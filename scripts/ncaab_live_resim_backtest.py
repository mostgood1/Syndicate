"""NCAAB live re-sim backtest: P1's engine resumed at in-game checkpoints over the 2025-26 corpus.

Lane `ncaab-native-live-tier` (P4 of `docs/ai_context/basketball_live_native_plan.md`). The
verification the lane owes BEFORE the board may price NCAAB live lines: per checkpoint and per
season phase (regular season NEVER pooled with tournaments), the resumed engine against

  * the FINAL (total / margin bias + MAE, ML Brier),
  * the naive "resume at the prior's rate" baseline (`ncaab_corpus_baseline.py`) on the SAME games,
  * ESPN's own win probability at the same play (an outside model, not a market).

The LIVE CLOSE is not graded: ESPN keeps no in-play line history (probed 2026-10-09); that needs
OddsAPI historical in-play snapshots, a user decision.

WALK-FORWARD, NO LEAKAGE. For a game on date D: team ratings from `compute_ratings` over corpus box
rows dated < D; player priors from `compute_priors` over player box rows dated < D (exactly the
function the producer runs). The resume state at a checkpoint is rebuilt from the corpus's own plays
(score split by half, on-floor five from directed substitutions, player and team fouls by half).
A five that does not map to exactly 5 frame players is left empty and the engine samples the
lineup -- the live path's rule (`nba/live_resim.map_state_names`) -- and the share is reported.

Inputs (all local, named in the report):
  <ncaab root>/data/pbp_corpus/pbp_corpus_<season>.jsonl.gz      (build_ncaab_pbp_corpus.py)
  <ncaab root>/data/processed/player_game_box_<season>.csv       (build_ncaab_player_priors.py)

    py -3 scripts/ncaab_live_resim_backtest.py --season 2026 --regular-sample 300 --sims 100 --workers 3
Run at Idle priority: the fleet shares the host.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


corpus = _load("build_ncaab_pbp_corpus")
players_mod = _load("build_ncaab_player_priors")
baseline = _load("ncaab_corpus_baseline")
ratings = corpus.ratings

CHECKPOINTS = {"tip": 0, "half": 1200, "H2_10:00": 1800, "H2_5:00": 2100, "H2_2:00": 2280}
FOUL_TYPE = 519
TOURNAMENT_PHASES = ("conf_tournament", "ncaa_tournament", "other_postseason")


# ------------------------------------------------------------------ state

def on_floor_at(record: Mapping[str, Any], plays: list[dict[str, Any]], elapsed: float) -> dict[str, list[str]]:
    """Athlete ids on the floor per side at `elapsed`, from the box starters and directed subs.

    Each half: a player whose first sub event in the half is OUT was on at its start, IN was not,
    none carries the previous state. Returns {} for a side whose count is not 5.
    """
    players = {(side, pid) for side, pid, *_ in record.get("players") or [] if pid}
    starters = {(side, pid) for side, pid, starter, *_ in record.get("players") or [] if starter and pid}
    on = {p: p in starters for p in players}
    period_now = 1 if elapsed < 1200 else 2
    for period in (1, 2):
        half = [p for p in plays if p["period"] == period and p.get("sub") in (1, -1) and p["athlete"] and p["team"]]
        if period == 2:
            for key in players:
                first = next((p["sub"] for p in half if (p["team"], p["athlete"]) == key), None)
                if first is not None:
                    on[key] = first == -1
        for p in half:
            if p["elapsed"] > elapsed:
                break
            key = (p["team"], p["athlete"])
            on[key] = p["sub"] == 1
        if period == period_now:
            break
    out: dict[str, list[str]] = {}
    for side in ("h", "a"):
        ids = [pid for (s, pid), v in on.items() if v and s == side]
        if len(ids) == 5:
            out[side] = ids
    return out


def resume_state(record: Mapping[str, Any], cp: float, names: Mapping[str, str]):
    """A P1 `GameState` at regulation-elapsed `cp`, or None for the tip (a pregame run)."""
    from syndicate.features.basketball_engine.resume import GameState

    if cp <= 0:
        return None, {}
    plays = baseline.plays_of(record)
    st = baseline.state_at(plays, cp)
    if st is None:
        return None, {"skip": "no_state"}
    h1 = baseline.state_at(plays, 1200) if cp >= 1200 else None
    report: dict[str, Any] = {}
    if cp >= 1200 and h1 is not None:
        hp = (h1["home"], st["home"] - h1["home"])
        ap = (h1["away"], st["away"] - h1["away"])
    else:
        hp, ap = (st["home"],), (st["away"],)
    if cp == 1200:
        # A period just ended: resume from the second half's tip (the live path's rule).
        return GameState(period=2, seconds_remaining=None, home_period_pts=(hp[0], 0), away_period_pts=(ap[0], 0)), report
    period = 1 if cp < 1200 else 2
    secs = int(round(period * 1200 - cp))
    half_start = (period - 1) * 1200
    fouls_p: dict[str, int] = defaultdict(int)
    team_fouls = {"h": 0, "a": 0}
    for p in plays:
        if p["elapsed"] > cp:
            break
        if p["type"] == FOUL_TYPE and p["team"] in ("h", "a"):
            if p["athlete"]:
                fouls_p[f"{p['team']}|{p['athlete']}"] += 1
            if p["elapsed"] > half_start:
                team_fouls[p["team"]] += 1
    floor = on_floor_at(record, plays, cp)
    five = {}
    for side in ("h", "a"):
        mapped = [names.get(pid) for pid in floor.get(side, [])]
        five[side] = tuple(mapped) if len(mapped) == 5 and all(mapped) else ()
        report[f"{side}_on_floor_mapped"] = len(five[side]) == 5
    gs = GameState(
        period=period, seconds_remaining=secs, home_period_pts=hp, away_period_pts=ap, possession=None,
        home_on_floor=five["h"], away_on_floor=five["a"],
        home_player_fouls={names[k.split("|")[1]]: v for k, v in fouls_p.items() if k.startswith("h|") and k.split("|")[1] in names},
        away_player_fouls={names[k.split("|")[1]]: v for k, v in fouls_p.items() if k.startswith("a|") and k.split("|")[1] in names},
        home_team_fouls=team_fouls["h"], away_team_fouls=team_fouls["a"],
    )
    return gs, report


# ------------------------------------------------------------------ per game

def run_game(task: Mapping[str, Any]) -> dict[str, Any]:
    """One game, every checkpoint. Runs in a worker process."""
    import numpy as np  # noqa: F401 -- worker import

    from syndicate.features.ncaab import live_resim as lr
    from syndicate.features.ncaab import live_team_model as tm

    rec = task["record"]
    prior = tm.NcaabGamePrior(**{**task["prior"], "ratings_as_of": dt.date.fromisoformat(task["prior"]["ratings_as_of"])})
    priors = lr.PlayerPriors(season=rec["season"], as_of=dt.date.fromisoformat(rec["date"]), source="walk_forward",
                             by_team=task["player_priors"])
    inputs = lr.build_engine_inputs(rec["date"], rec["home"]["id"], rec["away"]["id"], neutral=rec["neutral"],
                                    priors=priors, team_prior=prior)
    out = {"game_id": rec["game_id"], "date": rec["date"], "phase": rec["phase"],
           "final": [rec["home"]["score"], rec["away"]["score"]], "checkpoints": {}}
    if isinstance(inputs, lr.NcaabResimRefusal):
        out["refusal"] = inputs.reason
        return out
    names = {}
    for frame in (inputs["home_players"], inputs["away_players"]):
        names.update(dict(zip(frame["athlete_id"], frame["player_name"])))
    plays = baseline.plays_of(rec)
    for cp_name, cp in CHECKPOINTS.items():
        gs, report = resume_state(rec, cp, names)
        if report.get("skip"):
            continue
        t0 = time.time()
        res = lr.resim_live_game(inputs, gs, sims=int(task["sims"]), base_seed=lr.stable_seed(rec["game_id"], int(cp)))
        if isinstance(res, lr.NcaabResimRefusal):
            out["checkpoints"][cp_name] = {"refusal": res.reason, "detail": res.detail}
            continue
        st = baseline.state_at(plays, cp) if cp > 0 else {"home": 0, "away": 0, "wp_home": None}
        rem = (2400 - cp) / 2400
        out["checkpoints"][cp_name] = {
            "total": res["total_mean"], "margin": res["home_margin_mean"], "p_home": res["home_win_prob"],
            "naive_total": st["home"] + st["away"] + prior.total * rem,
            "naive_margin": st["home"] - st["away"] + prior.home_margin * rem,
            "espn_wp": st.get("wp_home"), "sec": round(time.time() - t0, 2), **report,
        }
    return out


# ------------------------------------------------------------------ driver

def build_tasks(season: int, *, regular_sample: int, sims: int, seed: int, min_games: int) -> tuple[list[dict], dict]:
    records = [r for r in corpus.read_records(corpus.corpus_path(season)) if r.get("v") == corpus.RECORD_VERSION]
    records.sort(key=lambda r: (r["date"], r["game_id"]))
    box = players_mod.read_csv(players_mod.box_path(season))
    if not box:
        raise SystemExit(f"no player box at {players_mod.box_path(season)} -- run build_ncaab_player_priors.py first")
    d1 = ratings.load_registry()
    box_by_date: dict[str, list] = defaultdict(list)
    for row in box:
        box_by_date[row["date"]].append(row)
    rng = random.Random(seed)
    regular = [r for r in records if r["phase"] == "regular" and r["check"]["pbp_final_matches"]]
    chosen_ids = {r["game_id"] for r in rng.sample(regular, min(regular_sample, len(regular)))}
    chosen_ids |= {r["game_id"] for r in records if r["phase"] in TOURNAMENT_PHASES and r["check"]["pbp_final_matches"]}
    by_date: dict[str, list] = defaultdict(list)
    for r in records:
        by_date[r["date"]].append(r)
    tasks: list[dict] = []
    skipped: dict[str, int] = defaultdict(int)
    seen_team_rows: list[dict] = []
    seen_box: list[dict] = []
    from syndicate.features.ncaab import live_team_model as tm

    for day in sorted(by_date):
        todays = [r for r in by_date[day] if r["game_id"] in chosen_ids]
        if todays and seen_team_rows:
            team_r = ratings.compute_ratings(seen_team_rows, d1)
            table = tm.table_from_rows(({**v, "espn_id": k, "team": d1.get(k, k)} for k, v in team_r.items()),
                                       season=season, as_of=dt.date.fromisoformat(day) - dt.timedelta(days=1), source="walk_forward")
            pri = players_mod.compute_priors(seen_box, as_of=dt.date.fromisoformat(day), d1=d1)
            by_team: dict[str, list] = defaultdict(list)
            for p in pri.values():
                by_team[p["team_id"]].append(p)
            for r in todays:
                gp = tm.game_prior(table, r["home"]["id"], r["away"]["id"], neutral=r["neutral"]) if table else None
                if not isinstance(gp, tm.NcaabGamePrior):
                    skipped["no_team_prior"] += 1
                    continue
                if gp.home_games < min_games or gp.away_games < min_games:
                    skipped["fewer_than_min_games"] += 1
                    continue
                p = {k: getattr(gp, k) for k in gp.__dataclass_fields__}
                p["ratings_as_of"] = gp.ratings_as_of.isoformat()
                tasks.append({"record": r, "prior": p, "sims": sims,
                              "player_priors": {t: by_team.get(t, []) for t in (r["home"]["id"], r["away"]["id"])}})
        elif todays:
            skipped["first_date"] += len(todays)
        for r in by_date[day]:
            seen_team_rows.extend(r.get("box_rows") or [])
        seen_box.extend(box_by_date.get(day, []))
    return tasks, dict(skipped)


def _stats(errs: list[float]) -> dict[str, Any]:
    if not errs:
        return {"n": 0}
    return {"n": len(errs), "bias": round(statistics.fmean(errs), 3), "mae": round(statistics.fmean(abs(e) for e in errs), 3)}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    phases = sorted({r["phase"] for r in results})
    for phase in phases:
        rs = [r for r in results if r["phase"] == phase]
        sec: dict[str, Any] = {"games": len(rs), "refused": dict(sorted(_count(r.get("refusal") for r in rs if r.get("refusal")).items()))}
        for cp in CHECKPOINTS:
            rows = [(r, r["checkpoints"][cp]) for r in rs if cp in r["checkpoints"] and "total" in r["checkpoints"][cp]]
            if not rows:
                continue
            ft = [r["final"][0] + r["final"][1] for r, _ in rows]
            fm = [r["final"][0] - r["final"][1] for r, _ in rows]
            won = [1.0 if m > 0 else 0.0 for m in fm]
            paired = [(c["p_home"], c["espn_wp"], w) for (_r, c), w in zip(rows, won) if c.get("espn_wp") is not None]
            sec[cp] = {
                "n": len(rows),
                "engine_total": _stats([c["total"] - t for (_r, c), t in zip(rows, ft)]),
                "naive_total": _stats([c["naive_total"] - t for (_r, c), t in zip(rows, ft)]),
                "engine_margin": _stats([c["margin"] - m for (_r, c), m in zip(rows, fm)]),
                "naive_margin": _stats([c["naive_margin"] - m for (_r, c), m in zip(rows, fm)]),
                "brier_engine_vs_espn": {
                    "n": len(paired),
                    "engine": round(statistics.fmean((p - w) ** 2 for p, _e, w in paired), 4) if paired else None,
                    "espn": round(statistics.fmean((float(e) - w) ** 2 for _p, e, w in paired), 4) if paired else None,
                },
                "on_floor_mapped_share": round(statistics.fmean(1.0 if c.get("h_on_floor_mapped") and c.get("a_on_floor_mapped") else 0.0 for _r, c in rows), 3) if cp not in ("tip", "half") else None,
                "sec_per_game": round(statistics.fmean(c["sec"] for _r, c in rows), 2),
            }
        out[phase] = sec
    return out


def _count(values) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values:
        out[str(v)] += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--regular-sample", type=int, default=300)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--min-games", type=int, default=5)
    ap.add_argument("--max-games", type=int, default=None, help="smoke runs: only the first N tasks")
    ap.add_argument("--exact-target", action="store_true",
                    help="run the engine with EXACT_TARGET_CALIBRATION (SYNDICATE_NCAAB_EXACT_TARGET=1 in every worker)")
    ap.add_argument("--out", type=Path, required=True, help="results JSONL (resumable: finished games are skipped)")
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.exact_target:
        import os

        os.environ["SYNDICATE_NCAAB_EXACT_TARGET"] = "1"  # spawned workers inherit it
    tasks, skipped = build_tasks(args.season, regular_sample=args.regular_sample, sims=args.sims, seed=args.seed, min_games=args.min_games)
    # INTERLEAVED BY PHASE (seeded), so a partial run -- this takes hours at Idle on a shared host --
    # is a balanced read of every phase rather than November's regular season only.
    by_phase: dict[str, list] = defaultdict(list)
    for t in tasks:
        by_phase[t["record"]["phase"]].append(t)
    shuffler = random.Random(args.seed)
    for lst in by_phase.values():
        shuffler.shuffle(lst)
    queues = sorted(by_phase.values(), key=len)
    tasks = [q[i] for i in range(max((len(q) for q in queues), default=0)) for q in queues if i < len(q)]
    if args.max_games is not None:
        tasks = tasks[: args.max_games]
    done = {}
    if args.out.is_file():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["game_id"]] = r
    todo = [t for t in tasks if t["record"]["game_id"] not in done]
    print(f"[ncaab_live_resim_backtest] tasks={len(tasks)} done={len(done)} todo={len(todo)} skipped={skipped}", flush=True)
    started = time.time()
    if todo:
        from multiprocessing import Pool

        with Pool(processes=max(1, args.workers)) as pool, args.out.open("a", encoding="utf-8") as fh:
            for i, res in enumerate(pool.imap_unordered(run_game, todo, chunksize=1), 1):
                fh.write(json.dumps(res, separators=(",", ":")) + "\n")
                fh.flush()
                done[res["game_id"]] = res
                if i % 25 == 0:
                    print(f"[ncaab_live_resim_backtest] PROGRESS {i}/{len(todo)} elapsed_s={round(time.time() - started)}", flush=True)
    results = [done[t["record"]["game_id"]] for t in tasks if t["record"]["game_id"] in done]
    report = {
        "substrate": f"LOCAL: corpus {corpus.corpus_path(args.season)}, player box {players_mod.box_path(args.season)}",
        "season": args.season, "sims": args.sims, "regular_sample": args.regular_sample, "seed": args.seed,
        "min_games": args.min_games, "skipped_before_sim": skipped, "exact_target": bool(args.exact_target),
        "live_close": "NOT GRADED: ESPN keeps no in-play line history; needs OddsAPI in-play snapshots (user decision)",
        "phases": summarize(results),
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["phases"], indent=1)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
