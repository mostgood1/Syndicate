"""Basketball interval-projection REPLAY BACKTEST: the bar every Phase 2 engine change must beat.

User 2026-11-07, Phase 2 step 1 of the interval-projection plan (lane `basketball-interval-backtest`). For every
completed game in a corpus it steps through the play-by-play every 30 s of regulation clock, rebuilds the state the
live path would have built from the log so far, asks each projector for the projected full-game / h1 / h2 / (quarter
leagues) q1-q4 total and home margin, and scores them against the actual results. The machinery is
`syndicate/features/shared/basketball_interval_backtest.py`; this script loads games and writes a report.

READ-ONLY. It opens files under `--data-root` for reading and writes only under `--out`. It fetches nothing.

SUBSTRATE (`CLAUDE.md`: Render / the fleet is the source of truth, the repo's data/ is a lossy mirror). Point
`--data-root` at the fleet's production root (`/home/amyn/syndicate-prod/data`). Families read:
  every league   <league>_source/data/processed/rotation_stints/games_<date>.csv     (official finals, phase)
                 <league>_source/data/processed/rotation_stints/player_checks_<date>.csv (box: names, starters)
                 <league>_source/data/processed/pbp_events/<season>/<event_id>.jsonl.gz  (the typed event log)
  ncaab          ncaab_source/data/pbp_corpus/pbp_corpus_<season>.jsonl.gz  (team ids, neutral site, ESPN BET
                 close, box rows for the walk-forward team ratings) and processed/player_game_box_<season>.csv
                 (walk-forward player priors) -- exactly the P4 backtest's inputs (`ncaab_live_resim_backtest.py`)
  nba / wnba     <league>_source/data/processed/engine_inputs/<date>/<H>_<A>.pkl  (production's pregame engine
                 inputs; the re-sim resumes from them) and processed/smart_sim_<date>_<H>_<A>.json (the pregame
                 line at sim time and the 3-minute ladder the NBA tick reads)
Per-family date coverage and the intersection are printed BEFORE any number, and every number carries the
games it rests on.

WALK-FORWARD, NO LEAKAGE (college re-sim). For a game on date D: team ratings from corpus box rows dated < D, player
priors from player box rows dated < D, and the college PRIOR CALIBRATION (`college_basketball/prior_calibration.fit`,
production's daily fit since 2026-11-03) refit on the games dated D-21 .. D-1 against the ESPN BET close. Today's
live path then market-anchors the live margin (`anchor_result`); `resim_anchored` replays that against the same close.

COST. One 100-sim re-sim of an NCAAB game costs ~2.5-10 s at nice 19 on the shared host (tip ~10 s), so the re-sim
runs at the four checkpoints (+ the tip for the anchor) unless `--resim-every` asks for more; the arithmetic
projectors run at every 30 s step. 100 sims is production NBA's count (`SYNDICATE_NBA_LIVE_RESIM_SIMS=100` on the
fleet) and both re-sims' floor (`MIN_SIMS`).

    nice -n 19 python scripts/backtest_basketball_intervals.py --league ncaab --season 2026 \
        --data-root /home/amyn/syndicate-prod/data --projectors naive_pace,interval_projection,league_rate,pregame_rate,pooled_rate,pooled_pace,pooled_efficiency,resim \
        --sample 300 --workers 3 --out ~/bball_iv/ncaab_resim
Run at Idle / `nice -n 19`: the fleet shares this machine.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import importlib.util
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.shared import basketball_interval_backtest as bib  # noqa: E402
from syndicate.features.shared import basketball_pbp as pbp  # noqa: E402

TOURNAMENT_PHASES = ("conf_tournament", "ncaa_tournament", "other_postseason")
EVENT_FIELDS = {f.name for f in dc_fields(pbp.PbpEvent)}
TUPLE_FIELDS = {"players", "sub_in", "sub_out"}
MIN_LEAGUE_RATE_GAMES = 30


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ------------------------------------------------------------------------------------------------ substrate

def processed_dir(data_root: Path, league: str) -> Path:
    return Path(data_root) / f"{league}_source" / "data" / "processed"


def read_games_tables(data_root: Path, league: str, season: int) -> list[dict[str, Any]]:
    """Every row of `rotation_stints/games_<date>.csv` for one ESPN season (the year the season ends)."""
    out: list[dict[str, Any]] = []
    for path in sorted((processed_dir(data_root, league) / "rotation_stints").glob("games_*.csv")):
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if str(row.get("season")) == str(season):
                    out.append(row)
    return out


_BOX_CACHE: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = {}


def read_box(data_root: Path, league: str, date: str) -> dict[str, list[dict[str, Any]]]:
    key = (str(data_root), league, date)
    if key not in _BOX_CACHE:
        _BOX_CACHE[key] = _read_box(data_root, league, date)
    return _BOX_CACHE[key]


def _read_box(data_root: Path, league: str, date: str) -> dict[str, list[dict[str, Any]]]:
    path = processed_dir(data_root, league) / "rotation_stints" / f"player_checks_{date}.csv"
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                out[str(row["event_id"])].append(row)
    return out


def events_path(data_root: Path, league: str, season: Any, event_id: str) -> Path:
    return processed_dir(data_root, league) / "pbp_events" / str(season) / f"{event_id}.jsonl.gz"


def read_events(path: Path) -> tuple[pbp.PbpEvent, ...]:
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            raw = json.loads(line)
            kw = {k: (tuple(v or ()) if k in TUPLE_FIELDS else v) for k, v in raw.items() if k in EVENT_FIELDS}
            out.append(pbp.PbpEvent(**kw))
    out.sort(key=lambda e: e.seq)
    return tuple(out)


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_meta(league: str, row: Mapping[str, Any], box_rows: Iterable[Mapping[str, Any]],
               team_ids: Optional[Mapping[str, str]] = None) -> pbp.GameMeta:
    team_ids = team_ids or {}
    meta = pbp.GameMeta(
        league=league, event_id=str(row["event_id"]), date=str(row["date"]), season=_int_or_none(row.get("season")),
        season_type=str(row.get("season_type") or ""), status_state="post", completed=True,
        home=pbp.TeamInfo("home", str(team_ids.get("home") or ""), str(row["home"]), _int_or_none(row.get("official_home"))),
        away=pbp.TeamInfo("away", str(team_ids.get("away") or ""), str(row["away"]), _int_or_none(row.get("official_away"))),
    )
    for b in box_rows:
        side = "home" if str(b.get("team")) == str(row["home"]) else ("away" if str(b.get("team")) == str(row["away"]) else "")
        if not side or not b.get("player_id"):
            continue
        meta.box[str(b["player_id"])] = pbp.BoxPlayer(
            player_id=str(b["player_id"]), name=str(b.get("player_name") or ""), side=side,
            starter=str(b.get("starter")) in ("1", "True", "true"), did_not_play=False,
            minutes=float(b["box_minutes"]) if str(b.get("box_minutes") or "").strip() else None,
            pf=_int_or_none(b.get("box_pf")), pts=None)
    return meta


def build_game(task: Mapping[str, Any]) -> bib.ReplayGame:
    meta = build_meta(task["league"], task["game_row"], task["box_rows"], task.get("team_ids"))
    events = read_events(Path(task["events_path"]))
    pre = task.get("pregame") or {}
    return bib.ReplayGame(league=task["league"], game_id=str(task["game_id"]), date=str(task["date"]), phase=str(task["phase"]),
                          meta=meta, events=events, pregame_total=pre.get("total"), pregame_home_margin=pre.get("home_margin"),
                          pregame_source=str(pre.get("source") or ""), extra=dict(task.get("extra") or {}))


def coverage_report(families: Mapping[str, Iterable[str]]) -> dict[str, Any]:
    """Per-family date coverage and the intersection (`CLAUDE.md`: a join collapses to the narrowest family)."""
    sets = {k: set(v) for k, v in families.items()}
    out: dict[str, Any] = {}
    for name, dates in sets.items():
        s = sorted(dates)
        out[name] = {"dates": len(s), "first": s[0] if s else None, "last": s[-1] if s else None}
    inter = set.intersection(*sets.values()) if sets else set()
    out["INTERSECTION"] = {"dates": len(inter), "first": min(inter) if inter else None, "last": max(inter) if inter else None}
    return out


def _league_rates(totals_by_date: Mapping[str, list[float]], reg_seconds: int) -> dict[str, Optional[float]]:
    """Walk-forward league scoring rate per date: regulation points per regulation second over every game dated
    before it (>= MIN_LEAGUE_RATE_GAMES games, else None -> `league_rate` refuses by name)."""
    out: dict[str, Optional[float]] = {}
    seen: list[float] = []
    for day in sorted(totals_by_date):
        out[day] = (statistics.fmean(seen) / reg_seconds) if len(seen) >= MIN_LEAGUE_RATE_GAMES else None
        seen.extend(totals_by_date[day])
    return out


# ------------------------------------------------------------------------------------------------ ncaab

def _calibrated(prior: Any, cal: Any) -> Any:
    """`ncaab/live_team_model._calibrated`'s apply step, on a walk-forward fit (the production function reads its fit
    from a dated file; `tests/test_basketball_interval_backtest.py` pins this against it)."""
    from dataclasses import replace

    if cal is None or not cal.calibrated:
        return replace(prior, raw_home_margin=prior.home_margin, raw_total=prior.total,
                       calibration={"calibrated": False, "reason": getattr(cal, "reason", "no walk-forward fit")})
    margin = cal.margin(prior.home_margin, home_site=not prior.neutral)
    total = cal.total(prior.total)
    hp, ap = (total + margin) / 2.0, (total - margin) / 2.0
    return replace(prior, home_points=hp, away_points=ap, total=total, home_margin=margin,
                   home_ppp=hp / prior.possessions, away_ppp=ap / prior.possessions,
                   raw_home_margin=prior.home_margin, raw_total=prior.total, calibration=cal.stamp())


def _close(record: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    lines = record.get("lines") or {}
    total, spread = lines.get("total_close"), lines.get("spread_home_close")
    return (float(total) if total is not None else None, (-float(spread)) if spread is not None else None)


def ncaab_tasks(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from syndicate.features.college_basketball import prior_calibration as pc
    from syndicate.features.ncaab import live_team_model as tm

    os.environ["SYNDICATE_DATA_ROOT"] = str(args.data_root)  # the corpus helpers resolve paths from it (read-only)
    corpus = _load_script("build_ncaab_pbp_corpus")
    players_mod = _load_script("build_ncaab_player_priors")
    baseline = _load_script("ncaab_corpus_baseline")
    ratings = corpus.ratings
    lite: list[dict[str, Any]] = []
    for r in corpus.read_records(corpus.corpus_path(args.season)):
        if r.get("v") != corpus.RECORD_VERSION:
            continue
        lite.append({k: r.get(k) for k in ("game_id", "date", "season", "phase", "neutral", "home", "away", "lines", "box_rows", "check")})
    lite.sort(key=lambda r: (r["date"], r["game_id"]))
    by_id = {r["game_id"]: r for r in lite}
    games = {str(g["event_id"]): g for g in read_games_tables(args.data_root, "ncaab", args.season)}
    ev_ok = {gid for gid, g in games.items() if events_path(args.data_root, "ncaab", args.season, gid).is_file()}
    box_dates = json.loads(players_mod.box_dates_path(args.season).read_text(encoding="utf-8")) if players_mod.box_dates_path(args.season).is_file() else {}
    box_date_set = set(box_dates.get("dates", box_dates) if isinstance(box_dates, dict) else box_dates)
    cov = coverage_report({
        "pbp_corpus (ids, close, box rows)": {r["date"] for r in lite},
        "rotation_stints games_<date>.csv": {g["date"] for g in games.values()},
        "pbp_events logs": {games[g]["date"] for g in ev_ok},
        "player_game_box dates": box_date_set or {r["date"] for r in lite},
    })
    # Walk-forward raw priors for EVERY game (the calibration window needs them), then a daily fit -- production's.
    raw_priors = baseline.walk_forward_priors(lite)
    fit_rows: dict[str, list[Any]] = defaultdict(list)
    for r in lite:
        p = raw_priors.get(r["game_id"])
        if not isinstance(p, tm.NcaabGamePrior):
            continue
        ct, cm = _close(r)
        fs = (r["home"].get("score"), r["away"].get("score"))
        fit_rows[r["date"]].append(pc.FitRow(date=r["date"], event_id=r["game_id"], home_site=not r["neutral"],
                                             prior_margin=p.home_margin, prior_total=p.total, close_margin=cm, close_total=ct,
                                             final_margin=(fs[0] - fs[1]) if None not in fs else None,
                                             final_total=(fs[0] + fs[1]) if None not in fs else None))
    cal_by_date: dict[str, Any] = {}
    reg_totals: dict[str, list[float]] = defaultdict(list)
    for r in lite:
        ls_h, ls_a = (r["home"].get("linescores") or [])[:2], (r["away"].get("linescores") or [])[:2]
        if len(ls_h) == 2 and len(ls_a) == 2 and None not in ls_h + ls_a:
            reg_totals[r["date"]].append(float(sum(ls_h) + sum(ls_a)))
    rates = _league_rates(reg_totals, int(pbp.rules_for("ncaab").regulation_seconds()))

    eligible = [r for r in lite if r["game_id"] in ev_ok and r["game_id"] in games
                and (r.get("check") or {}).get("pbp_final_matches") and (args.phases is None or r["phase"] in args.phases)]
    rng = random.Random(args.seed)
    chosen = eligible if not args.sample or args.sample >= len(eligible) else rng.sample(eligible, args.sample)
    chosen_ids = {r["game_id"] for r in chosen}
    need_resim = any(p.startswith("resim") for p in args.projector_names)
    box = players_mod.read_csv(players_mod.box_path(args.season)) if need_resim else []
    d1 = ratings.load_registry() if need_resim else {}
    box_by_date: dict[str, list] = defaultdict(list)
    for row in box:
        box_by_date[row["date"]].append(row)
    seen_box: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)
    tasks: list[dict[str, Any]] = []
    by_date: dict[str, list] = defaultdict(list)
    for r in lite:
        by_date[r["date"]].append(r)
    for day in sorted(by_date):
        todays = [r for r in by_date[day] if r["game_id"] in chosen_ids]
        if todays:
            d = dt.date.fromisoformat(day)
            window = [fr for k, rows in fit_rows.items() if (d - dt.timedelta(days=pc.WINDOW_DAYS)).isoformat() <= k < day for fr in rows]
            cal = pc.fit(window, league="ncaab", season=args.season, as_of=d) if window else None
            cal_by_date[day] = cal.stamp() if cal is not None else None
            by_team: dict[str, list] = defaultdict(list)
            if need_resim:
                for p in players_mod.compute_priors(seen_box, as_of=d, d1=d1).values():
                    by_team[p["team_id"]].append(p)
            for r in todays:
                g = games[r["game_id"]]
                total, margin = _close(r)
                extra: dict[str, Any] = {"league_points_per_second": rates.get(day)}
                prior = raw_priors.get(r["game_id"])
                if isinstance(prior, tm.NcaabGamePrior):
                    extra["prior_possessions"] = 2.0 * float(prior.possessions)
                    if need_resim and prior.home_games >= args.min_games and prior.away_games >= args.min_games:
                        cp = _calibrated(prior, cal)
                        pd_ = {k: getattr(cp, k) for k in cp.__dataclass_fields__}
                        pd_["ratings_as_of"] = cp.ratings_as_of.isoformat()
                        extra["college_resim"] = {"prior": pd_, "season": args.season, "neutral": bool(r["neutral"]),
                                                  "player_priors": {t: by_team.get(t, []) for t in (r["home"]["id"], r["away"]["id"])}}
                    elif need_resim:
                        skipped["fewer_than_min_games"] += 1
                else:
                    skipped["no_team_prior"] += 1
                tasks.append({
                    "league": "ncaab", "game_id": r["game_id"], "date": day, "phase": r["phase"], "season": args.season,
                    "events_path": str(events_path(args.data_root, "ncaab", args.season, r["game_id"])), "game_row": g,
                    "box_rows": read_box(args.data_root, "ncaab", g["date"]).get(r["game_id"], []),
                    "team_ids": {"home": r["home"]["id"], "away": r["away"]["id"]},
                    "pregame": {"total": total, "home_margin": margin, "source": "espn_bet_close"} if total is not None and margin is not None else {},
                    "extra": extra,
                })
        seen_box.extend(box_by_date.get(day, []))
    meta = {"coverage": cov, "eligible_games": len(eligible), "chosen_games": len(chosen), "skipped_before_replay": dict(skipped),
            "calibration_by_date": cal_by_date, "substrate": f"{args.data_root} (read-only)"}
    return tasks, meta


# ------------------------------------------------------------------------------------------------ nba / wnba

def _sim_file(data_root: Path, league: str, date: str, home: str, away: str, kind: str) -> Optional[Path]:
    base = processed_dir(data_root, league)
    path = (base / "engine_inputs" / date / f"{home.upper()}_{away.upper()}.pkl") if kind == "inputs" else (base / f"smart_sim_{date}_{home.upper()}_{away.upper()}.json")
    return path if path.is_file() else None


def pro_tasks(args: argparse.Namespace, league: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    games = [g for g in read_games_tables(args.data_root, league, args.season)
             if str(g.get("score_match")) == "1" and (args.phases is None or g.get("season_type") in args.phases)]
    base = processed_dir(args.data_root, league)
    ev_ok = [g for g in games if events_path(args.data_root, league, args.season, g["event_id"]).is_file()]
    ei_dates = {p.name for p in (base / "engine_inputs").glob("*") if p.is_dir()}
    ss_dates = {p.name[len("smart_sim_"):len("smart_sim_") + 10] for p in base.glob("smart_sim_*.json")}
    cov = coverage_report({
        "rotation_stints games_<date>.csv (score_match)": {g["date"] for g in games},
        "pbp_events logs": {g["date"] for g in ev_ok},
        **({"engine_inputs (pregame, persisted)": ei_dates, "smart_sim (line + ladder)": ss_dates} if args.require_sim_inputs else {}),
    })
    # Regulation totals for the walk-forward league rate: one pass over the logs, nothing kept.
    reg_totals: dict[str, list[float]] = defaultdict(list)
    reg = int(pbp.rules_for(league).regulation_periods)
    for g in ev_ok:
        evs = read_events(events_path(args.data_root, league, args.season, g["event_id"]))
        reg_totals[g["date"]].append(float(sum(e.points for e in evs if e.points and e.side in ("home", "away") and e.period <= reg)))
    rates = _league_rates(reg_totals, int(pbp.rules_for(league).regulation_seconds()))
    tasks: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    for g in ev_ok:
        extra: dict[str, Any] = {"league_points_per_second": rates.get(g["date"])}
        pre: dict[str, Any] = {}
        ss = _sim_file(args.data_root, league, g["date"], g["home"], g["away"], "smart_sim")
        if ss is not None:
            doc = json.loads(ss.read_text(encoding="utf-8"))
            mk = doc.get("market") or {}
            if mk.get("market_total") is not None and mk.get("market_home_spread") is not None:
                pre = {"total": float(mk["market_total"]), "home_margin": -float(mk["market_home_spread"]), "source": "smart_sim_market_at_sim_time"}
            if doc.get("intervals"):
                extra["tick_intervals"] = doc["intervals"]
        ei = _sim_file(args.data_root, league, g["date"], g["home"], g["away"], "inputs")
        if ei is not None:
            extra["engine_inputs_root"] = str(Path(args.data_root) / f"{league}_source")
            try:
                import pickle

                with ei.open("rb") as fh:
                    cfg = (pickle.load(fh).get("kwargs") or {}).get("cfg")
                poss = cfg.get("possessions_per_game") if isinstance(cfg, Mapping) else getattr(cfg, "possessions_per_game", None)
                if poss:
                    extra["prior_possessions"] = 2.0 * float(poss)
            except Exception as exc:  # noqa: BLE001 -- recorded; the re-sim then refuses on its own read
                skipped[f"engine_inputs_unreadable:{type(exc).__name__}"] += 1
        if args.require_sim_inputs and (ei is None or ss is None):
            skipped["no_pregame_sim_inputs"] += 1
            continue
        tasks.append({"league": league, "game_id": str(g["event_id"]), "date": g["date"], "phase": g.get("season_type") or "",
                      "season": args.season, "events_path": str(events_path(args.data_root, league, args.season, g["event_id"])),
                      "game_row": g, "box_rows": read_box(args.data_root, league, g["date"]).get(str(g["event_id"]), []),
                      "pregame": pre, "extra": extra})
    rng = random.Random(args.seed)
    if args.sample and args.sample < len(tasks):
        tasks = rng.sample(tasks, args.sample)
    meta = {"coverage": cov, "eligible_games": len(ev_ok), "chosen_games": len(tasks), "skipped_before_replay": dict(skipped),
            "substrate": f"{args.data_root} (read-only)"}
    return tasks, meta


# ------------------------------------------------------------------------------------------------ worker

_PROJECTORS: list[bib.Projector] = []
_SIM_TIMES: Optional[list[float]] = None


def make_projectors(names: Iterable[str], *, sims: int, mechanisms: Mapping[str, Any]) -> list[bib.Projector]:
    """`name[:k=<v>]` -> projector. `resim_mech` is the re-sim with `--mechanisms` set on its cfg."""
    out: list[bib.Projector] = []
    for token in names:
        name, _, arg = token.partition(":")
        kv = dict(p.split("=", 1) for p in arg.split(",") if "=" in p)
        if name == "naive_pace":
            out.append(bib.NaivePace())
        elif name == "interval_projection":
            out.append(bib.IntervalModule())
        elif name == "league_rate":
            out.append(bib.LeagueRate())
        elif name == "pregame_rate":
            out.append(bib.PregameRate())
        elif name == "pooled_rate":
            out.append(bib.PooledRate(float(kv.get("k", 1200))))
        elif name == "pooled_pace":
            out.append(bib.PooledPace(float(kv.get("k", 60))))
        elif name == "pooled_efficiency":
            out.append(bib.PooledEfficiency(float(kv.get("k", 60))))
        elif name == "resim":
            out.append(bib.Resim(sims=sims))
        elif name == "resim_mech":
            if not mechanisms:
                raise SystemExit("resim_mech needs --mechanisms")
            out.append(bib.Resim(sims=sims, mechanisms=mechanisms))
        elif name == "nba_tick":
            out.append(bib.NbaTick())
        else:
            raise SystemExit(f"unknown projector {token!r}")
    return out


def _init_worker(names: list[str], sims: int, mechanisms: Mapping[str, Any], sim_times: Optional[list[float]]) -> None:
    global _PROJECTORS, _SIM_TIMES
    _PROJECTORS = make_projectors(names, sims=sims, mechanisms=mechanisms)
    _SIM_TIMES = sim_times


def run_task(task: Mapping[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    try:
        game = build_game(task)
        res = bib.replay_game(game, _PROJECTORS, sim_times=_SIM_TIMES)
    except Exception as exc:  # noqa: BLE001 -- one bad game is a named row, never a dead run
        return {"league": task["league"], "game_id": task["game_id"], "date": task["date"], "phase": task["phase"],
                "game_refusal": f"replay_error:{type(exc).__name__}", "detail": str(exc)[:300], "rows": []}
    out = bib.compact(res)
    out["sec"] = round(time.time() - t0, 2)
    return out


# ------------------------------------------------------------------------------------------------ report

def _fmt(stat: Mapping[str, Any]) -> str:
    if not stat or not stat.get("n"):
        return "--"
    return f"{stat['mae']:.2f} ({stat['bias']:+.2f})"


def markdown(report: Mapping[str, Any], *, segments: Optional[Iterable[str]] = None) -> str:
    """The report as tables: coverage, the checkpoint MAE (bias) per projector x segment, the 5%-bucket curve at the
    old NCAAB app's bins (minute 10/20/30/38 of 40, i.e. 2-minute bins over every 30 s snapshot), and the paired
    gates against the baseline. Every cell carries the games it rests on."""
    want = set(segments) if segments else None
    lines: list[str] = []
    cfg = report.get("config") or {}
    lines.append(f"**{cfg.get('league')} season {cfg.get('season')}** -- code `{cfg.get('code')}`, sims {cfg.get('sims')}, "
                 f"re-sim at {cfg.get('sim_times')}; games scored {report.get('games_scored')} of {report.get('games_replayed')} "
                 f"replayed (eligible {report.get('eligible_games')}); refused before replay {report.get('skipped_before_replay')}; "
                 f"game refusals {report.get('game_refusals')}; {report.get('sec_per_game')} s/game\n")
    lines.append("| family | dates | first | last |\n|---|---|---|---|")
    for name, c in (report.get("coverage") or {}).items():
        lines.append(f"| {name} | {c['dates']} | {c['first']} | {c['last']} |")
    if report.get("prepare_refusals"):
        lines.append(f"\nPer-game projector refusals (named): `{json.dumps(report['prepare_refusals'], sort_keys=True)}`")
    for lg, phases in (report.get("checkpoint") or {}).items():
        labels = list(bib.checkpoint_times(lg))
        for ph, projs in phases.items():
            for qty in ("total", "margin"):
                lines.append(f"\n#### {lg} / {ph} -- {qty}: MAE (bias) at {', '.join(labels)} elapsed; [games]\n")
                lines.append("| projector | segment | " + " | ".join(labels) + " |")
                lines.append("|---|---|" + "---|" * len(labels))
                for pj, segs in projs.items():
                    for seg, cells in segs.items():
                        if want and seg not in want:
                            continue
                        row = [f"{_fmt(cells.get(lb, {}).get(qty, {}))} [{cells.get(lb, {}).get('games', 0)}]" for lb in labels]
                        if all(r.startswith("--") for r in row):
                            continue
                        lines.append(f"| {pj} | {seg} | " + " | ".join(row) + " |")
    bars = [str(f) for f in bib.CHECKPOINT_FRACTIONS]
    for lg, phases in (report.get("bucket") or {}).items():
        reg_min = float(pbp.rules_for(lg).regulation_seconds()) / 60.0
        heads = [f"{float(b) * reg_min:g}-{(float(b) + bib.BUCKET_FRACTION) * reg_min:g}m" for b in bars]
        for ph, projs in phases.items():
            lines.append(f"\n#### {lg} / {ph} -- FULL-GAME TOTAL over every 30 s snapshot in the bin: MAE (bias) [games]\n")
            lines.append("| projector | " + " | ".join(heads) + " |")
            lines.append("|---|" + "---|" * len(heads))
            for pj, segs in projs.items():
                cells = segs.get("full") or {}
                row = [f"{_fmt(cells.get(b, {}).get('total', {}))} [{cells.get(b, {}).get('games', 0)}]" for b in bars]
                if not all(r.startswith("--") for r in row):
                    lines.append(f"| {pj} | " + " | ".join(row) + " |")
    base = report.get("gate_baseline")
    for gate, by_qty in (report.get("gates") or {}).items():
        for qty, tree in by_qty.items():
            for lg, phases in tree.items():
                labels = list(bib.checkpoint_times(lg))
                for ph, segs in phases.items():
                    rows = []
                    for seg, cells in segs.items():
                        if want and seg not in want:
                            continue
                        vals = []
                        for lb in labels:
                            c = cells.get(lb)
                            vals.append("--" if not c else f"{c['delta']:+.2f} +-{(c['se'] or 0) * 1.96:.2f} {c['verdict']} [{c['games']}]")
                        if not all(v == "--" for v in vals):
                            rows.append(f"| {seg} | " + " | ".join(vals) + " |")
                    if rows:
                        lines.append(f"\n#### GATE {gate} -- {lg} / {ph} -- {qty}: mean |err| difference vs {base} "
                                     f"(negative = better), +-1.96 game-clustered SE [games]\n")
                        lines.append("| segment | " + " | ".join(labels) + " |")
                        lines.append("|---|" + "---|" * len(labels))
                        lines.extend(rows)
    return "\n".join(lines) + "\n"


def build_report(results: list[dict[str, Any]], meta: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    refusals: dict[str, int] = defaultdict(int)
    prep: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    step: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        if r.get("game_refusal"):
            refusals[r["game_refusal"]] += 1
        for k, v in (r.get("prepare_refusals") or {}).items():
            prep[k][v] += 1
        for k, d in (r.get("refusals") or {}).items():
            for reason, n in d.items():
                step[k][reason] += n
    scored = [r for r in results if not r.get("game_refusal")]
    names = sorted({row["projector"] for r in scored for row in r.get("cp_rows") or ()})
    base = args.baseline if args.baseline in names else ("pregame_rate" if "pregame_rate" in names else "naive_pace")
    gates = {f"{c}_vs_{base}": {q: bib.paired_delta(scored, c, base, quantity=q) for q in ("total", "margin")}
             for c in names if c != base}
    return {
        "config": {"league": args.league, "season": args.season, "phases": args.phases, "projectors": args.projector_names,
                   "sims": args.sims, "mechanisms": args.mechanisms_obj, "step_seconds": bib.STEP_SECONDS,
                   "checkpoints": bib.checkpoint_times(args.league), "sim_times": args.sim_times or "checkpoints",
                   "seed": args.seed, "sample": args.sample, "code": args.code_sha},
        **meta,
        "games_replayed": len(results), "games_scored": len(scored), "game_refusals": dict(refusals),
        "prepare_refusals": {k: dict(v) for k, v in prep.items()}, "step_refusals": {k: dict(v) for k, v in step.items()},
        "sec_per_game": round(statistics.fmean(r.get("sec", 0.0) for r in results), 2) if results else None,
        "checkpoint": bib.summarize(scored, by="checkpoint"),
        "bucket": bib.summarize(scored, by="bucket"),
        "gate_baseline": base,
        "gates": gates,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--league", choices=("ncaab", "nba", "wnba"))
    ap.add_argument("--season", type=int, help="ESPN season = the year the season ENDS (NBA 2027 = 2026-27)")
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("SYNDICATE_DATA_ROOT") or (REPO / "data")))
    ap.add_argument("--phases", default="", help="comma list (ncaab: regular,conf_tournament,...; nba/wnba: regular,playoffs,...); empty = all")
    ap.add_argument("--projectors", default="naive_pace,interval_projection,league_rate,pregame_rate,pooled_rate,pooled_pace,pooled_efficiency")
    ap.add_argument("--mechanisms", default="", help="JSON EventSimConfig fields for resim_mech")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--resim-every", type=int, default=0, help="re-sim every N regulation seconds instead of the four checkpoints")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20261107)
    ap.add_argument("--min-games", type=int, default=5, help="college re-sim: both teams need this many prior games")
    ap.add_argument("--require-sim-inputs", action="store_true", help="nba/wnba: only games with persisted engine inputs + smart sim")
    ap.add_argument("--baseline", default="pregame_rate")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--code-sha", default="", help="the commit the run's code is at (recorded in the report)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--render", default="", help="re-render report.md from an existing report.json (no replay)")
    ap.add_argument("--render-segments", default="", help="with --render: only these segments in the tables")
    ap.add_argument("--max-games", type=int, default=None, help="smoke runs: only the first N tasks")
    args = ap.parse_args(argv)
    if args.render:
        report = json.loads(Path(args.render).read_text(encoding="utf-8"))
        text = markdown(report, segments=[x for x in args.render_segments.split(",") if x] or None)
        (args.out / "report.md").write_text(text, encoding="utf-8") if args.out.is_dir() else print(text)
        return 0
    if not args.league or not args.season:
        ap.error("--league and --season are required (except with --render)")
    args.phases = [p for p in args.phases.split(",") if p] or None
    args.projector_names = [p for p in args.projectors.split(",") if p]
    args.mechanisms_obj = json.loads(args.mechanisms) if args.mechanisms else {}
    reg = int(pbp.rules_for(args.league).regulation_seconds())
    args.sim_times = [float(t) for t in range(args.resim_every, reg, args.resim_every)] if args.resim_every else None
    make_projectors(args.projector_names, sims=args.sims, mechanisms=args.mechanisms_obj)  # fail fast on a bad name
    args.out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    tasks, meta = ncaab_tasks(args) if args.league == "ncaab" else pro_tasks(args, args.league)
    print("[interval_backtest] COVERAGE (dates per family; the join rests on the intersection)", flush=True)
    for name, c in meta["coverage"].items():
        print(f"  {name:55s} {c['dates']:4d} dates  {c['first']} .. {c['last']}", flush=True)
    print(f"[interval_backtest] eligible={meta['eligible_games']} chosen={len(tasks)} skipped={meta['skipped_before_replay']} "
          f"load_s={round(time.time() - started)}", flush=True)
    # Interleave by phase (seeded) so a partial run is a balanced read of every phase.
    by_phase: dict[str, list] = defaultdict(list)
    for t in tasks:
        by_phase[t["phase"]].append(t)
    shuffler = random.Random(args.seed)
    for lst in by_phase.values():
        shuffler.shuffle(lst)
    queues = sorted(by_phase.values(), key=len)
    tasks = [q[i] for i in range(max((len(q) for q in queues), default=0)) for q in queues if i < len(q)]
    if args.max_games is not None:
        tasks = tasks[: args.max_games]
    results_path = args.out / "results.jsonl"
    done: dict[str, dict[str, Any]] = {}
    if results_path.is_file():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["game_id"]] = r
    todo = [t for t in tasks if t["game_id"] not in done]
    print(f"[interval_backtest] tasks={len(tasks)} done={len(done)} todo={len(todo)} projectors={args.projector_names} sims={args.sims}", flush=True)
    if todo:
        initargs = (args.projector_names, args.sims, args.mechanisms_obj, args.sim_times)
        with results_path.open("a", encoding="utf-8") as fh:
            if args.workers <= 1:
                # In-process: no pool (a spawned worker cannot re-import a script loaded by path, e.g. under pytest).
                _init_worker(*initargs)
                stream = map(run_task, todo)
                pool = None
            else:
                from multiprocessing import get_context

                ctx = get_context("fork") if sys.platform != "win32" else get_context("spawn")
                pool = ctx.Pool(processes=args.workers, initializer=_init_worker, initargs=initargs)
                stream = pool.imap_unordered(run_task, todo, chunksize=1)
            try:
                for i, res in enumerate(stream, 1):
                    fh.write(json.dumps(res, separators=(",", ":")) + "\n")
                    fh.flush()
                    done[res["game_id"]] = res
                    if i % 25 == 0 or i == len(todo):
                        print(f"[interval_backtest] PROGRESS {i}/{len(todo)} elapsed_s={round(time.time() - started)}", flush=True)
            finally:
                if pool is not None:
                    pool.close()
                    pool.join()
    results = [done[t["game_id"]] for t in tasks if t["game_id"] in done]
    report = build_report(results, meta, args)
    (args.out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (args.out / "report.md").write_text(markdown(report), encoding="utf-8")
    print(f"[interval_backtest] DONE games_scored={report['games_scored']} refusals={report['game_refusals']} "
          f"report={args.out / 'report.json'} elapsed_s={round(time.time() - started)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
