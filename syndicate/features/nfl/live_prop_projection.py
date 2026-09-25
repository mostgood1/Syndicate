"""NFL live prop projections by REMAINING-TIME RESCALE.

PARKED 2026-09-25, UNWIRED, AND NOT THE PLAN. Nothing imports this. It was
written as a fast path to make NFL's props live-aware before Sunday, and the
user's direction is explicitly NOT to chase quick wins but to solve the urgent
in-season issues properly. Keeping it because the CONTRACT work in it is real --
`liveProjection` mandatory, `liveModelProbOver` never fabricated, refusals named
-- and a rest-of-game re-sim will need exactly those shapes. Deleting it would
throw that away; wiring it would ship a uniform-rate assumption that football
violates by design.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

It publishes a live PROJECTION and no live PROBABILITY. `liveProjection` is what
`live_projection_join.build_live_prop_index` requires and treats as the
live-awareness evidence; `liveModelProbOver` is the re-sim's rest-of-game P(over)
(`#414`) and this module cannot compute one, so it emits none. A projection with
no probability shows on the board and is NOT priced -- the same posture WNBA's
live tier already takes, and the same reason: inventing the number that opens the
pricing gate is the single worst substitution available here.

THE GUARD THIS IS SHAPED AROUND. `build_live_prop_index` refuses any row whose
`liveProjection` is null, because on 2026-08-13 63 of 144 snapshot rows carried
`modelProbOver` while `liveProjection`, `modelMean` and `actualSoFar` were all
null -- a PREGAME probability sitting in a live-lens row, which would be marked
`live_aware` and hand `live_edge_policy` exactly the edge it exists to suppress.
So every row here carries a real `liveProjection` derived from the live box, or
it is not emitted at all.

THE MODEL IS NAIVE AND ITS NAIVETY IS THE POINT OF THIS DOCSTRING.

    liveProjection = actualSoFar + pregame_total * remaining_fraction

That assumes production is UNIFORM IN GAME TIME. For football it is not: game
script, blowouts, garbage time and clock-killing all break it, and the error is
not symmetric -- a leading team runs and a trailing team throws. This is a
stop-gap that makes the 95% of NFL's board that is props live-aware at all
(measured 2026-09-25: 76 game markets vs 1431 prop markets on the 09-27 slate),
not a model. It must be replaced by a rest-of-game re-sim, and until it is, no
row it produces may be priced.

WHY SHIP IT ANYWAY: the alternative on the table was nothing for the whole of
this season's remaining slates, and an unpriced live projection is strictly more
information than a pregame number with no live marking at all.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

# A regulation NFL game. Overtime is handled by clamping, not by pretending the
# clock ran past zero -- see `remaining_fraction`.
REGULATION_PERIODS = 4
PERIOD_SECONDS = 15 * 60
REGULATION_SECONDS = REGULATION_PERIODS * PERIOD_SECONDS

LIVE_PROP_SOURCE = "live_rescale"


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _as_int(value: Any) -> Optional[int]:
    number = _as_float(value)
    return int(number) if number is not None else None


def remaining_fraction(
    *,
    period: Any,
    clock_seconds: Any,
    periods: int = REGULATION_PERIODS,
    period_seconds: int = PERIOD_SECONDS,
) -> Optional[float]:
    """Fraction of regulation still to play, in [0, 1], or None if unknowable.

    None is a REFUSAL and callers must treat it as one. Guessing a fraction from
    a missing clock is how a pregame number acquires a live costume.

    OVERTIME CLAMPS TO 0.0 rather than going negative: once regulation is spent
    there is no remaining REGULATION time, and a negative fraction would reduce
    a projection below what has already happened, which is not a smaller
    estimate but a nonsensical one.
    """
    period_index = _as_int(period)
    remaining_in_period = _as_float(clock_seconds)
    if period_index is None or remaining_in_period is None:
        return None
    if period_index < 1 or remaining_in_period < 0:
        return None
    if period_index > periods:
        return 0.0
    periods_left_after_this = max(0, periods - period_index)
    remaining = min(remaining_in_period, float(period_seconds)) + periods_left_after_this * period_seconds
    total = float(periods * period_seconds)
    if total <= 0:
        return None
    return max(0.0, min(1.0, remaining / total))


def rescale(*, pregame_total: Any, actual_so_far: Any, fraction: Any) -> Optional[float]:
    """`actual + pregame_total * fraction`, or None when any input is missing.

    NOT `pregame_total * fraction` alone: the player has already banked
    `actual_so_far`, and a projection that ignores it would fall as the game
    progresses even while the player produced.
    """
    total = _as_float(pregame_total)
    actual = _as_float(actual_so_far)
    frac = _as_float(fraction)
    if total is None or actual is None or frac is None:
        return None
    if total < 0 or actual < 0 or not (0.0 <= frac <= 1.0):
        return None
    return actual + total * frac


def build_live_props(
    *,
    pregame_props: Sequence[Mapping[str, Any]],
    actuals_by_player_market: Mapping[tuple[str, str], float],
    period: Any,
    clock_seconds: Any,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """`(liveProps, refusals_by_reason)` for ONE game.

    Every emitted row carries a real `liveProjection`; a row whose projection
    cannot be computed is REFUSED BY NAME rather than emitted with a null, which
    the index would drop silently and uncountably.

    `liveModelProbOver` is never set. See the module docstring.
    """
    refusals: dict[str, int] = {}

    def refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    fraction = remaining_fraction(period=period, clock_seconds=clock_seconds)
    if fraction is None:
        # ONE refusal for the whole game, named. Counting it per-prop would
        # report hundreds of failures for a single missing clock.
        return [], {"no_clock": 1}

    out: list[dict[str, Any]] = []
    for prop in pregame_props or ():
        if not isinstance(prop, Mapping):
            refuse("row_not_a_mapping")
            continue
        player = str(prop.get("playerName") or prop.get("player") or "").strip()
        market = str(prop.get("market") or "").strip()
        line = _as_float(prop.get("line"))
        if not player or not market or line is None:
            refuse("no_player_market_or_line")
            continue
        pregame_total = _as_float(prop.get("modelMean"))
        if pregame_total is None:
            pregame_total = _as_float(prop.get("projection"))
        if pregame_total is None:
            refuse("no_pregame_projection")
            continue
        actual = actuals_by_player_market.get((player.lower(), market.lower()))
        if actual is None:
            # The player is in the prop book but not in the live box: has not
            # played, or the box does not carry this market. Distinguishable
            # from a broken join because it is counted.
            refuse("no_live_actual")
            continue
        projection = rescale(pregame_total=pregame_total, actual_so_far=actual, fraction=fraction)
        if projection is None:
            refuse("rescale_refused")
            continue
        out.append({
            "playerName": player,
            "market": market,
            "line": line,
            # THE REQUIRED FIELD. `build_live_prop_index` drops any row without
            # it, on purpose.
            "liveProjection": round(projection, 4),
            "actualSoFar": actual,
            "modelMean": round(projection, 4),
            # The PREGAME probability, carried through under its own name so a
            # reader can see it is pregame. Never copied into
            # `liveModelProbOver`.
            "modelProbOver": prop.get("modelProbOver"),
            "selection": prop.get("selection"),
            "liveSource": LIVE_PROP_SOURCE,
            "remainingFraction": round(fraction, 4),
        })
    return out, refusals


def actuals_index(rows: Iterable[Mapping[str, Any]] | None) -> dict[tuple[str, str], float]:
    """`(player_lower, market_lower) -> value` from live box rows.

    Keys are lowercased on BOTH sides here and in `build_live_props`, because a
    case mismatch between the prop book and the box is a silent zero-coverage
    join and this module exists to remove silent zeroes.
    """
    index: dict[tuple[str, str], float] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        player = str(row.get("playerName") or row.get("player") or "").strip().lower()
        market = str(row.get("market") or row.get("stat") or "").strip().lower()
        value = _as_float(row.get("value") if row.get("value") is not None else row.get("actual"))
        if not player or not market or value is None:
            continue
        index[(player, market)] = value
    return index
