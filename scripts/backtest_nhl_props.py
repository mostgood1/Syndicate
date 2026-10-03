"""Backtest: does the NHL player-prop sim (hockeysim) predict player box stats?

WHAT IT MEASURES. The production props producer is
`scripts/build_nhl_artifacts.py::build_props_for_date` -> `loaders.build_slate_features` ->
`player_props.build_prop_projections` (n_sims runs of the real boxscore engine, per-player means
= `proj_lambda`), and the served CSV prices P(over) by Poisson from `proj_lambda`
(`build_nhl_artifacts._poisson_p_over`). This harness runs THAT path, unmodified, over historical
dates whose inputs were rebuilt AS-OF each date, then scores every projected player-game against
the real boxscore, joined by `player_id` (never by name):

  * point accuracy per market (SOG / GOALS / ASSISTS / POINTS / BLOCKS for skaters, F and D split;
    SAVES for the sim's designated starting goalie) -- n, mean actual, mean projected, bias, MAE,
    RMSE -- against three naive baselines: (a) the player's as-of per-game average (season to date;
    for the 2026-27 arm the prior season), (b) his last-10-games average, (c) the league positional
    mean as-of. MAE delta vs (a) carries a GAME-clustered bootstrap 95% CI.
  * probability quality at standard lines (SOG 1.5/2.5/3.5, GOALS 0.5, ASSISTS 0.5, POINTS 0.5/1.5,
    BLOCKS 1.5, SAVES 22.5/25.5/28.5): Brier + log-loss of the PRODUCTION price (Poisson from
    proj_lambda) and of the empirical sim fraction, against Poisson(baseline a); decile
    reliability tables.
  * selection: players the sim lineup carried who did not play, players who played but were not in
    the sim lineup (rate + share of the actual stat), and players carried with no `line_slot`.
  * vs the book, where lines exist (2026 playoffs, 2026-27 opening dates): proportional de-vig of
    every two-sided line, model vs book Brier/log-loss on the SAME rows, and hit rate / flat-stake
    ROI of the model's side where model EV > 0. One-sided lines are excluded and counted.

WHERE THE INPUTS COME FROM, AND WHAT IS AS-OF (production has the same file contract):
  * scoreboard `data/odds/games/date=<d>/scoreboard.csv` -- written per date from the boxscores.
  * `lineups_/roster_snapshot_/starting_goalies_<d>.csv` -- written by the PRODUCTION collector
    `ingestion/collect.py::collect_slate_inputs`, unmodified, with an `NhlWebIngestClient` whose
    HTTP is disk-cached under the scratch dir. Its `recent_finished_game_ids` is the production
    function: the club-schedule endpoint lists the whole season, and production itself filters to
    `gameDate < date` and finished -- so a schedule fetched today yields exactly the as-of window.
    Roster full names come from the roster endpoint fetched today (names only; the join is by id).
  * season files `team_rates_ / player_rates_ / team_xg_ / team_elo_ / team_special_teams_` --
    rebuilt PER DATE from games STRICTLY BEFORE the date, with the producers' own aggregation
    functions and `_write_csv` (imported from `scripts/build_nhl_*_artifact.py`). The xG logistic
    model is RE-FIT per date on pre-date shots (the producer fits once on the full season). For the
    2026 playoffs and the 2026-27 arm the producers' own filter (regular season only) makes the full
    2025-26 regular season the correct as-of input; the 2026-27 arm writes ONLY `*_latest.csv`
    because production has no 2026-2027 season files and falls back to `_latest`.
  * NOT as-of (frozen, stated in the report): the engine's `SimConfig` constants
    (`calibration_profile.py`), several of which were fit against the 1,312-game 2025-26 truth
    snapshot -- in-sample for the regular-season arm, out-of-sample for playoffs and 2026-27.
    The harness does not tune or replace them.

DATA SOURCES. Boxscores + play-by-play + landings: `<src>/data/ingestion_cache` and
`<src>/data/truth/raw` (read-only); playoff and 2026-27 boxscores fetched from api-web.nhle.com into
`<out>/cache`. Book lines: `<src>/data/props/player_props_lines` and
`<src>/source_artifacts/data/props/player_props_lines`; 2026-09-30..10-04 lines live only on the
fleet disk and are READ via `wsl cat` (`--fleet-lines`), copied to `<out>/lines`.

HONESTY RULES BUILT IN:
  * the INTERSECTION is reported, never the union: every population prints how many player-games
    were dropped and why (did not play, no projection, no baseline);
  * `n` travels with every statistic, and no skill verdict is emitted below `--min-n`;
  * the harness never SUPPLIES an input production does not have: no actual lineup, no actual
    starting goalie, no future game enters any input;
  * "no skill" is a result and is printed as such;
  * the sample capture is a pass-through hook on `aggregate_events_to_boxscores_fast`; every game
    asserts the captured mean equals production's `proj_lambda`, so the analysed distribution is
    the one production averaged.

Usage:
  py -3 scripts/backtest_nhl_props.py --src <repo>/data/nhl_source --out C:/tmp/nhlprops/bt \\
      --arms regular,playoff,current --fleet-lines --workers 10
  py -3 scripts/backtest_nhl_props.py ... --analyze-only     # re-score cached sim results
"""
from __future__ import annotations

import argparse
import bisect
import csv
import importlib.util
import io
import json
import math
import os
import pickle
import random
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NHLE = "https://api-web.nhle.com/v1"
FINISHED = {"OFF", "FINAL"}
SKATER_MARKETS = ("SOG", "GOALS", "ASSISTS", "POINTS", "BLOCKS")
STANDARD_LINES = {
    "SOG": (1.5, 2.5, 3.5), "GOALS": (0.5,), "ASSISTS": (0.5,), "POINTS": (0.5, 1.5),
    "BLOCKS": (1.5,), "SAVES": (22.5, 25.5, 28.5),
}
STAT_KEY = {"SOG": "sog", "GOALS": "g", "ASSISTS": "a", "POINTS": "pts", "BLOCKS": "blk", "SAVES": "sv"}
SEASON_PREV = 20252026
SEASON_CUR = 20262027


# ---------------------------------------------------------------------------
# small utils
# ---------------------------------------------------------------------------

def _load_script(name: str):
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_bt_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _read_json(path: Path) -> Optional[Dict]:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _toi_min(v: object) -> float:
    s = str(v or "")
    if ":" not in s:
        return 0.0
    m, sec = s.split(":", 1)
    try:
        return int(m) + int(sec) / 60.0
    except ValueError:
        return 0.0


def _name(v: object) -> str:
    return str((v or {}).get("default") or "").strip() if isinstance(v, dict) else str(v or "").strip()


class CachedHttp:
    """Disk-cached GET for the public api-web host (schedule / roster / boxscore / score)."""

    def __init__(self, cache: Path, allow_net: bool, rate: float = 5.0) -> None:
        self.cache = cache
        self.allow = allow_net
        self.min_int = 1.0 / rate
        self.last = 0.0
        self.calls = 0

    def key(self, url: str) -> Path:
        tail = url.replace(NHLE, "").strip("/").replace("/", "__")
        return self.cache / "http" / f"{tail}.json"

    def get(self, url: str, *, refresh: bool = False) -> Optional[Dict]:
        p = self.key(url)
        if not refresh:
            d = _read_json(p)
            if d is not None:
                return d
        if not self.allow:
            return None
        wait = self.min_int - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        self.calls += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Syndicate nhl props backtest)"})
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (public host)
                d = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            if "404" in str(exc):
                return None
            print(f"  GET failed {url}: {exc}", flush=True)
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")
        return d


def _boxscore_path(gid: str, src: Path, out: Path) -> Optional[Path]:
    for d in (src / "data" / "ingestion_cache", out / "cache"):
        p = d / f"boxscore_{gid}.json"
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


# ---------------------------------------------------------------------------
# 1. discovery + fetch
# ---------------------------------------------------------------------------

