"""Does in-sim substitution actually fix the opportunity bias? `#440` P2.

The defect, measured on production artifacts: the sim projects `ab_mean` 4.006
against an actual 3.495 (**+14.6%**), because it never substitutes position
players. `scripts/build_mlb_manager_tendencies.py` fitted the hazard;
`simulate.py` now consumes it behind `GameConfig.position_substitutions`.

This replays REAL roster artifacts with the flag OFF and ON and compares
simulated starter AB to the same 3.495 target. It is the payoff measurement: if
starter AB does not fall toward the actual, the consumer is wired but useless.

Deliberately narrow -- it measures OPPORTUNITY, not accuracy. Whether the
reduced opportunity improves the market scoreboard is a separate question that
`mlb_opportunity_haircut.py` answers, and it should be re-run after this.

Usage:
  py -3 scripts/measure_substitution_effect.py --games 40 --sims 60
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "mlb_bettingv2"
for p in (str(REPO_ROOT), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

SNAPSHOTS = REPO_ROOT / "data/mlb_source/source_artifacts/data/daily_pitcher_props/snapshots"
PK_RE = re.compile(r"_pk(\d+)_")
ACTUAL_AB = 3.495  # measured, 2,495 lineup player-games


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=40)
    parser.add_argument("--sims", type=int, default=60)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    paths = []
    for snapshot in sorted(SNAPSHOTS.iterdir()):
        for path in sorted((snapshot / "roster_objs").glob("roster_obj_*.json")):
            if PK_RE.search(path.name):
                paths.append(path)
    paths = paths[:args.games]
    if not paths:
        print("no roster artifacts found")
        return 1

    print("=" * 84)
    print("IN-SIM SUBSTITUTION — effect on starter opportunity")
    print("=" * 84)
    print(f"\n  games {len(paths)}   sims/game {args.sims}   target actual AB {ACTUAL_AB}\n")

    results = {}
    bench_used = {}
    for enabled in (False, True):
        starter_abs: list[float] = []
        bench_abs: list[float] = []
        for path in paths:
            try:
                raw = read_game_roster_artifact(path)
                away, home = raw["away"], raw["home"]
            except Exception:
                continue
            starters = {b.player.mlbam_id for r in (away, home) for b in r.lineup.batters}
            bench_ids = {b.player.mlbam_id for r in (away, home) for b in (r.lineup.bench or [])}
            cfg = GameConfig(rng_seed=args.seed, manager_pitching="v2",
                             position_substitutions=enabled)
            for i in range(args.sims):
                try:
                    res = simulate_game(away, home, replace(cfg, rng_seed=args.seed + i))
                except Exception:
                    continue
                for pid, st in res.batter_stats.items():
                    ab = float(st.get("AB", 0) or 0)
                    if int(pid) in starters:
                        starter_abs.append(ab)
                    elif int(pid) in bench_ids:
                        bench_abs.append(ab)
        if not starter_abs:
            print(f"  enabled={enabled}: nothing simulated")
            continue
        mean_ab = statistics.fmean(starter_abs)
        results[enabled] = mean_ab
        bench_used[enabled] = (statistics.fmean(bench_abs) if bench_abs else 0.0, len(bench_abs))
        bias = mean_ab - ACTUAL_AB
        print(f"  substitutions {'ON ' if enabled else 'OFF'}: "
              f"starter AB {mean_ab:.3f}   bias {bias:+.3f}  ({bias / ACTUAL_AB:+.1%})   "
              f"n={len(starter_abs)}")

    if len(results) == 2:
        before, after = results[False], results[True]
        closed = (before - after)
        gap_before, gap_after = before - ACTUAL_AB, after - ACTUAL_AB
        print(f"\n  starter AB moved {closed:+.4f} toward actual")
        print(f"  bias {gap_before:+.3f} -> {gap_after:+.3f}   "
              f"({(1 - abs(gap_after) / abs(gap_before)) * 100:.1f}% of the gap closed)"
              if gap_before else "")
        mean_bench, n_bench = bench_used.get(True, (0.0, 0))
        print(f"  bench AB when ON: mean {mean_bench:.3f} over {n_bench} appearances")
        if closed <= 0:
            print("\n  NO EFFECT — the consumer is wired but is not removing anyone.")
        elif abs(gap_after) < abs(gap_before):
            print("\n  The consumer reduces the measured opportunity bias.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
