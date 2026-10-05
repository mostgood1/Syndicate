"""NHL in-season season inputs: `team_rates_ / team_special_teams_ / player_rates_ / team_elo_<season>.csv`
rebuilt from the current season as games are played. Lane `nhl-season-inputs-in-season`; the sibling of
`inseason_team_xg.py` (team xG), which shipped first.

WHY. Production read FROZEN 2025-26 builds of these four files all of 2026-27: `_ensure_season_inputs`
only pulls a missing `_latest`, and nothing rebuilt them in-season. They feed the PROPS engine and the
faceoff model, not the game lines (the game lines read team xG only; Elo's blend weight is 0). Every
loader already prefers `<stem>_<season>.csv` over `<stem>_latest.csv` (`features/loaders.py`), so writing
the season file is the whole switch.

WHAT IT WRITES. Each `_latest` row, with the rate columns this season can update replaced by a count-level
empirical-Bayes blend in which last season enters as W games of pseudo-counts:
    rate = (W * prior_num_per_game + current_num) / (W * prior_den_per_game + current_den)
and every other column -- including the metadata (`games`, opportunities, draws) -- carried from `_latest` unchanged (the shot-strength and faceoff-zone/role indices
need inputs this module does not rebuild; they stay last season's, exactly as before). Only entities
present in `_latest` are written: a player with no prior row keeps the engine's own position/TOI fallback,
as before. `team_elo` carries last season's final rating regressed toward 1500 by ELO_REGRESSION, then
updates through this season's results (INERT in production: elo_blend_weight == 0).

MEASURED (scripts/nhl_season_inputs_fields_experiment.py): W per field chosen on 2024-25 (prior 2023-24),
checked on 2025-26 (prior 2024-25) by how well the as-of value forecasts the next game. See BLEND_W.

NEVER RAISES. Generation must still run: any failure returns a status dict and writes nothing, so the
loaders keep reading the previous file (or `_latest`).
"""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from syndicate.features.nhl.inseason_team_xg import finished_regular_games, season_code

# Pseudo-games of last season per field; math.inf would keep last season's value. Tuned on 2024-25 (prior
# 2023-24) and frozen; 2025-26 next-game MSE, blend vs prior-only (vs current-only):
BLEND_W: Dict[str, float] = {
    "team.shots": 5.0,          # -3.47% (-3.06%)  n=2,624 team-games
    "team.faceoff_pct": 20.0,   # -3.82% (-3.83%)
    "team.pp_pct": 40.0,        # -1.51% (-4.31%)  n=2,575
    "team.pk_ga_rate": 80.0,    # -0.87% (-3.92%)
    "team.committed": 20.0,     # -1.72% (-3.55%)
    "team.block_rate": math.inf,  # tuned W20 (-3.93%); kept at the prior -- see H16/H17 below
    "player.shots": 10.0,       # -4.38% (-4.16%)  n=47,231 player-games
    "player.goals": 20.0,       # -2.12% (-4.55%)
    "player.blocks": math.inf,  # tuned W10 (-3.14%); kept at the prior -- see H16/H17 below
}
# Last season's final Elo regressed 1/3 toward 1500 (tuned 2024-25; 2025-26 home-win Brier 0.2519 vs the
# frozen file's 0.2649). INERT: production's elo_blend_weight is 0.
# An entity's current season enters only once it has played this many games (0 = from game 1).
# User decision 2026-10-04: floor 10 with blocks at the prior (H17). Props A/B on 2025-26, 446 games, Brier at
# the lines vs prior: SOG@1.5 -0.00343 [-0.00453, -0.00228], POINTS@0.5 -0.00103 [-0.00169, -0.00034],
# no line worse from November; blocks blended made BLOCKS@1.5 worse in late October (H16) and gained
# nothing over the season, so they stay last season's.
MIN_CURRENT_GAMES = 10
ELO_REGRESSION = 1.0 / 3.0

FetchJson = Callable[[str], Any]


def _blend(w: float, p_num_pg: float, p_den_pg: float, c_num: float, c_den: float) -> Optional[float]:
    if w == math.inf or c_den <= 0:
        return p_num_pg / p_den_pg if p_den_pg > 0 else None
    den = w * p_den_pg + c_den
    return (w * p_num_pg + c_num) / den if den > 0 else None


