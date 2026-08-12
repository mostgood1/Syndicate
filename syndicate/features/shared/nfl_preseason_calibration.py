"""Measured calibration for `nfl_preseason_v1` (`#367`).

BACKTESTED, NOT ASSUMED. 146 completed preseason games, 2023-2025, joining
`smartsim2_preseason_projections_<season>_wk<week>.csv` to the actual scores in
`schedule_preseason_<season>.csv` by `game_id`. Same `profile_name`
(`nfl_preseason_v1`) and same `rating_source` in all four seasons including
2026, so the historical error transfers.

TWO SEPARATE PROBLEMS, and the second is the serious one.

1. LEVEL BIAS on totals -- fixable, and fixed here.

       mean error (projection - actual)   +5.018
       median error                       +5.623
       share projecting HIGH               71.9%
       MAE  raw 9.62  ->  8.26 after the offset

   Preseason starters play a fraction of the snaps, so real totals land far
   below regular-season levels; the model emits regular-season-shaped means.
   On the live 2026 week-2 slate this rendered as 16 of 16 totals projecting
   OVER the market by a mean of +6.47 -- sixteen green edges that were entirely
   model error.

2. NEAR-ZERO SKILL -- NOT fixable by an offset, and disclosed rather than hidden.

       totals   corr(projection, actual) = +0.269
                projection stdev 1.77  vs  actual stdev 10.87
                MAE after offset 8.26  vs  8.48 for ALWAYS predicting 38.5
       margins  corr(projection, actual) = -0.047
                MAE 10.54 raw, 10.48 offset

   The total model is very slightly better than a constant. The MARGIN model is
   indistinguishable from noise, and `home_win_rate` is derived from it -- so
   preseason moneyline probabilities carry no measured information either. An
   offset cannot create skill that is not there.

WHY THE CORRECTION LIVES HERE AND NOT IN THE GENERATOR. The bias belongs to the
model and the right long-term fix is to rebuild `nfl_preseason_v1` against
preseason snap counts. That means regenerating artifacts offline; this makes the
board honest today without pretending the model was fixed. `calibrated: True` and
the skill block travel with every projection so nobody downstream mistakes a
corrected number for a good one.
"""

from __future__ import annotations

from typing import Any

# Median, not mean: 146 games with a 10.5-point error stdev, so the median is
# the more robust centre and it scored marginally better on MAE (8.23 vs 8.26).
TOTAL_BIAS_POINTS: float = 5.62

PRESEASON_PROFILES: frozenset[str] = frozenset({"nfl_preseason_v1"})

# Everything below is measured on the 146-game backtest described above.
MEASURED_SKILL: dict[str, Any] = {
    "sample_games": 146,
    "seasons": "2023-2025",
    "totals": {
        "correlation": 0.269,
        "mae_raw": 9.62,
        "mae_calibrated": 8.26,
        "mae_constant_baseline": 8.48,
        "verdict": "barely better than predicting the historical mean",
    },
    "margins": {
        "correlation": -0.047,
        "mae_raw": 10.54,
        "verdict": "no measured skill -- moneyline probabilities are uninformative",
    },
}


def is_preseason_profile(profile: Any) -> bool:
    return str(profile or "").strip().lower() in PRESEASON_PROFILES


def calibrated_total(total_mean: float | None, profile: Any) -> float | None:
    """Subtract the measured level bias for preseason profiles only.

    Regular-season projections are NOT touched: this bias was measured on
    preseason games and applying it elsewhere would be inventing a correction
    for a model that was never tested for one.
    """
    if total_mean is None or not is_preseason_profile(profile):
        return total_mean
    return round(float(total_mean) - TOTAL_BIAS_POINTS, 3)


def skill_note(profile: Any, market: str) -> dict[str, Any] | None:
    """What the backtest says this market's projection is actually worth."""
    if not is_preseason_profile(profile):
        return None
    key = "totals" if str(market).strip().lower() == "totals" else "margins"
    block = MEASURED_SKILL[key]
    return {
        "sample_games": MEASURED_SKILL["sample_games"],
        "seasons": MEASURED_SKILL["seasons"],
        "correlation": block["correlation"],
        "verdict": block["verdict"],
    }
