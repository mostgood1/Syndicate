"""Is passing_attempts' unclipped blend optimum (w=1.14, capped to 1.0 by
`nfl-player-props-skew-fix`) a real, stable property of the market, or
noise from one particular 2022-2023/2024-2025 split? (`nfl-passing-
attempts-skew-extrapolation` lane, follow-up to `#471`.)

WHY THIS CHECK, SPECIFICALLY. `calibrate_nfl_cover_probability_blend.py`
only ever computed ONE closed-form optimal weight per market -- fit on
2022-2023, reported (never re-selected) on 2024-2025. For every market
except `passing_attempts` the fit-half optimum landed inside [0, 1], so
clipping was a no-op. For `passing_attempts` it landed at 1.14 and got
capped -- meaning the fit half's data wanted MORE skew correction than a
log-normal distribution can express, and shipping stopped exactly at the
boundary of what a real, validated distributional model supports.

Before extrapolating past that boundary (blending PAST pure log-normal,
which has no distributional interpretation any more -- it is pure
curve-fitting at that point), this checks whether the SAME closed-form
optimum, computed INDEPENDENTLY on the 2024-2025 half, agrees. Two
genuinely independent seasons' worth of real games both wanting w>1 is
real signal; one split producing 1.14 and the other producing something
very different is the fit half's own sampling noise, and extrapolating
on it would be shipping an unvalidated correction dressed up as a
measurement.

DATA CONSTRAINT, STATED HONESTLY: only two independent halves exist
(4 total seasons). A fully rigorous fit/validate/held-out-test split
would need a third slice this repo does not have without going back
further than 2022 (nflverse coverage) or slicing weeks within a season
(introduces its own leakage/correlation concerns this script does not
attempt to solve). So: if both halves agree, the shipped weight is
chosen conservatively (the MINIMUM of the two, not their average or the
more aggressive one) and its Brier is reported on BOTH halves combined --
disclosed as evaluated on the same data that chose it, not a fresh
out-of-sample number, because none is available with only two splits.

Usage:
  py -3 scripts/check_passing_attempts_skew_stability.py
"""

from __future__ import annotations

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

STAT = "passing_attempts"
HALF_A_SEASONS = [2022, 2023]
HALF_B_SEASONS = [2024, 2025]


def main() -> int:
    print(f"Checking stability of the {STAT} blend weight across two independent halves...")

    raw_a, _ = collect_raw(HALF_A_SEASONS)
    raw_b, _ = collect_raw(HALF_B_SEASONS)

    normal_a, lognormal_a, outcomes_a = collect_aligned_prob_pairs(raw_a, STAT)
    normal_b, lognormal_b, outcomes_b = collect_aligned_prob_pairs(raw_b, STAT)

    w_a = optimal_blend_weight(normal_a, lognormal_a, outcomes_a)
    w_b = optimal_blend_weight(normal_b, lognormal_b, outcomes_b)

    print(f"\n  half A ({HALF_A_SEASONS}): n={len(outcomes_a)}, optimal w (unclipped) = {w_a:.4f}")
    print(f"  half B ({HALF_B_SEASONS}): n={len(outcomes_b)}, optimal w (unclipped) = {w_b:.4f}")

    result: dict[str, Any] = {
        "stat": STAT,
        "half_a": {"seasons": HALF_A_SEASONS, "n": len(outcomes_a), "w_optimal_unclipped": round(w_a, 4)},
        "half_b": {"seasons": HALF_B_SEASONS, "n": len(outcomes_b), "w_optimal_unclipped": round(w_b, 4)},
    }

    # Stability verdict: both halves must independently want w > 1.0 (the
    # boundary this weight is currently clipped at) for extrapolation to
    # be justified at all -- one half alone (the original fit) is not
    # enough, that is exactly the number already shipped-and-capped.
    both_above_one = w_a > 1.0 and w_b > 1.0
    print(f"\n  both halves independently want w > 1.0: {both_above_one}")

    if not both_above_one:
        print("\n  VERDICT: NOT STABLE. The 1.14 fit-half number does not replicate on the")
        print("  independent half -- extrapolating past w=1.0 would be shipping an")
        print("  unvalidated correction. Cap stays at 1.0. Nothing to fix.")
        result["verdict"] = "not stable -- cap stays at 1.0"
        print("\nRESULT block:")
        print(json.dumps(result, indent=2))
        return 0

    # Stable: both halves agree the true optimum exceeds 1.0. Ship the
    # MORE CONSERVATIVE of the two (the minimum), not their average and
    # not the larger one -- deliberately biased toward under-correcting
    # rather than over-correcting, since neither half's number is a fresh
    # out-of-sample read at this point (both were used to make this
    # decision).
    chosen_w = min(w_a, w_b)
    print(f"\n  VERDICT: STABLE. Both halves want w > 1.0. Shipping the MORE CONSERVATIVE")
    print(f"  (minimum) of the two: w = {chosen_w:.4f}")

    # Evaluate at the chosen weight on BOTH halves combined, and disclose
    # plainly that this is NOT a fresh out-of-sample number (the weight
    # was chosen using both halves' own optimum).
    all_normal = normal_a + normal_b
    all_lognormal = lognormal_a + lognormal_b
    all_outcomes = outcomes_a + outcomes_b

    brier_at_1 = brier(blend_probs(all_normal, all_lognormal, 1.0), all_outcomes)
    brier_at_chosen = brier(blend_probs(all_normal, all_lognormal, chosen_w), all_outcomes)
    print(f"\n  Brier at w=1.0 (current shipped cap), both halves combined: {brier_at_1}")
    print(f"  Brier at w={chosen_w:.4f} (extrapolated), both halves combined: {brier_at_chosen}")
    print(f"  improvement: {round(brier_at_1 - brier_at_chosen, 6):+.6f}")
    print("\n  DISCLOSED: this comparison is evaluated on the SAME data that chose the")
    print("  weight (both halves), not a fresh out-of-sample read -- only two")
    print("  independent splits exist. Treat as evidence the direction is right, not")
    print("  as a powered out-of-sample verdict the way the original blend fix had.")

    result["verdict"] = "stable"
    result["chosen_weight"] = round(chosen_w, 4)
    result["brier_at_w1_both_halves"] = brier_at_1
    result["brier_at_chosen_w_both_halves"] = brier_at_chosen
    result["improvement_both_halves_not_oos"] = round(brier_at_1 - brier_at_chosen, 6)

    print("\nRESULT block:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
