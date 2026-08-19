"""Is `ANYTIME_TD_SHRINKAGE_K = 12.0` (selected by grid search on
2022-2023, reported on 2024-2025 by `calibrate_nfl_anytime_td_
shrinkage.py`) a real, stable property of the market, or a fragile point
estimate from one particular split? (`nfl-anytime-td-shrinkage-stability`
lane, follow-up to `#471`.)

WHY THIS CHECK, AND WHY IT ISN'T A CLOSED FORM THIS TIME. The blend-
weight family (`passing_attempts`, `rushing_yards`, etc.) had a
closed-form Brier-minimizing weight because Brier is a QUADRATIC function
of a linear blend of two FIXED probabilities. The shrinkage estimator is
different: `shrunk_mean(k) = (n*raw + k*prior) / (n+k)` has `k` in the
DENOMINATOR, so Brier as a function of `k` is a sum of RATIONAL (not
quadratic) terms, and the `max(0, min(1, ...))` clamp adds a kink. No
closed form -- `calibrate_nfl_anytime_td_shrinkage.py` already handles
this correctly with a grid search, so this script reuses that exact
method (`brier_for_k` over the same candidate list) rather than inventing
a different one, and simply runs it INDEPENDENTLY on each half instead of
only the original fit-half-then-score-half direction.

Two genuinely independent multi-season samples selecting a similar `k` is
real signal that the constant is well-pinned-down. One selecting 12 and
the other selecting something wildly different (order-of-magnitude off,
or a flat curve where many values look equally good) means the "12" was
this particular split's own noise -- exactly what happened to
`passing_attempts`' blend weight.

Usage:
  py -3 scripts/check_anytime_td_shrinkage_k_stability.py
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

from calibrate_nfl_anytime_td_shrinkage import brier_for_k
from calibrate_nfl_anytime_td_shrinkage import collect_anytime_td_substrate
from syndicate.features.nfl.player_stats import ANYTIME_TD_SHRINKAGE_K

HALF_A_SEASONS = [2022, 2023]
HALF_B_SEASONS = [2024, 2025]
CANDIDATES = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 30.0]
RATIO_THRESHOLD = 2.0  # same threshold the blend-weight checks used, pre-registered before running


def sweep(rows: list[dict[str, Any]]) -> list[tuple[float, float, int]]:
    return [(k, *brier_for_k(rows, k)) for k in CANDIDATES]


def main() -> int:
    print(f"Shipped ANYTIME_TD_SHRINKAGE_K = {ANYTIME_TD_SHRINKAGE_K}")
    print(f"Checking stability across two independent halves, candidates: {CANDIDATES}")

    rows_a = collect_anytime_td_substrate(HALF_A_SEASONS)
    rows_b = collect_anytime_td_substrate(HALF_B_SEASONS)
    print(f"\nhalf A ({HALF_A_SEASONS}): n={len(rows_a)}")
    print(f"half B ({HALF_B_SEASONS}): n={len(rows_b)}")

    sweep_a = sweep(rows_a)
    sweep_b = sweep(rows_b)

    best_a = min(sweep_a, key=lambda row: row[1])
    best_b = min(sweep_b, key=lambda row: row[1])

    print(f"\n  {'k':>6s} {'half A Brier':>13s} {'half B Brier':>13s}")
    for (k, brier_a, _n_a), (_k2, brier_b, _n_b) in zip(sweep_a, sweep_b):
        marker_a = " <-- best A" if k == best_a[0] else ""
        marker_b = " <-- best B" if k == best_b[0] else ""
        print(f"  {k:>6.1f} {brier_a:>13.6f} {brier_b:>13.6f}{marker_a}{marker_b}")

    print(f"\n  half A best k = {best_a[0]} (Brier {best_a[1]})")
    print(f"  half B best k = {best_b[0]} (Brier {best_b[1]})")

    # How FLAT is each half's curve near its own minimum? A flat curve
    # means many k values are nearly indistinguishable, so the single
    # argmin is itself a fragile read even before comparing halves --
    # report the k range within 1% relative Brier of each half's own best,
    # so a reader can see "sharp minimum" vs "wide plateau" directly.
    def near_best_range(sweep_result, best_brier):
        near = [k for k, b, _n in sweep_result if b <= best_brier * 1.01]
        return (min(near), max(near))

    range_a = near_best_range(sweep_a, best_a[1])
    range_b = near_best_range(sweep_b, best_b[1])
    print(f"\n  half A: k values within 1% of its own best Brier: {range_a}")
    print(f"  half B: k values within 1% of its own best Brier: {range_b}")

    # No "same sign" check here (unlike the blend-weight family): every
    # candidate k is >= 0 by construction, so sign disagreement cannot
    # occur. Stability is purely a ratio question, with k=0 handled as a
    # special case below (a ratio against zero is undefined).
    if best_a[0] == 0 or best_b[0] == 0:
        ratio = None
        stable = best_a[0] == best_b[0] == 0
    else:
        ratio = max(best_a[0], best_b[0]) / min(best_a[0], best_b[0])
        stable = ratio <= RATIO_THRESHOLD
    print(f"\n  ratio: {f'{ratio:.2f}x' if ratio is not None else 'n/a (one half selected k=0)'}")
    print(f"  stable (ratio<={RATIO_THRESHOLD}x): {stable}")

    if stable:
        print(f"\n  VERDICT: STABLE. Shipped k={ANYTIME_TD_SHRINKAGE_K} is well-supported by both")
        print(f"  independent halves ({best_a[0]} and {best_b[0]}) -- no change needed.")
        recommendation = "no change -- shipped k is well-supported"
    else:
        conservative = min(best_a[0], best_b[0])
        print(f"\n  VERDICT: UNSTABLE. The two halves' argmins disagree by more than {RATIO_THRESHOLD}x.")
        print(f"  Conservative fallback (the smaller of the two): k={conservative}")
        recommendation = (
            f"shipped k={ANYTIME_TD_SHRINKAGE_K} vs conservative estimate {conservative} -- "
            + ("shipped value already at or below the conservative estimate, no change needed"
               if ANYTIME_TD_SHRINKAGE_K <= conservative
               else "shipped value exceeds the conservative estimate, consider lowering after a direct Brier check")
        )
        print(f"  {recommendation}")

    result: dict[str, Any] = {
        "shipped_k": ANYTIME_TD_SHRINKAGE_K,
        "half_a": {"seasons": HALF_A_SEASONS, "n": len(rows_a), "best_k": best_a[0], "best_brier": best_a[1],
                    "k_within_1pct_of_best": range_a},
        "half_b": {"seasons": HALF_B_SEASONS, "n": len(rows_b), "best_k": best_b[0], "best_brier": best_b[1],
                    "k_within_1pct_of_best": range_b},
        "ratio": round(ratio, 4) if ratio is not None else None,
        "stable": stable,
        "recommendation": recommendation,
        "verdict": "stable" if stable else "unstable",
    }

    print("\nRESULT block:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
