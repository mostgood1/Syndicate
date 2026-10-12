"""Game-matched re-fit of the NBA end-game fouling mechanism (lane `nba-native-live-resim`, PRE-REGISTERED in
`.syndicate/findings_2026-10-09_nba_live_situation_targets.md` §7, 2026-10-12, before any measurement).

For every 2025-26 REGULAR-season game whose state at exactly 2:00 Q4 has |margin| 1..10:
  * cut the real ESPN summary at 2:00 Q4 (`truncate_summary_at`) and resume the native sim from it through the SAME
    code path the live tick uses (`live_resim.resume_from_summary` -> `map_state_names` -> production's engine
    object), on that game's own as-of engine inputs;
  * for each p in the grid, 40 draws with COMMON random numbers (the same seed for every p), mechanism window 120 s,
    clock-governed extension on, p applied to every deficit bucket (the game's own bucket is what is graded);
  * REAL = regulation points after 2:00 (Q4 linescore total minus Q4 points at 2:00) and FTA after 2:00 (pbp).

`run` writes one row per game (shardable); `summarize` reads the rows, picks p per bucket on FIT and grades VALIDATION
once. Run at nice 19.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]

GRID = (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)
FIT = ("2025-11-01", "2026-02-28")
VALID = ("2026-03-01", "2026-04-12")


def bucket(deficit: int) -> str:
    return "1-3" if deficit <= 3 else ("4-6" if deficit <= 6 else "7-10")


def run(args: argparse.Namespace) -> int:
    import pickle

    import numpy as np

    import basketball_live_checkpoint_backtest as bt
    from syndicate.features.nba import live_resim as lr
    from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local

    games = [g for g in bt.load_games(Path(args.games)) if g.population == "regular" and FIT[0] <= g.date <= VALID[1]]
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        games = [g for g in games if zlib.crc32(g.event_id.encode()) % n == i]
    inputs_index = bt.index_engine_inputs(Path(args.engine_inputs))
    caches = [Path(c) for c in args.summary_cache]
    engine = _engine_for_league_local("nba")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(ln)["event_id"] for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()}
    counts: Dict[str, int] = {}
    with out.open("a", encoding="utf-8") as fh:
        for g in games:
            if g.event_id in done:
                continue
            key = (g.date, bt.ESPN_TO_TRI.get(g.home, g.home), bt.ESPN_TO_TRI.get(g.away, g.away))
            path = inputs_index.get(key)
            summary = next((bt._read_gz(c / f"summary_{g.event_id}.json.gz") for c in caches
                            if (c / f"summary_{g.event_id}.json.gz").exists()), None)
            if path is None or summary is None or len(g.period_points) < 4:
                counts["skip_no_inputs_or_summary"] = counts.get("skip_no_inputs_or_summary", 0) + 1
                continue
            res = lr.resume_from_summary(bt.truncate_summary_at(summary, 4, 120.0), date=g.date)
            if isinstance(res, lr.NbaResimRefusal):
                counts[f"refused_{res.reason}"] = counts.get(f"refused_{res.reason}", 0) + 1
                continue
            _st, gs, facts = res
            margin = facts.home_score - facts.away_score
            if not (1 <= abs(margin) <= 10) or facts.period != 4:
                counts["skip_margin_outside_1_10"] = counts.get("skip_margin_outside_1_10", 0) + 1
                continue
            with path.open("rb") as f:
                inputs = dict(pickle.load(f)["kwargs"])
            gs, _m = lr.map_state_names(gs, inputs["home_players"], inputs["away_players"])
            q4_at = gs.home_period_pts[3] + gs.away_period_pts[3]
            real_pts = sum(g.period_points[3]) - q4_at
            real_fta = sum(1 for p in g.plays if p.period == 4 and p.clock_s < 120 and p.kind == "ft")
            seed = zlib.crc32(f"eg|{g.event_id}".encode()) & 0x7FFFFFFF
            sims: Dict[str, Any] = {}
            for p in GRID:
                mech = {"record_events": True}
                if p > 0:
                    mech.update(endgame_foul_window_s=120, endgame_foul_max_deficit=10, endgame_foul_p=0.0,
                                endgame_foul_p_by_deficit=(p, p, p), endgame_foul_seconds=5.0,
                                endgame_extend_possessions=True)
                kw = lr.with_live_mechanisms(inputs, mech)
                rng = np.random.default_rng(seed)
                pts, fta = [], []
                for _ in range(args.draws):
                    hb, ab, hq, aq = engine.simulate_pbp_game_boxscore(rng=rng, **kw, state=gs)
                    pts.append(int(hq[3] + aq[3]) - q4_at)
                    evs = (hb.get("events") or []) + (ab.get("events") or [])
                    fta.append(sum(int(e.get("fta", 0)) for e in evs if e.get("q") == 4 and e.get("type") == "FTA"))
                sims[str(p)] = {"pts": statistics.fmean(pts), "fta": statistics.fmean(fta)}
            fh.write(json.dumps({"event_id": g.event_id, "date": g.date, "bucket": bucket(abs(margin)),
                                 "margin_at_2min": margin, "real_pts": real_pts, "real_fta": real_fta, "sims": sims}) + "\n")
            fh.flush()
            counts["graded"] = counts.get("graded", 0) + 1
    print("EG_FIT_RUN " + json.dumps(counts), flush=True)
    return 0


def _boot_ci(vals: List[float], reps: int = 2000, seed: int = 20261012) -> List[float]:
    rng = random.Random(seed)
    n = len(vals)
    ms = sorted(statistics.fmean(vals[rng.randrange(n)] for _ in range(n)) for _ in range(reps))
    return [ms[int(0.025 * reps)], ms[int(0.975 * reps) - 1]]


def summarize(args: argparse.Namespace) -> int:
    rows = []
    for f in args.rows:
        rows += [json.loads(ln) for ln in Path(f).read_text(encoding="utf-8").splitlines() if ln.strip()]
    report: Dict[str, Any] = {}
    for b in ("1-3", "4-6", "7-10"):
        fit = [r for r in rows if r["bucket"] == b and FIT[0] <= r["date"] <= FIT[1]]
        val = [r for r in rows if r["bucket"] == b and VALID[0] <= r["date"] <= VALID[1]]
        if not fit:
            continue
        err = {p: statistics.fmean(r["sims"][str(p)]["pts"] - r["real_pts"] for r in fit) for p in GRID}
        chosen = min(GRID, key=lambda p: abs(err[p]))
        cell: Dict[str, Any] = {
            "fit_n": len(fit), "real_pts_fit": statistics.fmean(r["real_pts"] for r in fit),
            "real_fta_fit": statistics.fmean(r["real_fta"] for r in fit),
            "sim_minus_real_pts_by_p_fit": {str(p): round(e, 3) for p, e in err.items()},
            "sim_fta_by_p_fit": {str(p): round(statistics.fmean(r["sims"][str(p)]["fta"] for r in fit), 3) for p in GRID},
            "chosen_p": chosen,
        }
        if val:
            real = [r["real_pts"] for r in val]
            ci = _boot_ci(real)
            half = (ci[1] - ci[0]) / 2
            e_ch = statistics.fmean(r["sims"][str(chosen)]["pts"] - r["real_pts"] for r in val)
            e_0 = statistics.fmean(r["sims"]["0.0"]["pts"] - r["real_pts"] for r in val)
            cell.update({"valid_n": len(val), "real_pts_valid": statistics.fmean(real), "real_ci95_valid": ci,
                         "valid_err_chosen": round(e_ch, 3), "valid_err_p0": round(e_0, 3),
                         "ship": bool(abs(e_ch) <= half and abs(e_ch) < abs(e_0))})
        report[b] = cell
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--games", required=True)
    r.add_argument("--engine-inputs", required=True)
    r.add_argument("--summary-cache", action="append", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--draws", type=int, default=40)
    r.add_argument("--shard")
    s = sub.add_parser("summarize")
    s.add_argument("--rows", nargs="+", required=True)
    s.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return run(args) if args.cmd == "run" else summarize(args)


if __name__ == "__main__":
    sys.exit(main())