def discover(src: Path, out: Path, allow_net: bool, today: str) -> Dict[str, Dict]:
    """Club schedules (both seasons) -> every finished game we need; fetch missing boxscores.
    Returns the game index {gid: meta} over games whose boxscore is available."""
    http = CachedHttp(out / "cache", allow_net)
    cache_dir = src / "data" / "ingestion_cache"
    teams = set()
    for p in sorted(cache_dir.glob("boxscore_20250200*.json"))[:40]:
        b = _read_json(p) or {}
        for side in ("homeTeam", "awayTeam"):
            teams.add(str((b.get(side) or {}).get("abbrev") or "").upper())
    teams.discard("")
    sched: Dict[str, Dict] = {}
    for season in (SEASON_PREV, SEASON_CUR):
        for t in sorted(teams):
            # the current season's schedule is refreshed once per run (states move); the past is fixed
            url = f"{NHLE}/club-schedule-season/{t}/{season}"
            d = http.get(url, refresh=(season == SEASON_CUR and allow_net and not os.environ.get("BT_NO_REFRESH")))
            for g in (d or {}).get("games", []):
                gid = str(g.get("id"))
                sched[gid] = {
                    "gid": gid, "season": int(g.get("season") or season), "gtype": int(g.get("gameType") or 0),
                    "date": str(g.get("gameDate") or "")[:10], "state": str(g.get("gameState") or ""),
                    "home": str((g.get("homeTeam") or {}).get("abbrev") or "").upper(),
                    "away": str((g.get("awayTeam") or {}).get("abbrev") or "").upper(),
                    "start": str(g.get("startTimeUTC") or ""),
                }
            # roster full names (the production collector asks for these too)
            http.get(f"{NHLE}/roster/{t}/{season}")
    want = [m for m in sched.values()
            if m["state"] in FINISHED and m["date"] < today
            and ((m["season"] == SEASON_PREV and m["gtype"] in (2, 3)) or (m["season"] == SEASON_CUR and m["gtype"] in (1, 2)))]
    fetched = 0
    for m in sorted(want, key=lambda r: r["gid"]):
        if _boxscore_path(m["gid"], src, out) is None and allow_net:
            d = http.get(f"{NHLE}/gamecenter/{m['gid']}/boxscore")
            if d is not None:
                (out / "cache").mkdir(parents=True, exist_ok=True)
                (out / "cache" / f"boxscore_{m['gid']}.json").write_text(json.dumps(d), encoding="utf-8")
                fetched += 1
    index: Dict[str, Dict] = {}
    for m in want:
        if _boxscore_path(m["gid"], src, out) is not None:
            index[m["gid"]] = m
    print(f"discover: schedule games={len(sched)} finished-wanted={len(want)} with boxscore={len(index)} "
          f"(fetched {fetched} now, http calls {http.calls})", flush=True)
    (out / "game_index.json").write_text(json.dumps({"index": index, "schedule": sched}), encoding="utf-8")
    return index


# ---------------------------------------------------------------------------
# 2. one-pass parse of everything the as-of builders and the scorer need
# ---------------------------------------------------------------------------

def parse_records(src: Path, out: Path, index: Dict[str, Dict]) -> Dict:
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import parse_boxscore_block_rate
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import parse_boxscore_shot_strength
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (
        parse_playbyplay_faceoffs_by_role, parse_playbyplay_faceoffs_by_zone, parse_playbyplay_faceoffs_ev)
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import parse_landing
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (
        parse_boxscore_player_rates, parse_playbyplay_player_faceoffs, parse_playbyplay_roster_names)
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.shot_xg_model import parse_play_by_play_shots
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import build_game_team_rates

    cache_dir = src / "data" / "ingestion_cache"
    truth_dir = src / "data" / "truth" / "raw"
    season_recs: Dict[str, Dict] = {}   # 2025-26 regular-season builder inputs, by gid
    actuals: Dict[str, Dict] = {}       # every indexed game: compact per-player box
    t0 = time.time()
    for i, (gid, m) in enumerate(sorted(index.items())):
        box = _read_json(_boxscore_path(gid, src, out))  # type: ignore[arg-type]
        if not box:
            continue
        players = []
        pbg = box.get("playerByGameStats") or {}
        for side, ab in (("homeTeam", m["home"]), ("awayTeam", m["away"])):
            st = pbg.get(side) or {}
            for grp, pos in (("forwards", "F"), ("defense", "D"), ("goalies", "G")):
                for p in st.get(grp) or []:
                    if p.get("playerId") is None:
                        continue
                    players.append({
                        "pid": int(p["playerId"]), "team": ab, "pos": pos, "name": _name(p.get("name")),
                        "toi": round(_toi_min(p.get("toi")), 3),
                        "sog": int(p.get("sog") or 0), "g": int(p.get("goals") or 0),
                        "a": int(p.get("assists") or 0), "pts": int(p.get("points") or 0),
                        "blk": int(p.get("blockedShots") or 0), "sv": int(p.get("saves") or 0),
                        "starter": bool(p.get("starter")) if pos == "G" else None,
                    })
        actuals[gid] = {**m, "home_name": (_name((box.get("homeTeam") or {}).get("placeName")) + " " + _name((box.get("homeTeam") or {}).get("commonName"))).strip(),
                        "away_name": (_name((box.get("awayTeam") or {}).get("placeName")) + " " + _name((box.get("awayTeam") or {}).get("commonName"))).strip(),
                        "start": str(box.get("startTimeUTC") or m.get("start") or ""), "players": players}
        if m["season"] == SEASON_PREV and m["gtype"] == 2:
            pbp = _read_json(cache_dir / f"playbyplay_{gid}.json")
            landing = _read_json(truth_dir / f"landing_{gid}.json")
            rec = {"date": m["date"]}
            rec["team_rates"] = build_game_team_rates([box], {gid: pbp} if pbp else {}).get(gid)
            rec["players"] = parse_boxscore_player_rates(box)
            rec["shot_str"] = parse_boxscore_shot_strength(box)
            rec["block"] = parse_boxscore_block_rate(box)
            rec["landing"] = parse_landing(landing) if landing else None
            if pbp:
                rec["pfo"] = parse_playbyplay_player_faceoffs(pbp)
                rec["pnames"] = parse_playbyplay_roster_names(pbp)
                rec["fo_ev"] = parse_playbyplay_faceoffs_ev(pbp)
                rec["fo_zone"] = parse_playbyplay_faceoffs_by_zone(pbp)
                rec["fo_role"] = parse_playbyplay_faceoffs_by_role(pbp)
                rec["shots"] = parse_play_by_play_shots(pbp)
                home, away = pbp.get("homeTeam") or {}, pbp.get("awayTeam") or {}
                rec["team_map"] = ({"home_id": int(home["id"]), "home_abbr": str(home.get("abbrev") or "").upper(),
                                    "away_id": int(away["id"]), "away_abbr": str(away.get("abbrev") or "").upper()}
                                   if home.get("id") is not None and away.get("id") is not None else None)
            season_recs[gid] = rec
        if i % 200 == 0:
            print(f"  parsed {i}/{len(index)} ({time.time() - t0:.0f}s)", flush=True)
    data = {"season_recs": season_recs, "actuals": actuals}
    with (out / "records.pkl").open("wb") as fh:
        pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"parse: {len(season_recs)} 2025-26 regular-season builder records, {len(actuals)} actual boxes "
          f"({time.time() - t0:.0f}s)", flush=True)
    return data


# ---------------------------------------------------------------------------
# 3. as-of season inputs (producers' own aggregation + writers)
# ---------------------------------------------------------------------------

