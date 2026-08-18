"""Does per-PA common-random-numbers actually cut difference-variance? `#440`.

`GameConfig.crn_pa_seeding` exists to make A/B comparisons of the sim cheaper to
resolve. That claim is testable and this tests it, rather than asserting it.

**THE QUANTITY THAT MATTERS IS THE VARIANCE OF THE DIFFERENCE, NOT OF EITHER
ARM.** A comparison is noisy because `stat(ON) - stat(OFF)` moves between seeds,
so that spread is what has to shrink. Each arm's own variance is irrelevant and
will not improve -- reporting it would look like a result and mean nothing.

Three checks, in order:

  1. **determinism preserved** -- same seed twice, flag OFF, identical output.
     A variance-reduction change that quietly broke reproducibility would be
     worse than the problem it solves.
  2. **reachability** -- flag ON differs from flag OFF. It re-seeds, so it MUST
     change results; if it does not, it is not running.
  3. **the actual claim** -- spread of (ON - OFF) across seeds, with CRN off vs
     CRN on. Lower is better, and the ratio is the payoff.

Usage:
  py -3 scripts/validate_crn_pa_seeding.py --games 8 --sims 40 --seeds 10
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

STATS = ("H", "TB", "R", "RBI")


def _totals(res) -> dict:
    out = {k: 0 for k in STATS}
    for _pid, st in res.batter_stats.items():
        for k in STATS:
            try:
                out[k] += int(st.get(k, 0) or 0)
            except Exception:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--sims", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    from sim_engine.data.arsenal import apply_arsenal_to_pitcher
    from sim_engine.data.conditional_mix import apply_conditional_mix_to_pitcher
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    paths = sorted(glob.glob(str(REPO / "data/mlb_source/source_artifacts/data/**/"
                                        "roster_objs/roster_obj_*.json"), recursive=True))
    if not paths:
        print("REFUSED: no roster artifacts")
        return 1

    games = []
    for p in paths:
        if len(games) >= args.games:
            break
        try:
            r = read_game_roster_artifact(Path(p))
        except Exception:
            continue
        if r.get("home") is not None and r.get("away") is not None:
            games.append(r)
    if not games:
        print("REFUSED: no readable rosters")
        return 1
    print(f"{len(games)} games x {args.sims} sims x {args.seeds} seeds\n")

    def run(game, seed, mix_on, crn):
        away, home = game["away"], game["home"]
        for roster in (away, home):
            for pr in [roster.lineup.pitcher] + list(roster.lineup.bullpen or []):
                if pr is None:
                    continue
                apply_arsenal_to_pitcher(pr, season=args.season)
                pr.conditional_arsenal = {}
                pr.count_bucket_map = {}
                if mix_on:
                    apply_conditional_mix_to_pitcher(pr, season=args.season)
        cfg = GameConfig(rng_seed=seed, manager_pitching="v2", crn_pa_seeding=crn)
        agg = {k: 0 for k in STATS}
        for i in range(args.sims):
            try:
                res = simulate_game(away, home, replace(cfg, rng_seed=seed + i))
            except Exception:
                continue
            t = _totals(res)
            for k in STATS:
                agg[k] += t[k]
        return agg

    print("1. DETERMINISM with the flag OFF (same seed twice)")
    a = run(games[0], 99, False, False)
    b = run(games[0], 99, False, False)
    print(f"   {a}")
    print(f"   {b}")
    print(f"   identical: {a == b}")
    if a != b:
        print("   REFUSED: the engine is not reproducible; variance work is meaningless")
        return 1

    print("\n2. REACHABILITY (flag ON must differ -- it re-seeds)")
    c = run(games[0], 99, False, True)
    print(f"   crn off {a}")
    print(f"   crn on  {c}")
    print(f"   different: {a != c}")
    if a == c:
        print("   REFUSED: crn_pa_seeding is INERT")
        return 1

    print("\n3. SPREAD OF (mix ON - mix OFF) ACROSS SEEDS -- the actual claim")
    out = {}
    for crn in (False, True):
        diffs = {k: [] for k in STATS}
        for s in range(args.seeds):
            seed = 1000 + s * 7919
            tot_on = {k: 0 for k in STATS}
            tot_off = {k: 0 for k in STATS}
            for g in games:
                r_on = run(g, seed, True, crn)
                r_off = run(g, seed, False, crn)
                for k in STATS:
                    tot_on[k] += r_on[k]
                    tot_off[k] += r_off[k]
            for k in STATS:
                # per-sim-game difference, so the number is comparable across
                # configurations rather than scaling with the run size
                diffs[k].append((tot_on[k] - tot_off[k]) / (len(games) * args.sims))
        out[crn] = diffs
        label = "CRN ON " if crn else "CRN OFF"
        print(f"\n   {label}")
        for k in STATS:
            d = diffs[k]
            print(f"     {k:<4} mean {statistics.mean(d):+8.4f}   "
                  f"sd {statistics.pstdev(d):7.4f}")

    print("\n   VARIANCE REDUCTION (sd CRN-off / sd CRN-on, higher is better)")
    ratios = []
    for k in STATS:
        s0 = statistics.pstdev(out[False][k])
        s1 = statistics.pstdev(out[True][k])
        r = (s0 / s1) if s1 > 0 else float("inf")
        ratios.append(r)
        print(f"     {k:<4} {s0:.4f} -> {s1:.4f}   {r:.2f}x")
    good = statistics.mean([r for r in ratios if r != float("inf")] or [0])
    print(f"\n   mean {good:.2f}x  =>  equivalent to ~{good**2:.1f}x the sims "
          f"for the same resolution")
    if good < 1.05:
        print("   NO MATERIAL REDUCTION. The flag is not worth using; say so.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
