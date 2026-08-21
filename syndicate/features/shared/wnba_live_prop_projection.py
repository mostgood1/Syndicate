"""A live per-player stat projection: what is known, plus what is left to play.

PHASE 2 of live WNBA props. Phase 1 (`scripts/capture_wnba_live_player_box.py`)
persists the live per-player lines; this turns one of those lines into a
projected final. It computes NO probability and prices NO edge -- see the last
section for why that is a refusal rather than an omission.

THE SHAPE IS `#475`'s, DELIBERATELY, NOT A SECOND CONVENTION. That entry fixed
the live TOTAL projection with the rule this file follows exactly: points
already scored are known EXACTLY, so only the REMAINING minutes need estimating,
and that estimate blends the live observed rate toward the pregame projected
rate by how much has actually been played. Reusing the shape matters more than
the arithmetic -- WNBA already has two live transforms sharing one time
convention on purpose (`#475`'s "one live time-decay convention for this sport,
not two that can drift apart"), and a third that invented its own would be the
drift that rule exists to prevent.

    projected = current + remaining_minutes * blended_rate
    blended_rate = (1 - w) * pregame_rate + w * live_rate
    w = minutes_played / pregame_minutes, clamped to [0, 1]

At tip-off `w = 0` and the projection collapses to the pregame number exactly;
at the final buzzer `remaining_minutes = 0` and it collapses to the actual stat.
Both are checked in the tests, because a projection that does not reduce to its
own endpoints is wrong somewhere in the middle too.

**IT REFUSES WITHOUT A PREGAME ANCHOR, AND THAT IS THE WHOLE GUARD.** A
live-rate-only remainder is precisely the naive extrapolation `#475` measured
and killed: 12 points two minutes in projects a 240-point final off a 5% floor,
"a 75-point error against a 165 line, published as a real number the over/under
probability was then derived from". A player with 6 points in 9 minutes is on a
26-point pace that nobody should publish as a projection at 09:00 of the second
quarter. Absent an anchor this returns None WITH A REASON rather than a number.

**MINUTES REMAINING ARE CAPPED BY THE GAME, not just by the player's own
projection.** A starter projected for 32 minutes who has played 8 cannot play 24
more when 10 remain on the clock. Without the cap a blowout or a late-game
capture inflates every projection at exactly the moment the market is thinnest.

WHY THERE IS NO PROBABILITY HERE. Pricing a prop edge needs an interval, and
nobody has measured this estimator's error -- there is no WNBA live-prop
equivalent of `#481`'s 0.054 held-out calibration gap. `live_gameline_join`
refuses a moneyline whose edge does not clear its estimator's own noise, and
`analytic_estimator_never_backtested_for_this_market` exists because the live
TOTALS transform was never graded either. A projection may be PUBLISHED
honestly; an edge may not be PRICED off it until it is graded. Producing a
probability here would route around both refusals at once.
"""

from __future__ import annotations

from typing import Any

# Why a projection could not be produced. Named rather than boolean: a blank
# beside a live player is otherwise indistinguishable from a player who has not
# come off the bench, and those need different fixes.
REASON_NO_LIVE_LINE = "no_live_stat_or_minutes_for_this_player"
REASON_NO_PREGAME_ANCHOR = "no_pregame_projection_to_anchor_the_remainder"
REASON_NO_PROJECTED_MINUTES = "pregame_projection_carries_no_expected_minutes"


def _number(value: Any) -> float | None:
    """Floats from ESPN's mixed vocabulary. `mp` arrives as a STRING ("9"), and
    a bare `float()` on a `"12:34"` clock-style value would raise rather than
    decline -- so parse defensively and return None instead of guessing."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; never a stat value
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        if ":" in text:
            # "MM:SS" minutes. Some feeds use it for `mp`; take it as minutes.
            minutes, _, seconds = text.partition(":")
            return float(int(minutes)) + (float(int(seconds)) / 60.0)
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN/inf
        return None
    return number


def project_live_player_stat(
    *,
    current_stat: Any,
    minutes_played: Any,
    pregame_stat: Any,
    pregame_minutes: Any,
    game_minutes_remaining: Any = None,
) -> dict[str, Any]:
    """Project one player's final value for one stat.

    Always returns a dict carrying `projected` and `unavailable_reason`, never a
    bare None -- an absent verdict is how "refused" silently becomes "not
    considered", the same contract `price_moneyline` keeps.
    """
    out: dict[str, Any] = {
        "projected": None,
        "current": None,
        "minutes_played": None,
        "minutes_remaining": None,
        "blend_weight": None,
        "basis": None,
        "unavailable_reason": None,
    }

    current = _number(current_stat)
    played = _number(minutes_played)
    if current is None or played is None or played < 0:
        out["unavailable_reason"] = REASON_NO_LIVE_LINE
        return out
    out["current"] = current
    out["minutes_played"] = played

    anchor_stat = _number(pregame_stat)
    if anchor_stat is None:
        # THE GUARD. Not a fallback to the live rate -- see the module
        # docstring: that is `#475`'s 240-point total.
        out["unavailable_reason"] = REASON_NO_PREGAME_ANCHOR
        return out
    anchor_minutes = _number(pregame_minutes)
    if anchor_minutes is None or anchor_minutes <= 0:
        # An anchor with no minutes cannot supply a RATE, and a rate is the only
        # thing the remainder can be built from. Distinct reason: the projection
        # exists, its denominator does not.
        out["unavailable_reason"] = REASON_NO_PROJECTED_MINUTES
        return out

    pregame_rate = anchor_stat / anchor_minutes
    live_rate = (current / played) if played > 0 else pregame_rate
    weight = max(0.0, min(1.0, played / anchor_minutes))
    blended_rate = ((1.0 - weight) * pregame_rate) + (weight * live_rate)

    remaining = max(0.0, anchor_minutes - played)
    clock_left = _number(game_minutes_remaining)
    if clock_left is not None:
        # A player cannot play more minutes than the game has left.
        remaining = min(remaining, max(0.0, clock_left))

    out["minutes_remaining"] = round(remaining, 3)
    out["blend_weight"] = round(weight, 4)
    out["basis"] = "live_rate_blended_toward_pregame"
    out["projected"] = round(current + (remaining * blended_rate), 3)
    return out