def _read_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            r = csv.DictReader(fh)
            rows = list(r)
            return list(r.fieldnames or []), rows
    except OSError:
        return [], []


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _write_atomic(path: Path, header: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    os.replace(tmp, path)


def _load_or_fetch(cache: Path, name: str, url: str, fetch: FetchJson, counts: Dict[str, int],
                   ok: Callable[[Any], bool]) -> Optional[dict]:
    path = cache / name
    if path.exists() and path.stat().st_size > 0:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            counts["cached"] += 1
            return payload
        except (OSError, ValueError):
            pass
    payload = fetch(url)
    if not isinstance(payload, dict) or not ok(payload):
        counts["failed"] += 1
        return None
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    counts["fetched"] += 1
    return payload


def current_counts(games: List[dict]) -> Dict[str, Any]:
    """Season-to-date counts from parsed per-game payloads [{box, landing, pbp}].
    team[abbr][field] = [num, den, games]; player[pid][field] = [num, den]; elo = [HistoricalGameRecord]."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import parse_boxscore_block_rate
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import parse_landing
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import parse_boxscore_player_rates
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import (
        parse_boxscore_sog, parse_play_by_play_faceoffs)

    team: Dict[str, Dict[str, List[float]]] = {}
    player: Dict[int, Dict[str, List[float]]] = {}
    records = []

    def add(ent: Dict, key: Any, field: str, num: float, den: float) -> None:
        e = ent.setdefault(key, {}).setdefault(field, [0.0, 0.0])
        e[0] += num
        e[1] += den

    for g in games:
        box, land, pbp = g.get("box"), g.get("landing"), g.get("pbp")
        if not box:
            continue
        rec = parse_landing(land) if land else None
        if rec is None or int(rec.game_type) != 2:
            continue
        records.append(rec)
        h, a = rec.home_abbr, rec.away_abbr
        for t in (h, a):
            team.setdefault(t, {}).setdefault("_games", [0.0, 0.0])[0] += 1
        sog = parse_boxscore_sog(box) or {}
        add(team, h, "shots", float(sog.get("home_sog", rec.home_sog)), 1.0)
        add(team, a, "shots", float(sog.get("away_sog", rec.away_sog)), 1.0)
        fo = (parse_play_by_play_faceoffs(pbp) or {}) if pbp else {}
        if fo.get("home_wins") is not None and fo.get("away_wins") is not None and fo.get("total"):
            add(team, h, "faceoff_pct", float(fo["home_wins"]), float(fo["total"]))
            add(team, a, "faceoff_pct", float(fo["away_wins"]), float(fo["total"]))
        add(team, h, "pp_pct", float(rec.pp_goals_home), float(rec.penalties_committed_away))
        add(team, a, "pp_pct", float(rec.pp_goals_away), float(rec.penalties_committed_home))
        add(team, h, "pk_ga_rate", float(rec.pp_goals_away), float(rec.penalties_committed_home))
        add(team, a, "pk_ga_rate", float(rec.pp_goals_home), float(rec.penalties_committed_away))
        add(team, h, "committed", float(rec.penalties_committed_home), 1.0)
        add(team, a, "committed", float(rec.penalties_committed_away), 1.0)
        blk = parse_boxscore_block_rate(box)
        if blk is not None:
            add(team, h, "block_rate", float(blk.home_blocks), float(blk.home_shots_faced))
            add(team, a, "block_rate", float(blk.away_blocks), float(blk.away_shots_faced))
        for p in parse_boxscore_player_rates(box):
            pid = int(p.player_id)
            add(player, pid, "shots", float(p.shots), 1.0)
            add(player, pid, "goals", float(p.goals), 1.0)
            add(player, pid, "blocks", float(p.blocks), 1.0)
    return {"team": team, "player": player, "records": records}


def _games(fields: Dict) -> float:
    """Current-season games of one entity: teams carry `_games`; a player's shots denominator is games."""
    if "_games" in fields:
        return fields["_games"][0]
    return (fields.get("shots") or [0.0, 0.0])[1]


def _cur(ent: Dict, key: Any, field: str) -> Tuple[float, float]:
    """Current-season (num, den) of one field -- (0, 0), i.e. last season's value, until the entity has
    played MIN_CURRENT_GAMES this season."""
    fields = ent.get(key) or {}
    v = fields.get(field)
    if not v or _games(fields) < MIN_CURRENT_GAMES:
        return 0.0, 0.0
    return v[0], v[1]


def build_team_rates(prior: List[Dict[str, str]], team: Dict) -> List[Dict[str, Any]]:
    out = []
    for row in prior:
        ab = str(row.get("abbr") or "").upper()
        g = _f(row.get("games")) or 0.0
        new = dict(row)
        shots = _f(row.get("shots_per_60"))
        if shots is not None:
            v = _blend(BLEND_W["team.shots"], shots, 1.0, *_cur(team, ab, "shots"))
            new["shots_per_60"] = round(v, 4) if v is not None else row.get("shots_per_60")
        fo, fos = _f(row.get("faceoff_win_pct")), _f(row.get("faceoffs"))
        if fo is not None and fos and g > 0:
            v = _blend(BLEND_W["team.faceoff_pct"], fo * fos / g, fos / g, *_cur(team, ab, "faceoff_pct"))
            new["faceoff_win_pct"] = round(v, 4) if v is not None else row.get("faceoff_win_pct")
        out.append(new)
    return out


def build_special_teams(prior: List[Dict[str, str]], team: Dict) -> List[Dict[str, Any]]:
    # league block rate this season, for re-normalising the blended block rate to an index
    cur_blk = [v["block_rate"] for v in team.values() if "block_rate" in v]
    cur_league = (sum(b[0] for b in cur_blk) / sum(b[1] for b in cur_blk)) if cur_blk and sum(b[1] for b in cur_blk) > 0 else None
    out = []
    for row in prior:
        ab = str(row.get("abbr") or "").upper()
        g = _f(row.get("games")) or 0.0
        new = dict(row)
        if g > 0:
            ppo, ppg = _f(row.get("pp_opportunities")), _f(row.get("pp_goals"))
            if ppo and ppg is not None:
                v = _blend(BLEND_W["team.pp_pct"], ppg / g, ppo / g, *_cur(team, ab, "pp_pct"))
                if v is not None:
                    new["pp_pct"] = round(v, 4)
            pko, pkga = _f(row.get("pk_opportunities")), _f(row.get("pp_goals_against"))
            if pko and pkga is not None:
                v = _blend(BLEND_W["team.pk_ga_rate"], pkga / g, pko / g, *_cur(team, ab, "pk_ga_rate"))
                if v is not None:
                    new["pk_pct"] = round(1.0 - v, 4)
            com = _f(row.get("committed_per_game"))
            if com is not None:
                v = _blend(BLEND_W["team.committed"], com, 1.0, *_cur(team, ab, "committed"))
                if v is not None:
                    new["committed_per_game"] = round(v, 4)
        # block_rate_index is relative to the league: blend in index units, the current half measured against
        # this season's league rate, weighted by games (shots faced per game is near-constant).
        bi = _f(row.get("block_rate_index"))
        c_num, c_den = _cur(team, ab, "block_rate")
        n = (team.get(ab) or {}).get("_games", [0.0])[0]
        w = BLEND_W["team.block_rate"]
        if bi is not None and w != math.inf and c_den > 0 and n > 0 and cur_league:
            new["block_rate_index"] = round((w * bi + n * (c_num / c_den) / cur_league) / (w + n), 4)
        out.append(new)
    return out


def build_player_rates(prior: List[Dict[str, str]], player: Dict) -> List[Dict[str, Any]]:
    out = []
    for row in prior:
        try:
            pid = int(row.get("player_id") or "")
        except ValueError:
            out.append(dict(row))
            continue
        new = dict(row)
        for col, field in (("shot_weight", "shots"), ("goal_weight", "goals"), ("block_weight", "blocks")):
            pv = _f(row.get(col))
            if pv is None:
                continue
            v = _blend(BLEND_W[f"player.{field}"], pv, 1.0, *_cur(player, pid, field))
            if v is not None:
                new[col] = round(v, 4)
        out.append(new)
    return out


def build_team_elo(prior: List[Dict[str, str]], records: list) -> List[Dict[str, Any]]:
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.elo_builder import (
        DEFAULT_ELO_SCALE, DEFAULT_HOME_ADVANTAGE, DEFAULT_K, _expected_home_win_prob)

    ratings = {}
    for row in prior:
        e = _f(row.get("elo"))
        if e is not None:
            ratings[str(row.get("abbr") or "").upper()] = 1500.0 + (1.0 - ELO_REGRESSION) * (e - 1500.0)
    for rec in sorted(records, key=lambda r: (r.date or "9999-99-99", str(r.game_id))):
        ra, rb = ratings.get(rec.home_abbr, 1500.0), ratings.get(rec.away_abbr, 1500.0)
        p = _expected_home_win_prob(ra, rb, scale=DEFAULT_ELO_SCALE, home_advantage=DEFAULT_HOME_ADVANTAGE)
        d = DEFAULT_K * ((1.0 if rec.home_win else 0.0) - p)
        ratings[rec.home_abbr], ratings[rec.away_abbr] = ra + d, rb - d
    return [{**row, "elo": round(ratings.get(str(row.get("abbr") or "").upper(), _f(row.get("elo")) or 1500.0), 2)}
            for row in prior]


# ON from November 1 of each season (user decision 2026-10-04: "enable on Nov 1"). Every variant tested was
# no worse on any line from November on, while late-October games (teams crossing the floor) carried the only
# regressions. Before Nov 1 generation reads `_latest` as before. The env var overrides both ways:
# on/1/true forces it on, off/0/false forces it off.
ENABLE_ENV = "SYNDICATE_NHL_INSEASON_SEASON_INPUTS"
ENABLE_FROM_MONTH_DAY = (11, 1)


def enabled(env: Optional[Dict[str, str]] = None, today: Optional[date] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(ENABLE_ENV) or "").strip().lower()
    if raw in {"1", "true", "on", "yes"}:
        return True
    if raw in {"0", "false", "off", "no"}:
        return False
    today = today or date.today()
    return today >= date(int(season_code(today)[:4]), *ENABLE_FROM_MONTH_DAY)


STEMS = ("team_rates", "team_special_teams", "player_rates", "team_elo")
# A short `_latest` is a broken pull, not a prior: write nothing and let the loaders keep `_latest`.
MIN_PRIOR_ROWS = {"team_rates": 30, "team_special_teams": 30, "player_rates": 300, "team_elo": 30}


def refresh_inseason_season_inputs(artifact_root: Path, *, today: Optional[date] = None, fetch: Optional[FetchJson] = None,
                                   season_start: Optional[date] = None, base: str = "https://api-web.nhle.com/v1") -> Dict[str, Any]:
    """Rebuild `<root>/data/processed/<stem>_<season>.csv` for the four STEMS. Boxscores, landings and
    play-by-play are cached under `<root>/data/ingestion_cache/` (each fetched once)."""
    status: Dict[str, Any] = {"wrote": []}
    try:
        if fetch is None:
            from syndicate.features.nhl.boxscore_log import fetch_json as fetch
        today = today or date.today()
        season = season_code(today)
        season_start = season_start or date(int(season[:4]), 9, 15)
        processed = artifact_root / "data" / "processed"
        cache = artifact_root / "data" / "ingestion_cache"
        priors = {s: _read_rows(processed / f"{s}_latest.csv") for s in STEMS}
        status.update(season=season, prior_rows={s: len(v[1]) for s, v in priors.items()})
        if all(len(priors[s][1]) < MIN_PRIOR_ROWS[s] for s in STEMS):
            status["reason"] = "no usable *_latest.csv prior; nothing fetched or written"
            return status
        sched, unreadable = finished_regular_games(fetch, start=season_start, end=today, base=base, cache_dir=cache)
        status.update(finished_regular_games=len(sched), unreadable_days=len(unreadable))
        counts = {"cached": 0, "fetched": 0, "failed": 0}
        payloads = []
        for g in sched:
            gid = g["game_id"]
            box = _load_or_fetch(cache, f"boxscore_{gid}.json", f"{base}/gamecenter/{gid}/boxscore", fetch, counts,
                                 lambda p: bool(p.get("playerByGameStats")))
            land = _load_or_fetch(cache, f"landing_{gid}.json", f"{base}/gamecenter/{gid}/landing", fetch, counts,
                                  lambda p: bool(p.get("summary")))
            pbp = _load_or_fetch(cache, f"playbyplay_{gid}.json", f"{base}/gamecenter/{gid}/play-by-play", fetch, counts,
                                 lambda p: bool(p.get("plays")))
            payloads.append({"box": box, "landing": land, "pbp": pbp})
        status.update(payloads=counts)
        cur = current_counts(payloads)
        status["games_used"] = len(cur["records"])
        builders = {
            "team_rates": lambda rows: build_team_rates(rows, cur["team"]),
            "team_special_teams": lambda rows: build_special_teams(rows, cur["team"]),
            "player_rates": lambda rows: build_player_rates(rows, cur["player"]),
            "team_elo": lambda rows: build_team_elo(rows, cur["records"]),
        }
        for stem in STEMS:
            header, rows = priors[stem]
            if len(rows) < MIN_PRIOR_ROWS[stem]:
                status[f"{stem}_reason"] = f"prior {stem}_latest.csv missing or short ({len(rows)} rows); nothing written"
                continue
            out = processed / f"{stem}_{season}.csv"
            _write_atomic(out, header, builders[stem](rows))
            status["wrote"].append(out.name)
    except Exception as exc:  # noqa: BLE001 -- generation must still run on the previous files
        status["reason"] = f"error={type(exc).__name__}: {exc}"
    print(f"[nhl_inseason_inputs] NHL_INSEASON_SEASON_INPUTS {json.dumps(status, sort_keys=True)}", flush=True)
    return status
