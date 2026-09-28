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

# (low, high) minutes remaining -> measured residual sd and observed p90 |error|,
# ONE TABLE PER MARKET. THESE ARE MEASUREMENTS. Changing one without re-running the
# grader makes the interval a guess wearing a measurement's clothes.
#
# PROVENANCE `[2026-09-28, lane live-props-model-probability]`:
# `scripts/grade_wnba_live_prop_projection.py --stat <market>` driven over every
# WNBA game 2026-07-17..09-27 that had a sim anchor -- 48 dates, 140 games
# (rebounds 139, assists 137: a game is graded for a stat only if its replay
# reproduces the official box EXACTLY for points AND that stat). Samples: points
# 11,910, rebounds 8,286, assists 5,138, threes 2,194. OUT OF SAMPLE: tables fit on
# 07-17..08-31 cover 91.5-91.8% of September finals inside their 90% band, all four.
#
# WHY PER MARKET: until this change rebounds/assists/threes were priced on the
# POINTS table (the only one measured, n=796 over 5 slates), which is 2-3x too wide
# for them -- its 90% band covered 99.1% / 99.9% / 100% of their finals, squashing
# every probability toward 0.5 and inventing edges on far lines. The same regrade
# showed the old points table itself too NARROW at this sample (86.8% coverage), so
# points is refreshed from the same run.
#
# NO BIAS CORRECTION, as before (choice 2 in the docstring), though rebounds
# measured a consistent early OVER-projection (+1.2 to +1.9 above 20 min left).
# Recorded, not applied: a bias term is a change to the PROJECTION, not to its
# interval, and it would need its own out-of-sample test.
_RESIDUAL_BUCKETS_BY_MARKET: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "points": (
        (30.0, float("inf"), 7.41, 12.39),
        (20.0, 30.0, 6.64, 10.82),
        (10.0, 20.0, 5.54, 8.90),
        (5.0, 10.0, 4.44, 6.78),
        (0.0, 5.0, 3.28, 6.00),
    ),
    "rebounds": (
        (30.0, float("inf"), 3.02, 5.23),
        (20.0, 30.0, 2.90, 4.73),
        (10.0, 20.0, 2.46, 4.04),
        (5.0, 10.0, 2.04, 3.21),
        (0.0, 5.0, 1.45, 2.91),
    ),
    "assists": (
        (30.0, float("inf"), 2.28, 3.67),
        (20.0, 30.0, 2.30, 3.63),
        (10.0, 20.0, 1.87, 2.96),
        (5.0, 10.0, 1.41, 2.15),
        (0.0, 5.0, 1.03, 2.00),
    ),
    "threes": (
        (30.0, float("inf"), 1.58, 2.81),
        (20.0, 30.0, 1.37, 2.33),
        (10.0, 20.0, 1.14, 1.96),
        (5.0, 10.0, 0.84, 1.37),
        (0.0, 5.0, 0.66, 1.00),
    ),
}
# Kept for readers of the old name: the points table.
_RESIDUAL_BUCKETS = _RESIDUAL_BUCKETS_BY_MARKET["points"]
MEASURED_MARKETS = frozenset(_RESIDUAL_BUCKETS_BY_MARKET)

REASON_NO_PROJECTION = "no_live_projection_to_price"
REASON_NO_MINUTES_REMAINING = "minutes_remaining_unknown_so_no_measured_interval"
REASON_NO_LINE = "no_line_to_price_against"
REASON_NO_MEASURED_MARKET = "no_measured_residual_for_this_market"
REASON_NO_CURRENT = "count_market_needs_the_banked_stat_to_price_the_remainder"

