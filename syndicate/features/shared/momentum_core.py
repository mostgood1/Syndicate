"""Causal exponential-decay momentum: the math, with no sport in it.

WHAT THIS IS. A momentum series is a signed, time-weighted sum of pressure
events -- one side positive, the other negative -- where each event's
contribution decays exponentially with age. That shape is what FotMob and
AiScore draw, and it is sport-agnostic: only the EVENT TAXONOMY and the
WEIGHTS are sport-specific, and neither lives here.

WHY IT IS A SEPARATE MODULE. `syndicate/features/soccer/features/momentum.py`
had the first implementation. Basketball needs the identical decay and a
completely different taxonomy (`shared/basketball_momentum.py`), and NHL/NFL
will need the same again. Seven copies of an exponential decay is seven places
for a half-life to drift silently, so the math is extracted once.

**SOCCER STILL HAS ITS OWN COPY, DELIBERATELY, AND THAT IS NOT AN OVERSIGHT.**
`soccer/features/momentum.py` is not edited by this lane: the lane holding it
(`soccer-board-mlb-parity`) still owes a production reading of soccer momentum
on a live card, and changing the implementation under an outstanding
measurement is how a measurement stops meaning anything.
`tests/test_momentum_core.py` PINS this module against that one instead, which
is the same guard `game_shape.py:483` uses for `basketball_elapsed_minutes`
against `wnba/cards.py`'s copy, and for the same stated reason. Having soccer
delegate here is follow-up work for when that lane closes.

THE TWO PROPERTIES THAT MAKE ANY OF THIS WORTH COMPUTING:

**1. STRICTLY CAUSAL.** Only events at or before the probe instant contribute.
A momentum value that can see the future makes every lead-vs-lag test pass
trivially, which is the one thing these modules exist to answer honestly.

**2. THE SCORING EVENT IS EXCLUDED BY THE CALLER.** A series that counts the
thing it is meant to predict spikes AT that thing and correlates with it by
construction, while carrying no predictive content whatsoever. This module
cannot enforce that -- it never sees an event's meaning, only its weight -- so
it is a contract on every taxonomy that feeds it. Soccer's `include_goals`
defaults to False for this reason; basketball's split into `pressure` and
`scoring` series is the same rule at a sport where scoring is dense.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

# A momentum event, as this module needs to see it. The taxonomy modules emit
# richer rows (type, player, description); only these three keys are read here.
#   t       -- seconds since the start of play. NOT a display clock, NOT a
#              period-relative countdown. Monotonic across periods/halves, so
#              decay is comparable at any point in the game.
#   sign    -- +1.0 for the home side, -1.0 for the away side.
#   weight  -- non-negative pressure magnitude on the taxonomy's own scale.
_T_KEY = "clock_seconds"
_SIGN_KEY = "sign"
_WEIGHT_KEY = "weight"


def momentum_at(
    events: Iterable[Mapping[str, Any]],
    clock_seconds: float,
    *,
    half_life_seconds: float,
) -> float:
    """Signed momentum as of `clock_seconds`: positive = home on top.

    STRICTLY CAUSAL -- only events at or before `clock_seconds` contribute.

    `half_life_seconds` is REQUIRED and has no default, unlike soccer's
    `momentum_at`. A shared module cannot have a defensible default: soccer
    chose 300s for a game with ~2.7 goals, and the same figure in basketball is
    ~12 possessions per side. A default here would be silently wrong for every
    sport but the one it was chosen for, and an inherited constant is exactly
    the kind of unfed input `model_engine_standard.md` exists to stop.
    """
    if not math.isfinite(float(clock_seconds)):
        raise ValueError(f"clock_seconds must be finite, got {clock_seconds!r}")
    half_life = float(half_life_seconds)
    if not (half_life > 0.0) or not math.isfinite(half_life):
        raise ValueError(f"half_life_seconds must be positive and finite, got {half_life_seconds!r}")

    probe = float(clock_seconds)
    total = 0.0
    for event in events:
        try:
            t = float(event[_T_KEY])
        except (KeyError, TypeError, ValueError):
            # A row without a usable clock cannot be placed in time. Skipping is
            # the only honest option -- dropping it to 0.0 would put it at
            # tip-off, where it would decay to nothing and read as "no event"
            # rather than "an event we could not place".
            continue
        if t > probe:
            # `momentum_events` builders return sorted rows, but this accepts any
            # iterable, so skip rather than break -- an unsorted caller must get a
            # correct answer, not a silently truncated one.
            continue
        decay = math.pow(0.5, (probe - t) / half_life)
        total += float(event.get(_SIGN_KEY) or 0.0) * float(event.get(_WEIGHT_KEY) or 0.0) * decay
    return round(total, 4)


def momentum_series(
    events: Iterable[Mapping[str, Any]],
    *,
    until_seconds: float,
    half_life_seconds: float,
    step_seconds: float = 60.0,
) -> list[tuple[float, float]]:
    """(clock_seconds, momentum) samples -- the shape the vendor charts draw.

    `until_seconds` is REQUIRED. Soccer's version defaults to 5400.0 (90
    minutes), which is a soccer fact. A caller must pass the instant it is
    describing, and that instant should be the LIVE CLOCK rather than the end
    of the feed -- reading the whole feed would let a card show pressure from
    after the moment it claims to describe.
    """
    if float(step_seconds) <= 0.0:
        raise ValueError(f"step_seconds must be positive, got {step_seconds!r}")
    rows = list(events)
    out: list[tuple[float, float]] = []
    t = 0.0
    limit = float(until_seconds)
    while t <= limit:
        out.append((t, momentum_at(rows, t, half_life_seconds=half_life_seconds)))
        t += float(step_seconds)
    return out


def peak_magnitude(series: Sequence[tuple[float, float]]) -> float:
    """Largest absolute excursion, floored above zero so callers can divide.

    Normalising a chart against the match's OWN peak is what makes the curve
    readable: the underlying scale is weighted events under exponential decay,
    which has no natural unit and no comparability across sports.
    """
    if not series:
        return 1e-6
    return max(1e-6, max(abs(float(v)) for _, v in series))


__all__ = ["momentum_at", "momentum_series", "peak_magnitude"]
