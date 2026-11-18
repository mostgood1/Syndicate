"""Stage B of the Understat-outage backtest: does the REAL SoccerSim move its probabilities the way the link does?

Lane `understat-fallback-backtest` (2026-11-18), H5. Stage A (`understat_staleness_backtest.py`) scores
every match with a cross-fitted Poisson link; that is precise but it is not the engine, and a link
result once flipped sign in the engine (RATING V2, findings 2026-10-19). The engine costs ~0.117 s of
CPU per simulated match, so it runs here on a seeded random SAMPLE of Stage A's historical matches.

For each sampled match and arm, the arm's ratings are rebuilt exactly as Stage A builds them (same
functions: production `compute_team_ratings` + `_fill_promoted` + `_gate_few_match`), and the match is
simulated through production's `build_soccer_simulation_input` + `build_soccer_simulation_adapter`.
`match_id` is the same string in every arm, so every arm draws from the same seed (`_match_seed`).
Written per match, flushed, resumable (`--append`).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.soccer_season_audit.understat_staleness_backtest import (  # noqa: E402  (sets the fleet env)
    arm_ratings,
    build_name_map,
    fixture_name,
    load_league,
)
from syndicate.features.soccer.adapters import build_soccer_simulation_adapter  # noqa: E402
from syndicate.features.soccer.features.loaders import build_soccer_simulation_input  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=Path(r"C:\tmp\ustale_1118\fleet_src"))
    ap.add_argument("--fd-raw", type=Path, default=Path(r"C:\tmp\ustale_1118\fd_raw"))
    ap.add_argument("--stage-a-rows", type=Path, required=True, help="a league's Stage A rows.jsonl (the sampling frame)")
    ap.add_argument("--league", required=True)
    ap.add_argument("--per-league", type=int, default=24)
    ap.add_argument("--arms", default="U0,U4,S4,G90")
    ap.add_argument("--simulations", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1118)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        pass

    frame = [json.loads(line) for line in args.stage_a_rows.open(encoding="utf-8")]
    frame = [r for r in frame if r["league"] == args.league and r["segment"] != "now"]
    frame.sort(key=lambda r: (r["date"], r["home"], r["away"]))
    sample = random.Random(f"{args.seed}:{args.league}").sample(frame, min(args.per_league, len(frame)))
    sample.sort(key=lambda r: (r["date"], r["home"]))
    arms = [a for a in args.arms.split(",") if a]

    done = set()
    if args.out.exists():
        for line in args.out.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            done.add((r["date"], r["home"], r["away"], r["arm"]))
    data = load_league(args.league, args.src, args.fd_raw)
    us_names = sorted({str(r["team"]) for r in data["us_rows"]})
    fd_names = sorted({c[1] for c in data["calendar"]} | {c[2] for c in data["calendar"]})
    fd_to_us = build_name_map(fd_names, us_names)
    adapter = build_soccer_simulation_adapter(args.league)
    by_day = defaultdict(list)
    for r in sample:
        by_day[r["date"]].append(r)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8", newline="\n") as handle:
        for day in sorted(by_day):
            # Ratings are built over the WHOLE day's fixtures (as production does), then only the sampled ones run.
            day_fixtures = [(c[1], c[2]) for c in data["calendar"] if c[0] == day]
            for arm in arms:
                todo = [r for r in by_day[day] if (day, r["home"], r["away"], arm) not in done]
                if not todo:
                    continue
                ratings, meta = arm_ratings(data, arm, day, day_fixtures, fd_to_us)
                fixtures = [{"home_team": fixture_name(arm, r["home"], fd_to_us), "away_team": fixture_name(arm, r["away"], fd_to_us),
                             "match_id": f"{args.league}_{day}_{r['home']}_{r['away']}".replace(" ", "_")} for r in todo]
                sim_input = build_soccer_simulation_input(league=args.league, date=day, fixtures=fixtures,
                                                          ratings=ratings, simulations=args.simulations)
                outputs = list(adapter.simulate_games(sim_input).match_outputs)
                for r, out in zip(todo, outputs):
                    win = out.get("win_probability") or {}
                    tot = sum(float(win.get(o, 0.0)) for o in ("home", "draw", "away")) or 1.0
                    td = out.get("total_distribution") or {}
                    handle.write(json.dumps({
                        "league": args.league, "date": day, "home": r["home"], "away": r["away"], "arm": arm,
                        "actual": r["actual"], "hg": r["hg"], "ag": r["ag"], "close_x2": r.get("close_x2"),
                        "sim_home": float(win.get("home", 0.0)) / tot, "sim_draw": float(win.get("draw", 0.0)) / tot,
                        "sim_away": float(win.get("away", 0.0)) / tot, "sim_over25": td.get("over_2_5_probability"),
                        "sim_total_mean": td.get("mean"), "simulations": args.simulations,
                        "link": {k: (r["arms"].get(arm) or {}).get(k) for k in ("p", "p_fx", "over", "over_fx")},
                        "link_U0": {k: (r["arms"].get("U0") or {}).get(k) for k in ("p", "p_fx")},
                    }) + "\n")
                    handle.flush()
            print(f"{args.league} {day} done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