def write_season_inputs(proc: Path, season_recs: Dict[str, Dict], cutoff: str, *, latest_only: bool) -> Dict:
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import compute_team_block_rate_index
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import compute_team_shot_rate_index
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.elo_builder import compute_elo_progression
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_ev_index import (
        compute_team_faceoff_dz_index, compute_team_faceoff_ev_index, compute_team_faceoff_nz_index,
        compute_team_faceoff_oz_index, compute_team_faceoff_pk_role_index, compute_team_faceoff_pp_role_index)
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (
        compute_player_faceoff_aggregates, compute_player_rate_aggregates)
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.shot_xg_model import featurize
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.special_teams_builder import compute_special_teams_rates
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import compute_team_rate_aggregates

    tr_mod = _load_script("build_nhl_team_rates_artifact")
    pr_mod = _load_script("build_nhl_player_rates_artifact")
    st_mod = _load_script("build_nhl_special_teams_artifact")
    elo_mod = _load_script("build_nhl_elo_artifact")
    xg_mod = _load_script("build_nhl_xg_artifact")

    recs = [r for _gid, r in sorted(season_recs.items()) if r["date"] < cutoff]
    names = (["latest"] if latest_only else ["2025-2026", "latest"])

    def _paths(stem: str) -> List[Path]:
        return [proc / f"{stem}_{n}.csv" for n in names]

    proc.mkdir(parents=True, exist_ok=True)
    tr = compute_team_rate_aggregates([r["team_rates"] for r in recs if r.get("team_rates")])
    for p in _paths("team_rates"):
        tr_mod._write_csv(p, tr)
    pagg = compute_player_rate_aggregates([x for r in recs for x in r["players"]])
    pfo_recs = [r for r in recs if "pfo" in r]
    fagg = compute_player_faceoff_aggregates([r["pfo"] for r in pfo_recs], [r["pnames"] for r in pfo_recs])
    for p in _paths("player_rates"):
        pr_mod._write_csv(p, pagg, fagg)
    landings = [r["landing"] for r in recs if r.get("landing") is not None and int(r["landing"].game_type) == 2]
    rates = compute_special_teams_rates(landings)
    shot_recs = [r["shot_str"] for r in recs if r.get("shot_str") is not None]
    block_recs = [r["block"] for r in recs if r.get("block") is not None]
    shot_idx = compute_team_shot_rate_index(shot_recs, {t: v.pp_opportunities for t, v in rates.items()},
                                            {t: v.pk_opportunities for t, v in rates.items()}) if shot_recs else {}
    block_idx = compute_team_block_rate_index(block_recs) if block_recs else {}
    ev = [r["fo_ev"] for r in recs if r.get("fo_ev") is not None]
    zone = [r["fo_zone"] for r in recs if r.get("fo_zone") is not None]
    role = [r["fo_role"] for r in recs if r.get("fo_role") is not None]
    fo_idx = compute_team_faceoff_ev_index(ev) if ev else {}
    oz = compute_team_faceoff_oz_index(zone) if zone else {}
    dz = compute_team_faceoff_dz_index(zone) if zone else {}
    nz = compute_team_faceoff_nz_index(zone) if zone else {}
    ppr = compute_team_faceoff_pp_role_index(role) if role else {}
    pkr = compute_team_faceoff_pk_role_index(role) if role else {}
    for p in _paths("team_special_teams"):
        st_mod._write_csv(p, rates, shot_idx, block_idx, fo_idx, oz, dz, nz, ppr, pkr)
    final, _pre = compute_elo_progression(landings)
    for p in _paths("team_elo"):
        elo_mod._write_csv(p, final)
    # xG: re-fit the producer's logistic model on PRE-DATE shots, then aggregate exactly as
    # `build_nhl_xg_artifact.main` does (xG per game played, both sides).
    shots = [s for r in recs for s in (r.get("shots") or [])]
    team_map = {}
    for r in recs:
        if r.get("team_map") and r.get("shots") is not None:
            gid = r["shots"][0].game_id if r["shots"] else None
            if gid:
                team_map[gid] = r["team_map"]
    xg_games = 0
    if len(shots) > 500 and sum(1 for s in shots if s.is_goal) > 20:
        model = xg_mod._fit_logistic(featurize(shots), [1 if s.is_goal else 0 for s in shots])
        proba = model.predict_proba(featurize(shots))[:, 1]
        xgf: Dict[str, float] = defaultdict(float)
        xga: Dict[str, float] = defaultdict(float)
        gp: Dict[str, set] = defaultdict(set)
        for s, x in zip(shots, proba):
            meta = team_map.get(s.game_id)
            if not meta:
                continue
            if s.team_id == meta["home_id"]:
                sh, de = meta["home_abbr"], meta["away_abbr"]
            elif s.team_id == meta["away_id"]:
                sh, de = meta["away_abbr"], meta["home_abbr"]
            else:
                continue
            xgf[sh] += float(x)
            xga[de] += float(x)
        for gid, meta in team_map.items():
            gp[meta["home_abbr"]].add(gid)
            gp[meta["away_abbr"]].add(gid)
        xgf60 = {a: xgf[a] / max(1, len(gp[a])) for a in gp}
        xga60 = {a: xga[a] / max(1, len(gp[a])) for a in gp}
        for p in _paths("team_xg"):
            xg_mod._write_csv(p, xgf60, xga60, {a: len(g) for a, g in gp.items()})
        xg_games = len(team_map)
    return {"cutoff": cutoff, "games": len(recs), "teams_rates": len(tr), "players_rated": len(pagg),
            "faceoff_players": len(fagg), "special_teams_teams": len(rates), "elo_teams": len(final),
            "xg_games": xg_games, "files": names}


# ---------------------------------------------------------------------------
# 4. per-date worker: inputs -> production collector -> production loaders -> production props
# ---------------------------------------------------------------------------

_W: Dict = {}


def _worker_init(src: str, out: str, allow_net: bool) -> None:
    _W["src"] = Path(src)
    _W["out"] = Path(out)
    _W["allow_net"] = allow_net
    with (Path(out) / "records.pkl").open("rb") as fh:
        _W["data"] = pickle.load(fh)


def _team_name_for(abbr: str, hint: str) -> str:
    from syndicate.local_nhl_odds import TEAM_NAME_TO_ABBR, _team_abbr
    if hint and _team_abbr(hint) == abbr:
        return hint
    for name, ab in TEAM_NAME_TO_ABBR.items():
        if ab == abbr and _team_abbr(name) == abbr:
            return name
    return hint


def _make_client(src: Path, out: Path, allow_net: bool):
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient

    http = CachedHttp(out / "cache", allow_net)

    class BacktestClient(NhlWebIngestClient):
        """Production client; only the transport differs: GETs are served from the scratch disk
        cache (fetched once, at discovery) and boxscores are read from the read-only source cache
        first. Every method production calls -- `recent_finished_game_ids`, `roster_full_names`,
        `boxscore` -- is the INHERITED production implementation."""

        def _get(self, url: str):  # noqa: D401
            return http.get(url)

        def roster_full_names(self, team_abbr, season):
            # The roster endpoint has NO as-of history: fetched today, a PAST season's roster is the
            # end-of-season one (~23 players). Since collect.py dresses only rostered players, using it
            # for 2025-26 dates stripped real players (13-17 slotted skaters of 18 on 2025-10-15) and
            # read as a +0.14 SOG MAE regression. Past seasons therefore get no roster (no filter, no
            # full names -- this harness joins by player_id); the current season keeps production's.
            if str(season) != str(SEASON_CUR):
                return {}
            return super().roster_full_names(team_abbr, season)

        def boxscore(self, game_id, *, use_cache: bool = True):
            p = _boxscore_path(str(game_id), src, out)
            if p is not None:
                return _read_json(p)
            return super().boxscore(game_id, use_cache=use_cache)

    return BacktestClient(cache_dir=out / "cache", rate_limit_per_sec=0, offline=not allow_net)


