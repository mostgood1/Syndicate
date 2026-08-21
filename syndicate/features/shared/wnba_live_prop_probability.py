"""`P(final >= line)` for a live prop, from a MEASURED residual.

PHASE 3(b). Phase 2 projects a player's final stat; this turns that projection
into the probability `build_live_prop_index` keys on. It exists only because the
error was measured -- `scripts/grade_wnba_live_prop_projection.py` replayed ESPN
play-by-play, drove the shipped projection at every scoring play and scored it
against the official final, over n=796 samples on 5 slates, with the replay
reconciling 100% against the official boxscore on every one.

WHAT THE MEASUREMENT SAID, and why the table is bucketed:

    minutes_left      n     mean      sd   p90/sd
         30-99       21    +0.18    6.03     1.71
         20-30      129    +0.42    5.38     1.59
         10-20      220    -0.54    5.30     1.61
          5-10      136    -1.23    3.88     1.56
           0-5      290    -1.69    2.70     1.90
           ALL      796    -0.90    4.39

The spread SHRINKS MONOTONICALLY as the game runs down, 6.03 -> 2.70. A single
sd would be far too wide late and too narrow early, pricing both ends wrongly --
the same dispersion-not-bias shape `#481` found for the win probability, where
aggregate means looked unbiased while the buckets did not.

THREE DELIBERATE CHOICES, each of which could reasonably have gone the other way:

1. **A TAIL-MATCHED SIGMA, never smaller than the measured sd.** `p90/sd` runs
   1.56-1.71 against 1.6449 for a normal, so the bulk is approximately normal
   and the normal CDF is defensible. The `0-5` bucket is the exception at 1.90 --
   heavier tails, where a normal UNDERSTATES how wrong the estimate can be, which
   is the dangerous direction. So each bucket uses `max(sd, p90 / 1.6449)`:
   measured sd, widened where the observed tail is fatter than normal. Only the
   `0-5` bucket is actually widened (2.70 -> 3.12).

2. **NO BIAS CORRECTION, though a bias was measured.** Per-bucket means run from
   +0.42 to -1.69 and change sign; the aggregate is -0.90. Subtracting a term
   that flips sign across buckets at n=796 is fitting noise, and a wrong bias
   correction shifts every probability systematically in one direction -- worse
   than a slightly wide interval. Recorded, not applied. Re-measure at
   `#481` scale (it used 73,878 samples) before revisiting.

3. **IT REFUSES RATHER THAN EXTRAPOLATING PAST THE MEASURED RANGE.** The buckets
   were measured from real games; a projection with unknown minutes remaining,
   or none at all, gets None with a reason. The table is a MEASUREMENT, and a
   measurement does not cover states it never saw.

WHAT THIS DOES NOT DO. It does not open the prop join's `sport != "mlb"` gate --
that is phase 4 and a separate decision. Emitting the field makes WNBA rows
*eligible* to be priced; the join's own `prob_std_err`/`PRICEABLE_SIGMA` refusal
still applies on top, exactly as it does for MLB.
"""

from __future__ import annotations

import math
from typing import Any

# The one-sided z at the 90th percentile. Named rather than inlined: it appears
# in both the table's derivation and its documentation, and a second literal
# would drift from the first.
_Z90 = 1.6449

# (low, high) minutes remaining -> measured residual sd and observed p90 |error|.
# Provenance: grade_wnba_live_prop_projection.py, n=796 over 2026-08-14/15/16/
# 17/19, replay reconciling 100% on every slate. THESE ARE MEASUREMENTS. Changing
# one without re-running that grader makes the interval a guess wearing a
# measurement's clothes.
_RESIDUAL_BUCKETS: tuple[tuple[float, float, float, float], ...] = (
    (30.0, float("inf"), 6.03, 10.29),
    (20.0, 30.0, 5.38, 8.53),
    (10.0, 20.0, 5.30, 8.52),
    (5.0, 10.0, 3.88, 6.05),
    (0.0, 5.0, 2.70, 5.14),
)

REASON_NO_PROJECTION = "no_live_projection_to_price"
REASON_NO_MINUTES_REMAINING = "minutes_remaining_unknown_so_no_measured_interval"
REASON_NO_LINE = "no_line_to_price_against"


def residual_sigma(minutes_remaining: Any) -> float | None:
    """The measured interval at this point of the game, or None outside it."""
    try:
        remaining = float(minutes_remaining)
    except (TypeError, ValueError):
        return None
    if remaining < 0.0 or remaining != remaining:  # negative or NaN
        return None
    for low, high, sd, p90 in _RESIDUAL_BUCKETS:
        if low <= remaining < high:
            # Widened only where the observed tail is fatter than normal.
            return max(sd, p90 / _Z90)
    return None


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def live_prop_prob_over(
    *,
    projected: Any,
    line: Any,
    minutes_remaining: Any,
) -> dict[str, Any]:
    """`P(final >= line)` from the projection and its measured residual.

    Always returns a dict carrying `prob_over` and `unavailable_reason` -- never
    a bare None, so a refusal cannot be mistaken for "not considered".
    """
    out: dict[str, Any] = {
        "prob_over": None,
        "residual_sigma": None,
        "basis": None,
        "unavailable_reason": None,
    }

    try:
        projection = float(projected)
    except (TypeError, ValueError):
        out["unavailable_reason"] = REASON_NO_PROJECTION
        return out
    try:
        target = float(line)
    except (TypeError, ValueError):
        out["unavailable_reason"] = REASON_NO_LINE
        return out

    sigma = residual_sigma(minutes_remaining)
    if sigma is None or sigma <= 0.0:
        # No measured interval for this state. A 0.0 here would read as perfect
        # precision and make every edge priceable -- the substitution this
        # codebase has already paid for once (`PHI @ MIN se=0.0`).
        out["unavailable_reason"] = REASON_NO_MINUTES_REMAINING
        return out

    out["residual_sigma"] = round(sigma, 4)
    out["basis"] = "measured_residual_normal"
    # P(final >= line). A prop line of 17.5 cannot be landed on exactly, so no
    # continuity correction is applied -- the half-point IS the correction.
    out["prob_over"] = round(1.0 - _normal_cdf((target - projection) / sigma), 6)
    return out
