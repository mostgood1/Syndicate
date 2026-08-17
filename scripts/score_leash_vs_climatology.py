"""CRPS SKILL SCORE against climatology, for the F5-leash grid. `#440` Phase 7.

WHY THIS EXISTS, and it is a correction to my own earlier verdict.
`sweep_starter_leash.py` decided "beats base" by comparing the model's MEAN
ABSOLUTE ERROR to a CONSTANT point prediction, and on that basis
`.syndicate/state.md` was told the model "loses to a constant baseline at every
grid point". That is a POINT-forecast test applied to a DISTRIBUTIONAL model,
and it is the wrong instrument twice over:

  1. A constant has no distribution. It cannot price P(outs > 17.5) at all, so
     it is not a competitor for a prop model -- the thing being sold is the
     distribution, not the mean.
  2. MAE ignores calibration and sharpness entirely. The sweep's own headline
     result was that dispersion moved 1.002 -> 0.791 against a 0.7979 target,
     i.e. the DISTRIBUTION got dramatically better while MAE barely moved. MAE
     cannot see that, and it was the metric the verdict rested on.

The proper skill test for a probabilistic forecast is CRPS against CLIMATOLOGY
-- the marginal empirical distribution of the same quantity. `model_scoring`
already has the exact integrator (`crps_empirical`), so this reuses it rather
than adding a sixth scoring implementation.

    skill = 1 - CRPS_model / CRPS_climatology
    > 0  the model beats climatology
    = 0  no better than knowing the league-wide distribution of outs
    < 0  worse than knowing nothing about the specific start

NOTE THE BASELINE IS DELIBERATELY HARD. Climatology is computed IN-SAMPLE, from
the very actuals being scored, so it is fitted to the test set and the model is
not. Beating it is therefore a conservative result, and losing to it is not
automatically damning -- both directions are stated rather than one.

Reads the PMFs already dumped by `sweep_starter_leash.py --dump-pmfs`. No
re-simulation.

Usage:
  py -3 scripts/score_leash_vs_climatology.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import crps_empirical  # noqa: E402

from scripts.grade_leash_betting import load_actuals  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmfs", type=Path, default=REPO_ROOT / "reports/phase7/leash_pmfs.json")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    if not args.pmfs.is_file():
        print(f"missing {args.pmfs} -- run sweep_starter_leash.py --dump-pmfs first")
        return 1

    records = [r for r in json.loads(args.pmfs.read_text(encoding="utf-8")) if "error" not in r]
    actuals = load_actuals()

    # Pair every record with its outcome, and collect the actuals ONCE (they do
    # not depend on the grid value -- the same starts are replayed at each).
    paired: dict[int, list[tuple[float, dict]]] = defaultdict(list)
    outcome_by_start: dict[tuple[str, str, str], float] = {}
    for rec in records:
        key = (rec["date"], rec["game_pk"], rec["player_id"])
        actual = actuals.get(key)
        if actual is None:
            continue
        paired[int(rec["grid"])].append((float(actual), rec["pmf"]))
        outcome_by_start[key] = float(actual)

    if not paired:
        print("nothing paired -- no actuals joined")
        return 1

    # CLIMATOLOGY: the marginal empirical distribution of outs over these starts.
    clim_pmf = {str(v): c for v, c in Counter(outcome_by_start.values()).items()}
    n_starts = len(outcome_by_start)

    clim_scores = [
        s for s in (crps_empirical(a, clim_pmf) for a in outcome_by_start.values()) if s is not None
    ]
    clim_crps = sum(clim_scores) / len(clim_scores)

    print("=" * 92)
    print("F5 LEASH -- CRPS SKILL SCORE vs CLIMATOLOGY")
    print("=" * 92)
    print(f"\n  distinct starts        {n_starts}")
    print(f"  climatology support    {len(clim_pmf)} distinct outs values")
    print(f"  CRPS(climatology)      {clim_crps:.4f}   <- the bar")
    print("\n  Climatology is fitted IN-SAMPLE to these same actuals, so it is a")
    print("  HARD baseline and beating it is a conservative result.\n")

    header = f"  {'leash':>6s} {'n':>5s} {'CRPS model':>11s} {'CRPS clim':>10s} {'skill':>9s}  verdict"
    print(header)
    print("  " + "-" * (len(header) + 4))

    rows = []
    for grid in sorted(paired):
        scores = [s for s in (crps_empirical(a, p) for a, p in paired[grid]) if s is not None]
        if not scores:
            continue
        model_crps = sum(scores) / len(scores)
        skill = 1.0 - (model_crps / clim_crps) if clim_crps > 0 else 0.0
        verdict = "BEATS climatology" if skill > 0 else "loses to climatology"
        mark = "  <- current" if grid == 5 else ""
        rows.append({"leash": grid, "n": len(scores), "crps_model": model_crps,
                     "crps_climatology": clim_crps, "skill_score": skill})
        print(f"  {grid:6d} {len(scores):5d} {model_crps:11.4f} {clim_crps:10.4f} "
              f"{skill:+8.2%}  {verdict}{mark}")

    print("\n  skill = 1 - CRPS_model / CRPS_climatology.")
    print("  This SUPERSEDES the sweep's 'beats base' column, which compared MAE to a")
    print("  CONSTANT POINT prediction -- a point test on a distributional model.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"n_starts": n_starts,
                                         "crps_climatology": clim_crps,
                                         "rows": rows}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