def run_date(date: str, arm: str, n_sims: int) -> Dict:
    import syndicate.features.nhl.sim_engine.hockeysim.player_props as pp
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import build_slate_features
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs

    src, out = _W["src"], _W["out"]
    data = _W["data"]
    t0 = time.time()
    root = out / "roots" / date
    proc = root / "data" / "processed"
    games = sorted([a for a in data["actuals"].values() if a["date"] == date], key=lambda a: a["gid"])
    sb = root / "data" / "odds" / "games" / f"date={date}" / "scoreboard.csv"
    sb.parent.mkdir(parents=True, exist_ok=True)
    with sb.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["gamePk", "gameDate", "home", "away", "home_goals", "away_goals", "gameState", "period", "clock"])
        for g in games:
            w.writerow([g["gid"], g["start"], _team_name_for(g["home"], g["home_name"]),
                        _team_name_for(g["away"], g["away_name"]), "", "", "FUT", 1, ""])
    inputs = write_season_inputs(proc, data["season_recs"], date if arm == "regular" else "9999-12-31",
                                 latest_only=(arm == "current"))
    client = _make_client(src, out, _W["allow_net"])
    collect = collect_slate_inputs(date, root=root, client=client)
    collect = {k: v for k, v in collect.items() if not k.startswith("_")}
    t_inputs = time.time() - t0

    captured: List[Dict] = []
    orig = pp.aggregate_events_to_boxscores_fast

    def _hook(gs, events, starter_goalies=None):
        box = orig(gs, events, starter_goalies)
        captured.append({(str(t), int(pid)): tuple(row) for (t, pid, per), row in box.items() if int(per) == 0})
        return box

    pp.aggregate_events_to_boxscores_fast = _hook
    feats = {g.game_pk: g for g in build_slate_features(date, root=root)}
    results = []
    try:
        for g in games:
            gf = feats.get(g["gid"])
            if gf is None:
                results.append({"gid": g["gid"], "error": "no features"})
                continue
            captured.clear()
            projs = pp.build_prop_projections(gf, n_sims=n_sims)
            nsim = len(captured)
            team_ab = {gf.home.name: g["home"], gf.away.name: g["away"]}
            starter = {gf.home.name: pp._starter_goalie_id(gf.home_players), gf.away.name: pp._starter_goalie_id(gf.away_players)}
            proj_by = {(p.team, p.player_id, p.market): p.proj_lambda for p in projs}
            players = []
            for tname, plist in ((gf.home.name, gf.home_players), (gf.away.name, gf.away_players)):
                for p in plist:
                    pos = str(p.position).upper()
                    markets = ("SAVES",) if pos == "G" else SKATER_MARKETS
                    rec = {"pid": int(p.player_id), "team": team_ab[tname], "pos": pos, "name": p.full_name,
                           "line_slot": p.line_slot, "pp_unit": p.pp_unit, "pk_unit": p.pk_unit,
                           "proj_toi": p.proj_toi, "shot_weight": p.shot_weight,
                           "sim_starter": (pos == "G" and starter.get(tname) == int(p.player_id)), "m": {}}
                    for mk in markets:
                        idx = pp._MARKET_STAT_INDEX[mk]
                        vals = [c[(tname, int(p.player_id))][idx] for c in captured if (tname, int(p.player_id)) in c]
                        lam = proj_by.get((tname, int(p.player_id), mk))
                        if vals and lam is not None:
                            # production counts a sim without the player as a zero (player_props, defect 4)
                            mean = sum(vals) / max(len(vals), nsim)
                            assert abs(round(mean, 4) - lam) < 1e-6, (date, g["gid"], p.player_id, mk, mean, lam)
                        rec["m"][mk] = {"lam": lam, "rows": len(vals),
                                        "hist": dict(Counter(int(v) for v in vals)) if vals else {}}
                    players.append(rec)
            results.append({"gid": g["gid"], "n_sims": nsim, "players": players,
                            "team_goals_per_60": {g["home"]: gf.home.goals_per_60, g["away"]: gf.away.goals_per_60}})
    finally:
        pp.aggregate_events_to_boxscores_fast = orig
    res = {"date": date, "arm": arm, "inputs": inputs, "collect": collect, "games": results,
           "t_inputs": round(t_inputs, 1), "t_total": round(time.time() - t0, 1)}
    (out / "sim").mkdir(parents=True, exist_ok=True)
    (out / "sim" / f"{arm}_{date}.json").write_text(json.dumps(res), encoding="utf-8")
    return {"date": date, "arm": arm, "games": len(results), "t": res["t_total"]}


# ---------------------------------------------------------------------------
# 5. book lines
# ---------------------------------------------------------------------------

def load_book_lines(src: Path, out: Path, dates: List[str], fleet: bool) -> Dict[str, List[Dict]]:
    by_date: Dict[str, List[Dict]] = defaultdict(list)
    seen = set()
    roots = [src / "data" / "props" / "player_props_lines", src / "source_artifacts" / "data" / "props" / "player_props_lines"]
    texts: List[Tuple[str, str, str]] = []
    for d in dates:
        for r in roots:
            p = r / f"date={d}" / "oddsapi.csv"
            if p.exists() and p.stat().st_size > 0:
                texts.append((d, str(p), p.read_text(encoding="utf-8-sig")))
        if fleet:
            local = out / "lines" / f"fleet_{d}.csv"
            if not local.exists():
                try:
                    txt = subprocess.run(
                        ["wsl", "-e", "bash", "-lc", f"cat ~/syndicate-prod/data/nhl_source/data/props/player_props_lines/date={d}/oddsapi.csv"],
                        capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    txt = ""
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text(txt, encoding="utf-8")
            txt = local.read_text(encoding="utf-8")
            if txt.strip():
                texts.append((d, "fleet", txt))
    for d, origin, txt in texts:
        for row in csv.DictReader(io.StringIO(txt)):
            key = (d, row.get("player_name"), row.get("market"), row.get("line"), row.get("book"),
                   row.get("first_seen_at"), row.get("over_price"), row.get("under_price"))
            if key in seen:
                continue
            seen.add(key)
            row["_origin"] = origin
            by_date[d].append(row)
    return by_date


# ---------------------------------------------------------------------------
# 6. scoring
# ---------------------------------------------------------------------------

_PO = None  # production `build_nhl_artifacts._poisson_p_over`, bound in `score()`


def _clip(p: float, lo: float = 1e-3) -> float:
    return min(1 - lo, max(lo, p))


def _logloss(p: float, y: int) -> float:
    p = _clip(p)
    return -(math.log(p) if y else math.log(1 - p))


def _boot_ci(rows: List[Tuple[str, float]], n_boot: int = 1000, seed: int = 7) -> Tuple[float, float, float]:
    """Mean of per-row values with a GAME-clustered bootstrap 95% CI."""
    by_g: Dict[str, List[float]] = defaultdict(list)
    for g, v in rows:
        by_g[g].append(v)
    keys = list(by_g)
    sums = [sum(by_g[k]) for k in keys]
    cnts = [len(by_g[k]) for k in keys]
    if not keys:
        return (float("nan"),) * 3  # type: ignore[return-value]
    point = sum(sums) / sum(cnts)
    rng = random.Random(seed)
    stats = []
    n = len(keys)
    for _ in range(n_boot):
        s = c = 0.0
        for _j in range(n):
            i = rng.randrange(n)
            s += sums[i]
            c += cnts[i]
        stats.append(s / c)
    stats.sort()
    return point, stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1]