# PLAYER-SCALED REMAINDER FOR THE COUNT MARKETS `[2026-09-28, lane
# live-props-model-probability, user: "build the player-scaled spread model"]`.
#
# WHY. One sigma per time bucket gives a 2-rebound bench player and a 10-rebound
# center the same spread. Interval coverage hid it (91.5-91.8% out of sample); LINE-LEVEL
# calibration -- predicted vs observed P(final >= line) over the ladder the lens
# publishes, CLOCK-sampled replays -- did not: overs overstated by up to 18.5 pp
# (rebounds), 10 (assists), 18.7 (threes) in-season. Empirical CDFs and a plain
# Poisson remainder fixed neither.
#
# THE MODEL. What is still to come, R = final - banked, is a count:
#     R ~ NegBin(mean m, dispersion r),  m = c_b * (projected - banked),  Var = m + m^2/r
# so the spread scales with the player's own expected remainder, the distribution is
# skewed like counts are, and nothing is priced below what is already banked. `c_b`
# (per minutes-remaining bucket) re-scales the SHIPPED projection's remainder -- it is
# how the measured bias enters PRICING without changing the projection itself; `r` is
# the dispersion (per bucket for rebounds/assists, one value for threes).
#
# PROVENANCE. Maximum likelihood over clock-sampled replays (`scripts/
# grade_wnba_live_prop_projection.py --sampling clock`), 2026-07-17..08-31; variant
# chosen on August with a July fit; then ONE test on September (playoffs, held out of
# everything). Worst line-level gap, rotation players, September: rebounds 16.7 -> 3.0 pp,
# assists 11.1 -> 6.1, threes 26.5 -> 5.9 (normal -> this). Brier skill up on all three.
# THESE ARE FITTED VALUES: change them only by re-running that fit.
#
# REBOUNDS AND ASSISTS PRICE ON A REMAINING-MINUTES MODEL `[2026-09-28, user: "improve the
# minutes projection for assists and threes"]`. Their mean is c_b x rate x E[remaining
# minutes], with E[remaining minutes] from `expected_remaining_minutes` below rather than
# the projection's `min(pregame - played, clock left)`. Remaining-minutes error (MAE),
# held-out September: rule 4.89 -> model 3.44 min (rotation 4.60 -> 3.55); August 4.55 ->
# 3.09. The fitted c_b fell to ~0.9-1.3 in EVERY bucket (the last-5-minutes c had been 2.7-2.8):
# the minutes rule was most of what c_b was patching. Buckets key on the MODEL's minutes.
# September line-level calibration, rotation, worst gap: assists 6.3 -> 3.5 pp (skill
# +0.365 -> +0.387); rebounds 3.0 -> 3.1 (all players 3.0 -> 2.2; skill +0.425 -> +0.448).
# THREES STAYS on the projection's remainder: with the model's minutes, hot-starting bench
# shooters (~15 pregame minutes, <1 expected three) were over-priced by up to 22 pp -- the
# live RATE after a few minutes is the problem there, and the old minutes cap had hidden it.
#
# (low, high, c, r) per remaining-minutes bucket.
MINUTES_MODEL_MARKETS = frozenset({"rebounds", "assists"})
_NEGBIN_REMAINDER: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "rebounds": (
        (30.0, float("inf"), 0.78, 7.0),
        (20.0, 30.0, 0.82, 7.0),
        (10.0, 20.0, 0.88, 4.0),
        (5.0, 10.0, 0.88, 2.0),
        (0.0, 5.0, 0.90, 1.0),
    ),
    "assists": (
        (30.0, float("inf"), 1.32, 3.0),
        (20.0, 30.0, 1.16, 3.0),
        (10.0, 20.0, 1.08, 3.0),
        (5.0, 10.0, 0.96, 3.0),
        (0.0, 5.0, 0.86, 3.0),
    ),
    "threes": (
        (30.0, float("inf"), 0.96, 1.5),
        (20.0, 30.0, 0.96, 1.5),
        (10.0, 20.0, 0.94, 1.5),
        (5.0, 10.0, 1.22, 1.5),
        (0.0, 5.0, 2.22, 1.5),
    ),
}
COUNT_MARKETS = frozenset(_NEGBIN_REMAINDER)

# E[remaining minutes] = clock_left x clip(x . beta, 0, 1), weighted least squares on the share
# of the remaining regulation clock a player actually played. Features, in order:
#   1, pregame share (pregame_minutes/40), live share (played/elapsed), lateness x each share,
#   the rule's own share (max(pregame - played, 0)/clock_left), blowout x pregame share, blowout
#   where blowout = clip(|own margin| - 8, 0, 20)/20 x lateness.
# Fit 2026-07-17..08-31 clock-sampled replays (`scripts/fit_wnba_live_count_remainder.py`).
# Fouls and an on-court flag were tested and added ~1% -- not worth a capture change.
_MINUTES_BETA: tuple[float, ...] = (0.0938, 0.6498, 0.1814, -0.4042, 0.5824, -0.0475, -1.6356, 0.6119)
_REGULATION_MINUTES = 40.0


def expected_remaining_minutes(
    pregame_minutes: Any, minutes_played: Any, game_minutes_remaining: Any, team_margin: Any = None
) -> float | None:
    """E[minutes this player still plays], or None when the state is unknown.

    `team_margin` is the player's OWN team's lead (negative when trailing). Unknown
    margin reads as 0 -- no blowout adjustment -- which is the state most samples had.
    """
    pre, played, clock = _as_number(pregame_minutes), _as_number(minutes_played), _as_number(game_minutes_remaining)
    if pre is None or pre <= 0.0 or played is None or played < 0.0 or clock is None or clock < 0.0:
        return None
    clock = min(clock, _REGULATION_MINUTES)
    if clock <= 0.0:
        return 0.0
    elapsed = _REGULATION_MINUTES - clock
    s_pre = min(1.0, pre / _REGULATION_MINUTES)
    s_live = min(1.0, played / elapsed) if elapsed > 0.0 else s_pre
    late = min(1.0, elapsed / _REGULATION_MINUTES)
    margin = abs(_as_number(team_margin) or 0.0)
    blowout = min(max(margin - 8.0, 0.0), 20.0) / 20.0 * late
    s_rule = min(1.0, max(pre - played, 0.0) / clock)
    x = (1.0, s_pre, s_live, late * s_pre, late * s_live, s_rule, blowout * s_pre, blowout)
    share = sum(b * v for b, v in zip(_MINUTES_BETA, x))
    return clock * max(0.0, min(1.0, share))


