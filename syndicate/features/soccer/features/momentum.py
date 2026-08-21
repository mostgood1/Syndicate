"""A momentum proxy computed from ESPN's own commentary feed.

WHY OURS RATHER THAN A VENDOR'S. FotMob and AiScore both publish an "attack
momentum" panel -- a signed continuous series, one team above the axis, the
other below -- built (per their own descriptions) from ball possession, WHERE
that possession is, and dangerous attacks. The methodology is not proprietary
magic, which means an approximation is computable from any sufficiently dense
timestamped event feed. We already parse one: ESPN's `commentary` block, ~5x
denser than the `keyEvents` timeline, carrying every shot, corner, foul and
offside with a clock and a team (see `ingestion/espn_shot_events.py`).

WHAT WE CAN AND CANNOT SEE, stated up front because it bounds every claim made
from this module:

    dangerous attacks   -> PROXY ONLY (shots + corners; build-up that never
                           produces a shot is invisible to us)
    possession location -> PARTIAL (shot location from commentary TEXT)
    possession share    -> MATCH TOTAL ONLY, not over time

So this is a pressure proxy, not a reconstruction. `espn_shot_events.py` says
the same thing about its own feed: "intentionally *not* a full possession
reconstruction ... not a complete pass-by-pass/tracking feed".

GOALS ARE EXCLUDED BY DEFAULT, AND THAT IS THE WHOLE POINT.
A momentum series that counts goals spikes AT the goal, so it correlates with
goals by construction and predicts nothing. Any vendor chart showing a peak
exactly at a goal marker has this property. The predictive content, if there is
any, lives in the BUILD-UP -- so `include_goals=False` is the default and the
lead-vs-lag test in `scripts/soccer_momentum_leadlag.py` is only meaningful
with it off.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

# Attacking-pressure weights. Ordered by how strongly each says "this team is
# threatening RIGHT NOW", not by how often it happens.
#
# Fouls are DELIBERATELY ABSENT despite being the most common commentary entry
# (47 of 124 on a sampled match). A foul is committed BY one side and suffered
# by the other, and which of those indicates pressure depends on where it
# happened -- information the feed does not reliably carry. Including them
# would add volume and ambiguity in equal measure.
_EVENT_WEIGHTS: dict[str, float] = {
    "shot-on-target": 3.0,
    "shot-hit-woodwork": 3.0,
    "shot-blocked": 1.5,
    "shot-off-target": 1.5,
    "corner-awarded": 1.0,
    "offside": 0.5,
}
_GOAL_WEIGHT = 3.0

# Multiplier for shots taken close in. `_classify_location` reads ESPN's own
# natural-language description, which that module argues is more reliable than
# the un-reverse-engineered coordinates.
_LOCATION_MULTIPLIER: dict[str, float] = {
    "six_yard_box": 1.5,
    "box": 1.25,
    "outside_box": 0.85,
}

# Half-life of an event's contribution, in seconds. 5 minutes: long enough that
# a spell of pressure accumulates rather than flickering, short enough that a
# chance from fifteen minutes ago is nearly gone. This is a CHOSEN constant,
# not a fitted one -- it should be swept before any number from it is trusted.
DEFAULT_HALF_LIFE_SECONDS = 300.0


def _clock_seconds(play: Mapping[str, Any]) -> float | None:
    clock = play.get("clock") or {}
    try:
        return float(clock.get("value"))
    except (TypeError, ValueError):
        return None


def momentum_events(
    summary: Mapping[str, Any],
    *,
    home_team: str,
    include_goals: bool = False,
) -> list[dict[str, Any]]:
    """Weighted pressure events, signed +1 for home and -1 for away.

    Returns one row per contributing event with its clock and weight, so a
    caller can compute a value at any instant without re-parsing.
    """
    from syndicate.features.soccer.ingestion.espn_shot_events import _classify_location

    out: list[dict[str, Any]] = []
    for entry in summary.get("commentary") or []:
        play = entry.get("play") or {}
        type_key = str((play.get("type") or {}).get("type") or "").strip().lower()
        weight = _EVENT_WEIGHTS.get(type_key)
        if weight is None:
            if include_goals and type_key.startswith("goal"):
                weight = _GOAL_WEIGHT
            else:
                continue
        seconds = _clock_seconds(play)
        if seconds is None:
            continue
        team = str((play.get("team") or {}).get("displayName") or "").strip()
        if not team:
            continue
        if type_key.startswith("shot") or type_key.startswith("goal"):
            weight *= _LOCATION_MULTIPLIER.get(
                _classify_location(str(play.get("text") or "")), 1.0
            )
        out.append({
            "clock_seconds": seconds,
            "team": team,
            "sign": 1.0 if team == home_team else -1.0,
            "weight": weight,
            "type": type_key,
        })
    out.sort(key=lambda r: r["clock_seconds"])
    return out


def momentum_at(
    events: Iterable[Mapping[str, Any]],
    clock_seconds: float,
    *,
    half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS,
) -> float:
    """Signed momentum as of `clock_seconds`: positive = home on top.

    STRICTLY CAUSAL -- only events at or before `clock_seconds` contribute.
    A momentum value that can see the future would make any lead-vs-lag test
    pass trivially, which is the one thing this module exists to answer
    honestly.
    """
    total = 0.0
    for event in events:
        t = float(event["clock_seconds"])
        if t > clock_seconds:
            # `momentum_events` returns sorted rows, but this accepts any
            # iterable, so skip rather than break -- an unsorted caller must get
            # a correct answer, not a silently truncated one.
            continue
        decay = math.pow(0.5, (clock_seconds - t) / max(1.0, half_life_seconds))
        total += float(event["sign"]) * float(event["weight"]) * decay
    return round(total, 4)


def momentum_series(
    events: Iterable[Mapping[str, Any]],
    *,
    until_seconds: float = 5400.0,
    step_seconds: float = 60.0,
    half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS,
) -> list[tuple[float, float]]:
    """(clock_seconds, momentum) samples -- the shape the vendor charts draw."""
    rows = list(events)
    out: list[tuple[float, float]] = []
    t = 0.0
    while t <= until_seconds:
        out.append((t, momentum_at(rows, t, half_life_seconds=half_life_seconds)))
        t += step_seconds
    return out


__all__ = [
    "DEFAULT_HALF_LIFE_SECONDS",
    "momentum_at",
    "momentum_events",
    "momentum_series",
]