class History:
    """Per-player game history (played games only) for the as-of baselines."""

    def __init__(self, actuals: Dict[str, Dict]) -> None:
        self.h: Dict[int, List[Tuple[str, int, int, Dict]]] = defaultdict(list)
        self.pos_games: List[Tuple[str, str, Dict]] = []
        for a in actuals.values():
            for p in a["players"]:
                played = p["toi"] > 0 if p["pos"] != "G" else bool(p["starter"])
                if not played:
                    continue
                self.h[p["pid"]].append((a["date"], a["season"], a["gtype"], p))
                if a["gtype"] in (2, 3):
                    grp = p["pos"]
                    self.pos_games.append((a["date"], grp, p))
        for v in self.h.values():
            v.sort(key=lambda t: t[0])
        self.pos_games.sort(key=lambda t: t[0])
        self.pos_dates = [t[0] for t in self.pos_games]
        self._pos_cache: Dict[Tuple[str, str], Dict[str, float]] = {}

    def season_avg(self, pid: int, date: str, season: int, prior: bool) -> Tuple[Optional[Dict[str, float]], int]:
        games = [t[3] for t in self.h.get(pid, []) if t[0] < date and
                 ((t[1] == season) if not prior else (t[1] == season and t[2] in (2, 3)))]
        if not games:
            return None, 0
        return {k: sum(g[k] for g in games) / len(games) for k in STAT_KEY.values()}, len(games)

    def last_n(self, pid: int, date: str, n: int = 10) -> Tuple[Optional[Dict[str, float]], int]:
        games = [t[3] for t in self.h.get(pid, []) if t[0] < date and t[2] in (2, 3)][-n:]
        if not games:
            return None, 0
        return {k: sum(g[k] for g in games) / len(games) for k in STAT_KEY.values()}, len(games)

    def league_pos(self, date: str, grp: str) -> Dict[str, float]:
        key = (date, grp)
        if key not in self._pos_cache:
            i = bisect.bisect_left(self.pos_dates, date)
            rows = [t[2] for t in self.pos_games[:i] if t[1] == grp]
            if not rows:  # first date of a season with nothing prior: no baseline
                self._pos_cache[key] = {}
            else:
                self._pos_cache[key] = {k: sum(r[k] for r in rows) / len(rows) for k in STAT_KEY.values()}
        return self._pos_cache[key]


def _metrics(rows: List[Dict], pred_key: str) -> Dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    err = [r[pred_key] - r["y"] for r in rows]
    return {"n": n, "mean_pred": round(sum(r[pred_key] for r in rows) / n, 4),
            "bias": round(sum(err) / n, 4), "mae": round(sum(abs(e) for e in err) / n, 4),
            "rmse": round(math.sqrt(sum(e * e for e in err) / n), 4)}