def _as_number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def negbin_remainder(projected: Any, current: Any, minutes_remaining: Any, market: str,
                     *, rate: Any = None, expected_minutes: Any = None) -> dict[str, float] | None:
    """`{mean, dispersion, sd, center}` of the remaining-production NegBin, or None.

    None for a non-count market, an unknown state, or minutes outside the fitted range.
    `center` is banked + mean: where the priced distribution actually sits. A
    `MINUTES_MODEL_MARKETS` market needs `rate` and `expected_minutes` and refuses
    without them -- falling back to the projection's minutes would price it on the
    table fitted for the OTHER minutes estimate.
    """
    table = _NEGBIN_REMAINDER.get(str(market or ""))
    proj, cur = _as_number(projected), _as_number(current)
    if table is None or cur is None:
        return None
    if str(market) in MINUTES_MODEL_MARKETS:
        per_min, rem = _as_number(rate), _as_number(expected_minutes)
        if per_min is None or rem is None or rem < 0.0:
            return None
        base = max(per_min, 0.0) * rem
    else:
        rem = _as_number(minutes_remaining)
        if proj is None or rem is None or rem < 0.0:
            return None
        base = max(proj - cur, 0.0)
    for low, high, c, r in table:
        if low <= rem < high:
            mean = c * base
            sd = math.sqrt(mean + mean * mean / r) if mean > 0.0 else 0.0
            return {"mean": mean, "dispersion": r, "sd": sd, "center": cur + mean}
    return None


def _negbin_sf(k: int, mean: float, r: float) -> float:
    """P(R >= k) for R ~ NegBin(mean, dispersion r)."""
    if k <= 0:
        return 1.0
    if mean <= 0.0:
        return 0.0
    p = r / (r + mean)
    pmf = p ** r
    cdf = pmf
    for i in range(1, k):
        pmf *= (i - 1 + r) / i * (1.0 - p)
        cdf += pmf
    return max(0.0, min(1.0, 1.0 - cdf))


def grid_center_and_sd(projected: Any, current: Any, minutes_remaining: Any, market: str,
                       *, rate: Any = None, expected_minutes: Any = None) -> tuple[float, float] | None:
    """Where the priced distribution sits and how wide, for sizing a line grid."""
    if str(market or "") in COUNT_MARKETS:
        nb = negbin_remainder(projected, current, minutes_remaining, market,
                              rate=rate, expected_minutes=expected_minutes)
        return None if nb is None else (nb["center"], nb["sd"])
    proj = _as_number(projected)
    sigma = residual_sigma(minutes_remaining, market)
    if proj is None or sigma is None or sigma <= 0.0:
        return None
    return proj, sigma


def residual_sigma(minutes_remaining: Any, market: str = "points") -> float | None:
    """The measured interval for `market` at this point of the game, or None.

    None outside the measured minutes range AND for a market with no measured
    table -- an unmeasured market must refuse, never borrow another's interval.
    """
    table = _RESIDUAL_BUCKETS_BY_MARKET.get(str(market or ""))
    if table is None:
        return None
    try:
        remaining = float(minutes_remaining)
    except (TypeError, ValueError):
        return None
    if remaining < 0.0 or remaining != remaining:  # negative or NaN
        return None
    for low, high, sd, p90 in table:
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
    market: str = "points",
    current: Any = None,
    rate: Any = None,
    expected_minutes: Any = None,
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

    if str(market or "") not in MEASURED_MARKETS:
        out["unavailable_reason"] = REASON_NO_MEASURED_MARKET
        return out
    if str(market) in COUNT_MARKETS:
        # A COUNT market is priced on the player-scaled remainder, never the normal.
        # Without the banked stat there is no remainder to price, so it refuses --
        # falling back to the normal would restore the miscalibration this replaced.
        if _as_number(current) is None:
            out["unavailable_reason"] = REASON_NO_CURRENT
            return out
        nb = negbin_remainder(projection, current, minutes_remaining, market,
                              rate=rate, expected_minutes=expected_minutes)
        if nb is None:
            out["unavailable_reason"] = REASON_NO_MINUTES_REMAINING
            return out
        out["residual_sigma"] = round(nb["sd"], 4)
        out["basis"] = "measured_negbin_remainder"
        needed = math.ceil(target - float(current))
        out["prob_over"] = round(_negbin_sf(needed, nb["mean"], nb["dispersion"]), 6)
        return out
    sigma = residual_sigma(minutes_remaining, market)
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
