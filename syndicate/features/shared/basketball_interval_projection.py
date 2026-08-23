"""Project the FINAL score of an interval from a probe INSIDE it.

**THIS IS THE QUESTION A QUARTER BET ACTUALLY ASKS**, and it is not the one
`basketball_projection_rows` answers. That module uses FIXED horizons -- "what
happens in the next 600s" -- which at any probe after tip spills across the
period boundary. A `totals_q4` market asks for the FINAL number of THIS quarter,
from wherever the clock currently is. The horizon therefore SHRINKS as the
interval runs, and the two questions coincide only at t=0.

## WHY THIS SHOULD WORK WHERE MOMENTUM DID NOT

Momentum was measured on 282 games and returned nothing: 120 correlations, the
largest 0.0613 against a pre-registered noise floor of 0.082. It was asked to
PREDICT a swing.

This is largely ARITHMETIC. Points remaining in a quarter are bounded by the
possessions remaining, which is bounded by the clock. Six minutes into a
ten-minute quarter the answer is mostly already determined, and the residual
uncertainty shrinks toward zero as the buzzer approaches.

So the honest framing is not "find alpha". It is: **how accurate is the
arithmetic, and at what point in an interval does it become accurate enough that
a stale line is beatable.** The edge is the market's, not the model's.

## WHAT IS DELIBERATELY NOT CLAIMED

Nothing here is fitted and nothing is compared to a market price. This produces
a projection and its measured error; whether that error is small enough to beat
a live line is a separate question requiring the line, and `model_engine_
standard.md` binds before any of it reaches pricing.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from syndicate.features.shared.basketball_momentum import _LEAGUE_PERIODS


def period_bounds(league_code: str, clock_seconds: float) -> tuple[int, float, float]:
    """(period number, seconds elapsed INTO it, seconds LEFT in it).

    Overtime is folded into the last regulation period rather than modelled: OT
    is rare, its length differs, and a wrong period index is worse than a
    coarse one. A caller wanting OT priced separately must say so.
    """
    rules = _LEAGUE_PERIODS.get(str(league_code or "").strip().lower())
    if rules is None:
        rules = _LEAGUE_PERIODS["wnba"]
    length = float(rules["quarter_minutes"]) * 60.0
    periods = int(float(rules["regulation_periods"]))

    index = int(clock_seconds // length) + 1
    if index > periods:                      # overtime
        index = periods
        into = clock_seconds - (periods - 1) * length
        return (index, into, 0.0)
    into = clock_seconds - (index - 1) * length
    return (index, into, length - into)


def _sum_between(rows: Sequence[Mapping[str, Any]], lo: float, hi: float) -> tuple[float, float]:
    """(signed margin, unsigned total) for rows in `(lo, hi]`."""
    margin = total = 0.0
    for row in rows:
        try:
            t = float(row["clock_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if t <= lo or t > hi:
            continue
        weight = float(row.get("weight") or 0.0)
        margin += float(row.get("sign") or 0.0) * weight
        total += abs(weight)
    return margin, total


def project_interval(
    pressure: Sequence[Mapping[str, Any]],
    scoring: Sequence[Mapping[str, Any]],
    probe: float,
    *,
    league_code: str = "wnba",
) -> dict[str, Any] | None:
    """One row: the state at `probe`, the naive projection, and the truth.

    The projection is deliberately the SIMPLEST defensible thing -- points so
    far in this period, plus remaining possessions times points-per-possession
    to date. It exists to be a BASELINE THAT MUST BE BEATEN, not a proposal. A
    fancier model that cannot beat this is not worth its complexity, and this
    repo has shipped exactly that mistake before.
    """
    if not pressure or not scoring:
        return None
    period, into, left = period_bounds(league_code, probe)
    if left <= 0.0:
        return None                          # at or past the buzzer, nothing to project

    period_start = probe - into
    period_end = period_start + into + left

    margin_so_far, total_so_far = _sum_between(scoring, period_start, probe)
    # Truth: the rest of THIS period only.
    rest_margin, rest_total = _sum_between(scoring, probe, period_end)

    past = [r for r in pressure if float(r["clock_seconds"]) <= probe]
    if not past:
        return None
    possessions = max(float(r.get("possession_index") or 0.0) for r in past)
    game_total = sum(abs(float(r.get("weight") or 0.0)) for r in scoring
                     if float(r["clock_seconds"]) <= probe)

    minutes = max(probe / 60.0, 1e-6)
    pace = possessions / minutes                       # possessions per minute
    ppp = (game_total / possessions) if possessions > 0 else 0.0
    poss_left = pace * (left / 60.0)
    projected_rest_total = poss_left * ppp

    return {
        "period": period,
        "t_seconds": round(probe, 1),
        "state_seconds_into_period": round(into, 1),
        "state_seconds_left_in_period": round(left, 1),
        "state_period_total_so_far": round(total_so_far, 2),
        "state_period_margin_so_far": round(margin_so_far, 2),
        "state_pace_per_min": round(pace, 4),
        "state_points_per_possession": round(ppp, 4),
        "state_possessions_left_est": round(poss_left, 2),
        # THE PROJECTION -- of the rest of the period, and of the period's final.
        "proj_rest_total": round(projected_rest_total, 2),
        "proj_period_total": round(total_so_far + projected_rest_total, 2),
        # THE TRUTH.
        "true_rest_total": round(rest_total, 2),
        "true_period_total": round(total_so_far + rest_total, 2),
        "true_rest_margin": round(rest_margin, 2),
        # The error a bettor actually eats: points on the period's final number.
        "abs_error_period_total": round(abs(projected_rest_total - rest_total), 2),
    }