def _reliability(ps: List[float], ys: List[int], bins: int = 10) -> List[Dict]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = []
    n = len(order)
    for b in range(bins):
        idx = order[b * n // bins:(b + 1) * n // bins]
        if not idx:
            continue
        out.append({"mean_pred": round(sum(ps[i] for i in idx) / len(idx), 4),
                    "obs": round(sum(ys[i] for i in idx) / len(idx), 4), "n": len(idx)})
    return out


def _american_to_dec(o) -> Optional[float]:
    """None for a price that is not a quotable American price (0, |o| < 100, None,
    text) -- 0 used to raise ZeroDivisionError here."""
    try:
        x = float(o)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or abs(x) < 100:
        return None
    return 1 + (x / 100.0 if x > 0 else 100.0 / -x)


def _implied(o) -> Optional[float]:
    """None for a price that is not a quotable American price -- 0 used to price as 0.0."""
    try:
        x = float(o)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or abs(x) < 100:
        return None
    return 100.0 / (x + 100.0) if x > 0 else -x / (-x + 100.0)


def score(out: Path, arms: List[str], min_n: int, lines_by_date: Dict[str, List[Dict]], runtime: Dict) -> Dict:
    global _PO
    from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import NHL_CALIBRATION_PROFILE_METADATA
    from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import initial_surname_key, normalize_name
    bna = _load_script("build_nhl_artifacts")
    _PO = bna._poisson_p_over

    with (out / "records.pkl").open("rb") as fh:
        data = pickle.load(fh)
    actuals = data["actuals"]
    hist = History(actuals)
    roster_names: Dict[int, str] = {}
    for p in (out / "cache" / "http").glob("roster__*.json"):
        d = _read_json(p) or {}
        for grp in ("forwards", "defensemen", "goalies"):
            for x in d.get(grp) or []:
                nm = " ".join(s for s in (_name(x.get("firstName")), _name(x.get("lastName"))) if s)
                if x.get("id") is not None and nm:
                    roster_names[int(x["id"])] = nm

    sr = data["season_recs"]
    fams = {"boxscore": {r["date"] for r in sr.values()},
            "playbyplay": {r["date"] for r in sr.values() if r.get("shots") is not None},
            "landing": {r["date"] for r in sr.values() if r.get("landing") is not None},
            "team_rates(box+pbp joined)": {r["date"] for r in sr.values() if r.get("team_rates") is not None}}
    coverage = {k: {"dates": len(v), "first": min(v) if v else None, "last": max(v) if v else None} for k, v in fams.items()}
    coverage["intersection_dates"] = len(set.intersection(*fams.values())) if fams else 0
    coverage["actual_boxscores_by_season_type"] = dict(Counter(f"{a['season']}/{a['gtype']}" for a in actuals.values()))
    print(f"2025-26 regular-season input coverage: {json.dumps(coverage)}", flush=True)
    report: Dict = {"input_coverage": coverage, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "min_n": min_n, "runtime": runtime,
                    "calibration_profile": str(NHL_CALIBRATION_PROFILE_METADATA), "arms": {}}
    for arm in arms:
        files = sorted((out / "sim").glob(f"{arm}_*.json"))
        sims = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        if not sims:
            continue
        A: Dict = {"dates": len(sims)}
        point_rows: Dict[str, List[Dict]] = defaultdict(list)
        prob_rows: Dict[Tuple[str, float], List[Dict]] = defaultdict(list)
        sel = Counter()
        sel_stat = Counter()
        sel_gt: Dict[int, Counter] = defaultdict(Counter)  # same counters split by gameType
        noslot_rows: List[Dict] = []
        cov_rows: List[Tuple[float, float]] = []
        drops = Counter()
        games_used = set()
        sim_rows_index: Dict[Tuple[str, int], Dict] = {}
        gtypes = Counter()
        slot_bias: Dict[str, List[float]] = defaultdict(list)
        for s in sims:
            for g in s["games"]:
                if "players" not in g:
                    drops["game_no_features"] += 1
                    continue
                act = actuals.get(g["gid"])
                if not act:
                    drops["game_no_actual"] += 1
                    continue
                gtypes[act["gtype"]] += 1
                sg = sel_gt[act["gtype"]]
                apl = {(p["team"], p["pid"]): p for p in act["players"]}
                sim_keys = {(p["team"], p["pid"]) for p in g["players"]}
                nsim = g["n_sims"]
                # selection: who played vs who the sim carried
                for p in g["players"]:
                    if p["pos"] == "G":
                        continue
                    a = apl.get((p["team"], p["pid"]))
                    played = bool(a and a["toi"] > 0)
                    slot = "slot" if p["line_slot"] else "noslot"
                    sel[f"sim_skater_{slot}"] += 1; sg[f"sim_skater_{slot}"] += 1
                    sel[f"sim_skater_{slot}_played"] += int(played); sg[f"sim_skater_{slot}_played"] += int(played)
                    if not p["line_slot"] and played:
                        mm = p["m"].get("SOG") or {}
                        noslot_rows.append({"proj": mm.get("lam"), "y": a["sog"], "toi": a["toi"], "proj_toi": p["proj_toi"]})
                for (team, pid), a in apl.items():
                    if a["pos"] == "G" or a["toi"] <= 0:
                        continue
                    sel["actual_skater_played"] += 1; sg["actual_skater_played"] += 1
                    for k in ("sog", "pts", "blk"):
                        sel_stat[f"total_{k}"] += a[k]
                    if (team, pid) not in sim_keys:
                        sel["actual_played_not_in_sim"] += 1; sg["actual_played_not_in_sim"] += 1
                        for k in ("sog", "pts", "blk"):
                            sel_stat[f"missing_{k}"] += a[k]
                # goalies: sim starter vs actual starter
                for team in (act["home"], act["away"]):
                    ss = [p for p in g["players"] if p["team"] == team and p.get("sim_starter")]
                    real = [p for p in act["players"] if p["team"] == team and p["pos"] == "G" and p["starter"]]
                    sel["goalie_team_games"] += 1; sg["goalie_team_games"] += 1
                    if ss and real and ss[0]["pid"] == real[0]["pid"]:
                        sel["goalie_starter_correct"] += 1; sg["goalie_starter_correct"] += 1
                    elif not ss:
                        sel["goalie_no_sim_starter"] += 1
                # point + probability rows
                for p in g["players"]:
                    a = apl.get((p["team"], p["pid"]))
                    grp = "G" if p["pos"] == "G" else p["pos"]
                    if grp == "G" and not p.get("sim_starter"):
                        continue
                    for mk, mm in p["m"].items():
                        if mm.get("lam") is None:
                            drops[f"{mk}_no_projection"] += 1
                            continue
                        if a is None or (a["toi"] <= 0 if grp != "G" else not a["starter"]):
                            drops[f"{mk}_did_not_play" if grp != "G" else "SAVES_sim_starter_did_not_start"] += 1
                            continue
                        if arm == "current":
                            ba, nga = hist.season_avg(p["pid"], s["date"], SEASON_PREV, prior=True)
                        else:
                            ba, nga = hist.season_avg(p["pid"], s["date"], SEASON_PREV, prior=False)
                        bb, ngb = hist.last_n(p["pid"], s["date"], 10)
                        bc = hist.league_pos(s["date"], grp)
                        if ba is None or nga < 3 or bb is None or not bc:
                            drops[f"{mk}_no_baseline"] += 1
                            continue
                        y = a[STAT_KEY[mk]]
                        h = {int(k): v for k, v in mm["hist"].items()}
                        rws = sum(h.values())
                        cov_rows.append((rws / max(1, nsim), 1.0))
                        uncond = sum(k * v for k, v in h.items()) / max(1, nsim)
                        row = {"gid": g["gid"], "pid": p["pid"], "grp": grp, "y": y, "model": mm["lam"],
                               "uncond": uncond, "cov": rws / max(1, nsim),
                               "base_a": ba[STAT_KEY[mk]], "base_b": bb[STAT_KEY[mk]], "base_c": bc[STAT_KEY[mk]],
                               "slot": p["line_slot"] or "None", "gtype": act["gtype"]}
                        key = f"{mk}|{grp}" if mk != "SAVES" else "SAVES|G"
                        point_rows[key].append(row)
                        if mk != "SAVES":
                            point_rows[f"{mk}|ALL"].append(row)
                            if arm == "current":
                                point_rows[f"{mk}|ALL|gameType{act['gtype']}"].append(row)
                        if mk == "SOG":
                            slot_bias[row["slot"]].append(row["model"] - y)
                        games_used.add(g["gid"])
                        sim_rows_index[(g["gid"], p["pid"])] = {"lam": mm["lam"], "hist": h, "rows": rws, "y_all": a}
                        for ln in STANDARD_LINES.get(mk, ()):
                            pe = (sum(v for k, v in h.items() if k > ln) / rws) if rws else None
                            prob_rows[(mk, ln)].append({
                                "gid": g["gid"], "y": int(y > ln), "p_model": _PO(ln, mm["lam"]),
                                "p_emp": pe, "p_base": _PO(ln, ba[STAT_KEY[mk]])})
        # ---- point accuracy tables
        pt = {}
        for key, rows in sorted(point_rows.items()):
            m_model = _metrics(rows, "model")
            d_a = _boot_ci([(r["gid"], abs(r["model"] - r["y"]) - abs(r["base_a"] - r["y"])) for r in rows])
            pt[key] = {"n": len(rows), "games": len({r["gid"] for r in rows}),
                       "mean_actual": round(sum(r["y"] for r in rows) / len(rows), 4),
                       "model": m_model, "model_uncond_mean": round(sum(r["uncond"] for r in rows) / len(rows), 4),
                       "mean_coverage": round(sum(r["cov"] for r in rows) / len(rows), 4),
                       "base_a": _metrics(rows, "base_a"), "base_b": _metrics(rows, "base_b"),
                       "base_c": _metrics(rows, "base_c"),
                       "mae_delta_vs_a": {"point": round(d_a[0], 4), "ci95": [round(d_a[1], 4), round(d_a[2], 4)]},
                       "verdict": ("INSUFFICIENT_N" if len(rows) < min_n else
                                   ("MODEL_BETTER" if d_a[2] < 0 else ("MODEL_WORSE" if d_a[1] > 0 else "NO_DIFFERENCE")))}
        A["point"] = pt
        # ---- probability tables
        pr = {}
        for (mk, ln), rows in sorted(prob_rows.items()):
            n = len(rows)
            ys = [r["y"] for r in rows]
            out_r = {"n": n, "base_rate": round(sum(ys) / n, 4)}
            for k in ("p_model", "p_emp", "p_base"):
                rr = [r for r in rows if r[k] is not None]
                out_r[k] = {"n": len(rr), "mean_p": round(sum(r[k] for r in rr) / max(1, len(rr)), 4),
                            "brier": round(sum((r[k] - r["y"]) ** 2 for r in rr) / max(1, len(rr)), 5),
                            "logloss": round(sum(_logloss(r[k], r["y"]) for r in rr) / max(1, len(rr)), 5)}
            db = _boot_ci([(r["gid"], (r["p_model"] - r["y"]) ** 2 - (r["p_base"] - r["y"]) ** 2) for r in rows])
            out_r["brier_delta_model_vs_base"] = {"point": round(db[0], 5), "ci95": [round(db[1], 5), round(db[2], 5)]}
            out_r["verdict"] = ("INSUFFICIENT_N" if n < min_n else
                                ("MODEL_BETTER" if db[2] < 0 else ("MODEL_WORSE" if db[1] > 0 else "NO_DIFFERENCE")))
            out_r["reliability_model"] = _reliability([r["p_model"] for r in rows], ys)
            pr[f"{mk}_{ln}"] = out_r
        A["prob"] = pr
        # ---- selection
        A["selection"] = {
            "counts": dict(sel), "stat_totals": dict(sel_stat),
            "sim_slotted_skater_dnp_rate": round(1 - sel["sim_skater_slot_played"] / max(1, sel["sim_skater_slot"]), 4),
            "sim_noslot_skater_played_rate": round(sel["sim_skater_noslot_played"] / max(1, sel["sim_skater_noslot"]), 4),
            "actual_played_not_in_sim_rate": round(sel["actual_played_not_in_sim"] / max(1, sel["actual_skater_played"]), 4),
            "missing_share": {k: round(sel_stat[f"missing_{k}"] / max(1, sel_stat[f"total_{k}"]), 4) for k in ("sog", "pts", "blk")},
            "goalie_starter_accuracy": round(sel["goalie_starter_correct"] / max(1, sel["goalie_team_games"]), 4),
            "noslot_played": {"n": len(noslot_rows),
                              "mean_proj_sog": round(sum((r["proj"] or 0) for r in noslot_rows) / max(1, len(noslot_rows)), 4),
                              "mean_actual_sog": round(sum(r["y"] for r in noslot_rows) / max(1, len(noslot_rows)), 4),
                              "mean_actual_toi": round(sum(r["toi"] for r in noslot_rows) / max(1, len(noslot_rows)), 2),
                              "mean_proj_toi": round(sum((r["proj_toi"] or 0) for r in noslot_rows) / max(1, len(noslot_rows)), 2)},
            "by_game_type": {str(gt): {
                "slotted_dnp_rate": round(1 - c["sim_skater_slot_played"] / max(1, c["sim_skater_slot"]), 4),
                "actual_played_not_in_sim_rate": round(c["actual_played_not_in_sim"] / max(1, c["actual_skater_played"]), 4),
                "goalie_starter_accuracy": round(c["goalie_starter_correct"] / max(1, c["goalie_team_games"]), 4),
                "counts": dict(c)} for gt, c in sorted(sel_gt.items())},
            "sog_bias_by_line_slot": {k: {"n": len(v), "bias": round(sum(v) / len(v), 4)} for k, v in sorted(slot_bias.items())},
        }
        A["drops"] = dict(drops)
        A["games_scored"] = len(games_used)
        A["game_types"] = dict(gtypes)
        A["inputs_sample"] = sims[0].get("inputs")
        A["date_range"] = [sims[0]["date"], sims[-1]["date"]]
        # ---- vs book
        A["book"] = score_book(arm, sims, actuals, lines_by_date, roster_names, normalize_name, initial_surname_key, min_n)
        report["arms"][arm] = A
    return report


def score_book(arm, sims, actuals, lines_by_date, roster_names, normalize_name, initial_surname_key, min_n) -> Dict:
    stats = Counter()
    rows = []
    for s in sims:
        d = s["date"]
        lines = lines_by_date.get(d) or []
        if not lines:
            continue
        games = [g for g in s["games"] if "players" in g and g["gid"] in actuals]
        for ln in lines:
            stats["lines_raw"] += 1
            try:
                op = float(ln.get("over_price") or "nan")
                up = float(ln.get("under_price") or "nan")
                line = float(ln.get("line"))
            except ValueError:
                stats["unparseable"] += 1
                continue
            if math.isnan(op) or math.isnan(up):
                stats["one_sided_excluded"] += 1
                continue
            po, pu = _implied(op), _implied(up)
            dec_o, dec_u = _american_to_dec(op), _american_to_dec(up)
            if None in (po, pu, dec_o, dec_u):
                stats["invalid_price_excluded"] += 1
                continue
            mk = str(ln.get("market") or "").upper()
            nk = normalize_name(ln.get("player_name"))
            ik = initial_surname_key(ln.get("player_name"))
            ht, at = normalize_name(ln.get("home_team")), normalize_name(ln.get("away_team"))
            cand = []
            for g in games:
                act = actuals[g["gid"]]
                if ht and at and {ht, at} != {normalize_name(act["home_name"]), normalize_name(act["away_name"])}:
                    from syndicate.local_nhl_odds import _team_abbr
                    if {_team_abbr(ln.get("home_team")), _team_abbr(ln.get("away_team"))} != {act["home"], act["away"]}:
                        continue
                for p in act["players"]:
                    full = roster_names.get(p["pid"], "")
                    if (full and normalize_name(full) == nk) or (not full and initial_surname_key(p["name"]) == ik):
                        cand.append((g, act, p))
            if len({(c[0]["gid"], c[2]["pid"]) for c in cand}) != 1:
                stats["no_unique_player_match" if not cand else "ambiguous_match"] += 1
                continue
            g, act, p = cand[0]
            start = act["start"]
            fs = str(ln.get("first_seen_at") or "")
            if fs and start and fs >= start:
                stats["posted_after_start_excluded"] += 1
                continue
            played = p["toi"] > 0 if p["pos"] != "G" else bool(p["starter"])
            if not played:
                stats["player_did_not_play_void"] += 1
                continue
            sp = next((x for x in g["players"] if x["pid"] == p["pid"]), None)
            mm = (sp or {}).get("m", {}).get(mk) if sp else None
            if not mm or mm.get("lam") is None:
                stats["no_model_projection"] += 1
                continue
            if abs(line - round(line)) < 1e-9:
                stats["integer_line_excluded"] += 1
                continue
            y = int(p[STAT_KEY[mk]] > line)
            h = {int(k): v for k, v in mm["hist"].items()}
            rws = sum(h.values())
            rows.append({"gid": g["gid"], "date": d, "mk": mk, "pid": p["pid"], "line": line, "book": ln.get("book"),
                         "fs": fs, "y": y, "p_book": po / (po + pu), "vig": po + pu - 1,
                         "p_model": _PO(line, mm["lam"]), "p_emp": (sum(v for k, v in h.items() if k > line) / rws) if rws else None,
                         "dec_o": dec_o, "dec_u": dec_u})
    # keep the LATEST pregame snapshot per (game, player, market, line, book)
    latest: Dict[Tuple, Dict] = {}
    for r in rows:
        k = (r["gid"], r["pid"], r["mk"], r["line"], r["book"])
        if k not in latest or r["fs"] > latest[k]["fs"]:
            latest[k] = r
    stats["superseded_snapshots_dropped"] = len(rows) - len(latest)
    rows = list(latest.values())
    out: Dict = {"filter_counts": dict(stats), "n_rows": len(rows), "games": len({r["gid"] for r in rows}),
                 "dates": sorted({r["date"] for r in rows}), "by_market": {}}
    groups = defaultdict(list)
    for r in rows:
        groups[r["mk"]].append(r)
        groups["ALL"].append(r)
    for mk, rr in sorted(groups.items()):
        n = len(rr)
        res = {"n": n, "games": len({r["gid"] for r in rr}), "players": len({(r["gid"], r["pid"]) for r in rr}),
               "base_rate_over": round(sum(r["y"] for r in rr) / n, 4),
               "mean_p_book": round(sum(r["p_book"] for r in rr) / n, 4),
               "mean_p_model": round(sum(r["p_model"] for r in rr) / n, 4)}
        for k in ("p_book", "p_model", "p_emp"):
            q = [r for r in rr if r[k] is not None]
            res[k] = {"brier": round(sum((r[k] - r["y"]) ** 2 for r in q) / max(1, len(q)), 5),
                      "logloss": round(sum(_logloss(r[k], r["y"]) for r in q) / max(1, len(q)), 5), "n": len(q)}
        db = _boot_ci([(r["gid"], (r["p_model"] - r["y"]) ** 2 - (r["p_book"] - r["y"]) ** 2) for r in rr])
        res["brier_delta_model_vs_book"] = {"point": round(db[0], 5), "ci95": [round(db[1], 5), round(db[2], 5)]}
        bets = []
        for r in rr:
            ev_o = r["p_model"] * r["dec_o"] - 1
            ev_u = (1 - r["p_model"]) * r["dec_u"] - 1
            if max(ev_o, ev_u) <= 0:
                continue
            if ev_o >= ev_u:
                win = r["y"] == 1
                pnl = (r["dec_o"] - 1) if win else -1.0
                side = "over"
            else:
                win = r["y"] == 0
                pnl = (r["dec_u"] - 1) if win else -1.0
                side = "under"
            bets.append({"gid": r["gid"], "win": win, "pnl": pnl, "side": side})
        if bets:
            roi = _boot_ci([(b["gid"], b["pnl"]) for b in bets])
            res["ev_bets"] = {"n": len(bets), "hit_rate": round(sum(b["win"] for b in bets) / len(bets), 4),
                              "overs": sum(1 for b in bets if b["side"] == "over"),
                              "roi": round(roi[0], 4), "roi_ci95": [round(roi[1], 4), round(roi[2], 4)]}
        else:
            res["ev_bets"] = {"n": 0}
        res["verdict"] = "INSUFFICIENT_N" if n < min_n else (
            "MODEL_BETTER" if db[2] < 0 else ("MODEL_WORSE" if db[1] > 0 else "NO_DIFFERENCE"))
        out["by_market"][mk] = res
    return out


# ---------------------------------------------------------------------------
# 7. report
# ---------------------------------------------------------------------------

def write_md(report: Dict, path: Path) -> None:
    L = ["# NHL player-prop sim backtest (hockeysim)", "",
         f"generated {report['generated_at']}; min_n for any verdict = {report['min_n']}; "
         f"calibration profile: `{report['calibration_profile']}`", "",
         f"runtime: `{json.dumps(report['runtime'])}`", "",
         f"2025-26 regular-season builder-input coverage (per family, and intersection): `{json.dumps(report['input_coverage'])}`", ""]
    L += ["## inputs: as-of vs frozen", "",
          "- AS-OF (games strictly before the date): lineups/roster/starting goalies (production `collect_slate_inputs`, "
          "8-game TOI window from the club schedule filtered by production to gameDate < date); team_rates, player_rates "
          "(incl. faceoff_weight), team_special_teams (all indices), team_elo (inert: elo_blend_weight=0), team_xg "
          "(logistic re-fit per date on pre-date shots).",
          "- playoff + 2026-27 arms: the season files are the FULL 2025-26 regular season -- strictly prior, not a leak "
          "(the producers filter to gameType 2; 2026-27 has no season files so production reads `_latest`).",
          "- FROZEN / LEAKED: `SimConfig` constants in `calibration_profile.py` (special-teams shot/goal multipliers, block "
          "rates, faceoff decay curves) were fit on the full 1,312-game 2025-26 truth -- in-sample for the regular-season "
          "arm only. Roster FULL NAMES are fetched today (names only; every join is by player_id).",
          "- Not supplied by the harness: actual lineups, actual starting goalies, any post-date game.", ""]
    for arm, A in report["arms"].items():
        L += [f"## arm: {arm}", "",
              f"dates simulated {A['dates']} ({A['date_range'][0]}..{A['date_range'][1]}), games scored {A['games_scored']}, "
              f"game types {A['game_types']}", "", f"drops: `{json.dumps(A['drops'])}`", "",
              f"season inputs (first date): `{json.dumps(A['inputs_sample'])}`", "",
              "### point accuracy (model vs baselines a=as-of avg, b=last-10, c=league positional)", "",
              "| market|grp | n | games | mean act | mean proj | bias | MAE model | MAE a | MAE b | MAE c | dMAE vs a [95% CI] | RMSE model | RMSE a | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in A["point"].items():
            m, a, b, c = v["model"], v["base_a"], v["base_b"], v["base_c"]
            d = v["mae_delta_vs_a"]
            L.append(f"| {k} | {v['n']} | {v['games']} | {v['mean_actual']} | {m['mean_pred']} | {m['bias']} | {m['mae']} | "
                     f"{a['mae']} | {b['mae']} | {c['mae']} | {d['point']} [{d['ci95'][0]}, {d['ci95'][1]}] | {m['rmse']} | {a['rmse']} | {v['verdict']} |")
        L += ["", "### probability at standard lines (production price = Poisson(proj_lambda); emp = sim fraction; base = Poisson(as-of avg))", "",
              "| line | n | base rate | mean p model | Brier model | Brier emp | Brier base | dBrier model-base [CI] | LL model | LL emp | LL base | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in A["prob"].items():
            d = v["brier_delta_model_vs_base"]
            L.append(f"| {k} | {v['n']} | {v['base_rate']} | {v['p_model']['mean_p']} | {v['p_model']['brier']} | {v['p_emp']['brier']} | "
                     f"{v['p_base']['brier']} | {d['point']} [{d['ci95'][0]}, {d['ci95'][1]}] | {v['p_model']['logloss']} | "
                     f"{v['p_emp']['logloss']} | {v['p_base']['logloss']} | {v['verdict']} |")
        L += ["", "reliability (model, deciles: mean_pred -> observed):", ""]
        for k, v in A["prob"].items():
            L.append(f"- {k}: " + ", ".join(f"{r['mean_pred']}->{r['obs']}" for r in v["reliability_model"]))
        L += ["", "### selection", "", "```", json.dumps(A["selection"], indent=1), "```", "",
              "### vs book", "", f"filters: `{json.dumps(A['book'].get('filter_counts'))}`; rows {A['book'].get('n_rows')}, "
              f"games {A['book'].get('games')}, dates {A['book'].get('dates')}", "",
              "| market | n | games | over rate | Brier book | Brier model | Brier emp | dBrier model-book [CI] | LL book | LL model | EV bets n | hit | ROI [CI] | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for mk, v in A["book"].get("by_market", {}).items():
            e = v["ev_bets"]
            d = v["brier_delta_model_vs_book"]
            L.append(f"| {mk} | {v['n']} | {v['games']} | {v['base_rate_over']} | {v['p_book']['brier']} | {v['p_model']['brier']} | "
                     f"{v['p_emp']['brier']} | {d['point']} [{d['ci95'][0]}, {d['ci95'][1]}] | {v['p_book']['logloss']} | {v['p_model']['logloss']} | "
                     f"{e['n']} | {e.get('hit_rate', '')} | {e.get('roi', '')} {e.get('roi_ci95', '')} | {v['verdict']} |")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=Path(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or (REPO / "data" / "nhl_source")))
    ap.add_argument("--out", type=Path, default=Path(r"C:\tmp\nhlprops\bt"))
    ap.add_argument("--arms", default="regular,playoff,current")
    ap.add_argument("--start", default="2025-11-01", help="first regular-season date (as-of windows need >= 8 games)")
    ap.add_argument("--date-step", type=int, default=1, help="take every Nth regular-season date")
    ap.add_argument("--n-sims", type=int, default=200)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--no-net", action="store_true", help="never touch api-web (use only cached data)")
    ap.add_argument("--fleet-lines", action="store_true", help="READ 2026-09-30.. lines from the WSL fleet disk")
    ap.add_argument("--today", default=_date.today().isoformat())
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--limit-dates", type=int, default=0, help="debug: cap dates per arm")
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    t0 = time.time()
    runtime: Dict = {}

    if not args.analyze_only:
        index = discover(args.src, out, not args.no_net, args.today)
        runtime["discover_s"] = round(time.time() - t0, 1)
        if not (out / "records.pkl").exists() or os.environ.get("BT_REPARSE"):
            parse_records(args.src, out, index)
        runtime["parse_s"] = round(time.time() - t0, 1)
        with (out / "records.pkl").open("rb") as fh:
            acts = pickle.load(fh)["actuals"]
        dates_by_arm: Dict[str, List[str]] = {}
        reg = sorted({a["date"] for a in acts.values() if a["season"] == SEASON_PREV and a["gtype"] == 2 and a["date"] >= args.start})
        dates_by_arm["regular"] = reg[::max(1, args.date_step)]
        dates_by_arm["playoff"] = sorted({a["date"] for a in acts.values() if a["season"] == SEASON_PREV and a["gtype"] == 3})
        dates_by_arm["current"] = sorted({a["date"] for a in acts.values() if a["season"] == SEASON_CUR})[1:]  # day 1 has no prior game
        jobs = []
        for arm in arms:
            ds = dates_by_arm.get(arm, [])
            if args.limit_dates:
                ds = ds[:args.limit_dates]
            print(f"arm {arm}: {len(ds)} dates", flush=True)
            for d in ds:
                if not (out / "sim" / f"{arm}_{d}.json").exists():
                    jobs.append((d, arm))
        t1 = time.time()
        if jobs:
            with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init,
                                     initargs=(str(args.src), str(out), not args.no_net)) as ex:
                futs = {ex.submit(run_date, d, arm, args.n_sims): (d, arm) for d, arm in jobs}
                done = 0
                for f in as_completed(futs):
                    done += 1
                    try:
                        r = f.result()
                        print(f"  [{done}/{len(jobs)}] {r['arm']} {r['date']} games={r['games']} {r['t']}s "
                              f"(elapsed {time.time() - t1:.0f}s)", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [{done}/{len(jobs)}] FAILED {futs[f]}: {exc!r}", flush=True)
        runtime["sim_s"] = round(time.time() - t1, 1)
        runtime["n_sims"] = args.n_sims
        runtime["workers"] = args.workers
        runtime["date_step"] = args.date_step
        (out / "runtime.json").write_text(json.dumps(runtime), encoding="utf-8")
    elif (out / "runtime.json").exists():
        runtime = json.loads((out / "runtime.json").read_text(encoding="utf-8"))
        runtime["note"] = "sim timings from the last full run; this pass re-scored cached sim results"
    all_dates = sorted({f.stem.split("_", 1)[1] for f in (out / "sim").glob("*.json")})
    lines = load_book_lines(args.src, out, [d for d in all_dates if d >= "2026-04-01"], args.fleet_lines)
    report = score(out, arms, args.min_n, lines, runtime)
    report["runtime"]["score_s"] = round(time.time() - t0, 1)
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    write_md(report, out / "report.md")
    print(f"wrote {out / 'report.json'} and {out / 'report.md'} ({time.time() - t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
