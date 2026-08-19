"""Is a market's shipped Normal/log-normal blend weight a real, stable
property of the market, or fit-half noise? Generalizes
`check_passing_attempts_skew_stability.py` (which only handled the
CLIPPED-at-1.0 case) to any market. (`nfl-yardage-blend-stability` lane,
follow-up to `#471` / `nfl-player-props-skew-fix`.)

WHY THIS CHECK, GENERALIZED. Every weight in `syndicate/features/nfl/
props.py`'s `_COVER_PROBABILITY_BLEND_WEIGHT` was computed ONCE: the
closed-form Brier-minimizing weight fit on 2022-2023, with its
OUT-OF-SAMPLE improvement reported (never re-selected) on 2024-2025.
That one-way test validates the DIRECTION (does applying this weight to
new data beat w=0) but says nothing about whether a DIFFERENT weight,
chosen from the 2024-2025 half itself, would look similar or wildly
different -- i.e. whether the fit-half's specific number is a stable
estimate or a lucky/unlucky draw. `passing_attempts` already answered
this the hard way: its fit-half optimum (1.14) was capped at the log-
normal boundary (1.0), and the independent half's own optimum (0.88)
landed on the OPPOSITE side of that boundary -- the two disagreed both in
magnitude and in direction relative to 1.0.

This script asks the same question for markets that were never clipped:
does the independent half's own optimal weight roughly agree with the
fit half's, or is the whole blend-weight family this noisy?

STABILITY CRITERION (stated up front, not chosen after seeing the
numbers): both halves' optimal weights must (a) share the same sign
(both positive -- a sign disagreement means the correction's DIRECTION
isn't established) and (b) sit within a 2x ratio of each other (larger /
smaller <= 2.0) -- the same "roughly 2x apart" threshold the
`nfl-yardage-blend-stability` lane pre-registered before running this.

DATA CONSTRAINT, STATED HONESTLY (same as the passing_attempts version):
only two independent halves exist. If a market is unstable, this script
does NOT invent a third split to resolve it -- it reports the
instability and recommends the MORE CONSERVATIVE (closer to 0) of the
two estimates, or leaves the shipped value if it already sits at or
below the conservative one.

Usage:
  py -3 scripts/check_nfl_blend_weight_stability.py --stats receiving_yards,rushing_yards
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backtest_nfl_props import collect_raw
from calibrate_nfl_cover_probability_blend import blend_probs
from calibrate_nfl_cover_probability_blend import brier
from calibrate_nfl_cover_probability_blend import optimal_blend_weight
from compare_nfl_cover_probability_models import collect_aligned_prob_pairs
from syndicate.features.nfl.props import _COVER_PROBABILITY_BLEND_WEIGHT

HALF_A_SEASONS = [2022, 2023]
HALF_B_SEASONS = [2024, 2025]
RATIO_THRESHOLD = 2.0  # pre-registered in the lane block before this ran


def check_one_market(stat: str, raw_a: list, raw_b: list) -> dict[str, Any]:
    normal_a, lognormal_a, outcomes_a = collect_aligned_prob_pairs(raw_a, stat)
    normal_b, lognormal_b, outcomes_b = collect_aligned_prob_pairs(raw_b, stat)

    if len(outcomes_a) < 100 or len(outcomes_b) < 100:
        print(f"  {stat}: below 100 in one half, not measurable")
        return {"stat": stat, "verdict": "not measurable (sample too small)"}

    w_a = optimal_blend_weight(normal_a, lognormal_a, outcomes_a)
    w_b = optimal_blend_weight(normal_b, lognormal_b, outcomes_b)
    shipped = _COVER_PROBABILITY_BLEND_WEIGHT.get(stat, 0.0)

    same_sign = (w_a > 0) == (w_b > 0)
    ratio = None
    within_ratio = False
    if same_sign and w_a != 0 and w_b != 0:
        ratio = max(abs(w_a), abs(w_b)) / min(abs(w_a), abs(w_b))
        within_ratio = ratio <= RATIO_THRESHOLD
    stable = same_sign and within_ratio

    print(f"\n  {stat}  (shipped w={shipped})")
    print(f"    half A ({HALF_A_SEASONS}): n={len(outcomes_a)}, optimal w = {w_a:.4f}")
    print(f"    half B ({HALF_B_SEASONS}): n={len(outcomes_b)}, optimal w = {w_b:.4f}")
    print(f"    same sign: {same_sign}   ratio: {f'{ratio:.2f}x' if ratio is not None else 'n/a'}   "
          f"stable (same sign AND ratio<={RATIO_THRESHOLD}x): {stable}")

    result: dict[str, Any] = {
        "stat": stat, "shipped_weight": shipped,
        "half_a": {"seasons": HALF_A_SEASONS, "n": len(outcomes_a), "w_optimal": round(w_a, 4)},
        "half_b": {"seasons": HALF_B_SEASONS, "n": len(outcomes_b), "w_optimal": round(w_b, 4)},
        "same_sign": same_sign, "ratio": round(ratio, 4) if ratio is not None else None,
        "stable": stable,
    }

    if stable:
        print(f"    VERDICT: STABLE. Shipped weight {shipped} is well-supported by both")
        print(f"    independent halves ({w_a:.4f} and {w_b:.4f}) -- no change needed.")
        result["recommendation"] = "no change -- shipped weight is well-supported"
        result["verdict"] = "stable"
    else:
        conservative = min(abs(w_a), abs(w_b)) if same_sign else 0.0
        print(f"    VERDICT: UNSTABLE. The two halves disagree {'in sign' if not same_sign else 'in magnitude'}.")
        print(f"    Conservative fallback (min magnitude, or 0.0 if signs disagree): {conservative:.4f}")
        recommendation = (
            f"shipped weight {shipped} vs conservative estimate {conservative:.4f} -- "
            + ("weight already at or below the conservative estimate, no change needed"
               if shipped <= conservative + 1e-9
               else "shipped weight exceeds the conservative estimate, consider lowering")
        )
        print(f"    {recommendation}")
        result["conservative_weight"] = round(conservative, 4)
        result["recommendation"] = recommendation
        result["verdict"] = "unstable"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats", default="receiving_yards,rushing_yards")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    stats = [s.strip() for s in args.stats.split(",") if s.strip()]
    print(f"Checking blend-weight stability for: {stats}")
    print(f"Stability criterion (pre-registered): same sign AND ratio <= {RATIO_THRESHOLD}x")

    raw_a, _ = collect_raw(HALF_A_SEASONS)
    raw_b, _ = collect_raw(HALF_B_SEASONS)

    results = {stat: check_one_market(stat, raw_a, raw_b) for stat in stats}

    print("\nRESULT block:")
    print(json.dumps(results, indent=2))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWritten to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
