"""WHY does MLB -- the most mature engine -- lose to climatology on pitcher outs?

`#440` Phase 7. MLB is the reference implementation: phase-1 complete, the only
sport with a real prop backtest, and the engine every other sport is meant to
converge toward. It scored **-6.74%** against climatology at production sim
counts. A negative number on the flagship is either a broken model or a
MISCALIBRATED one, and those have completely different remedies.

THE CLUE IS ALREADY IN THE SWEEP. At leash 0:

    dispersion  0.791  against a 0.798 target   -> the SHAPE is right
    bias       -1.470 outs                      -> the LOCATION is not

A correctly-shaped distribution sitting half an inning too high is a location
error. So this asks the question the 2026-08-14 audit demands before any skill
verdict: **decompose the bias first.** Its own words: "'No measured skill' would
have been the WRONG conclusion and would have suppressed a model that needs
calibrating rather than retiring."

METHOD.
  1. Score the raw forecast against climatology (the published number).
  2. Fit a single scalar shift on a TRAIN half, apply it to a HELD-OUT half,
     re-score there. One free parameter, fitted out-of-sample.
  3. Report how much of the deficit that one parameter recovers.

THE HOLD-OUT IS THE POINT. `plan_2026-08-14_models.md` D4 exists because the MLB
prop de-bias was fitted and scored on the SAME window, and "de-biased beats
baseline" was therefore an in-sample claim. Repeating that here would produce a
flattering number that means nothing. The split is by DATE, not by row, so no
game contributes to both halves.

Usage:
  py -3 scripts/diagnose_mlb_outs_deficit.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.model_scoring import crps_empirical  # noqa: E402

from scripts.grade_leash_betting import load_actuals  # noqa: E402


def pmf_mean(pmf: dict) -> float | None:
    vals, wts = [], []
    for k, v in pmf.items():
        try:
            vals.append(float(k)); wts.append(float(v))
        except (TypeError, ValueError):
            continue
    total = sum(wts)
    return (sum(v * w for v, w in zip(vals, wts)) / total) if total > 0 else None


def shift_pmf(pmf: dict, delta: float) -> dict:
    """Translate the whole distribution. Shape untouched, location moved."""
    out: dict[str, float] = defaultdict(float)
    for k, v in pmf.items():
        try:
            out[str(float(k) + delta)] += float(v)
        except (TypeError, ValueError):
            continue
    return dict(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmfs", type=Path,
                        default=REPO_ROOT / "reports/phase7/pmfs_sims_1000.json")
    parser.add_argument("--grid", type=int, default=5, help="leash value; 5 = production")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    recs = [r for r in json.loads(args.pmfs.read_text(encoding="utf-8"))
            if "error" not in r and int(r.get("grid", -1)) == args.grid]
    actuals = load_actuals()

    rows = []
    for r in recs:
        actual = actuals.get((r["date"], r["game_pk"], r["player_id"]))
        mean = pmf_mean(r["pmf"])
        if actual is None or mean is None:
            continue
        rows.append({"date": r["date"], "actual": float(actual), "mean": mean, "pmf": r["pmf"]})
    if not rows:
        print("nothing joined")
        return 1

    dates = sorted({r["date"] for r in rows})
    cut = len(dates) // 2
    train_dates, test_dates = set(dates[:cut]), set(dates[cut:])
    train = [r for r in rows if r["date"] in train_dates]
    test = [r for r in rows if r["date"] in test_dates]

    print("=" * 88)
    print(f"WHY IS MLB LOSING? -- bias decomposition, leash={args.grid} (production)")
    print("=" * 88)
    print(f"\n  starts {len(rows)}   dates {len(dates)}")
    print(f"  TRAIN {len(train)} starts / {len(train_dates)} dates "
          f"({dates[0]}..{dates[cut-1]})")
    print(f"  TEST  {len(test)} starts / {len(test_dates)} dates "
          f"({dates[cut]}..{dates[-1]})")
    print("  split by DATE so no game is in both halves\n")

    # bias fitted on TRAIN only. actual - mean; positive => model runs LOW.
    bias = statistics.fmean(r["actual"] - r["mean"] for r in train)
    print(f"  bias fitted on TRAIN:  {bias:+.4f} outs "
          f"(negative = the sim projects too MANY outs)\n")

    # climatology for the TEST half, from TEST actuals
    test_actuals = [r["actual"] for r in test]
    clim_pmf = {str(v): c for v, c in Counter(test_actuals).items()}
    clim = statistics.fmean(
        s for s in (crps_empirical(a, clim_pmf) for a in test_actuals) if s is not None)

    raw = statistics.fmean(
        s for s in (crps_empirical(r["actual"], r["pmf"]) for r in test) if s is not None)
    deb = statistics.fmean(
        s for s in (crps_empirical(r["actual"], shift_pmf(r["pmf"], bias)) for r in test)
        if s is not None)

    skill_raw = 1 - raw / clim
    skill_deb = 1 - deb / clim

    print(f"  {'forecast':22s} {'CRPS':>9s} {'skill vs climatology':>22s}")
    print("  " + "-" * 56)
    print(f"  {'climatology':22s} {clim:9.4f} {'0.00% (by definition)':>22s}")
    print(f"  {'raw sim':22s} {raw:9.4f} {skill_raw:21.2%}")
    print(f"  {'sim + fitted shift':22s} {deb:9.4f} {skill_deb:21.2%}")

    recovered = skill_deb - skill_raw
    print(f"\n  ONE out-of-sample scalar recovers {recovered * 100:+.2f} skill points.")
    if skill_deb > 0:
        print("  => THE ENGINE IS NOT BROKEN. It is MISCALIBRATED, and a single")
        print("     location correction takes it from losing to BEATING climatology.")
        print("     Remedy is a calibration profile, NOT a model rewrite.")
    elif recovered > 0.02:
        print("  => Bias is a LARGE part of the deficit but does not close it.")
        print("     Calibration helps materially; something else is also wrong.")
    else:
        print("  => Bias is NOT the explanation. The deficit is in the conditional")
        print("     information itself, and a calibration layer will not rescue it.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"bias_train": bias, "n_train": len(train), "n_test": len(test),
             "crps_climatology": clim, "crps_raw": raw, "crps_debiased": deb,
             "skill_raw": skill_raw, "skill_debiased": skill_deb}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
