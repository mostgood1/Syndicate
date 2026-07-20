"""Shot-level truth from ESPN's match commentary feed.

ESPN's match summary carries two event feeds: the sparse ``keyEvents``
timeline (goals/cards/subs, used by ``espn_match_events.py`` for minutes)
and a much richer ``commentary`` feed -- roughly 5x the entries -- covering
every shot (on/off target, blocked), corner, foul, and offside, each with
a clock, team, participants, and (unreliable, unreverse-engineered)
field-position coordinates.

Rather than reverse-engineer ESPN's pitch-coordinate convention, this
module classifies shot location from ESPN's own commentary *text*, which
already describes it in natural language ("...shot from outside the
box...", "...from the centre of the box...", "...from the left side of
the six yard box..."). That's a more reliable signal than the coordinates
and needs no calibration of its own.

This is intentionally *not* a full possession reconstruction -- ESPN's
commentary is a notable-events feed (shots, corners, cards, fouls), not a
complete pass-by-pass/tracking feed, so there's no reliable way to recover
where a possession started or how many events preceded a shot. What it
does support well: real location-conditioned and corner-phase-conditioned
shot outcomes, which is what SoccerSim's ``box_shot_conversion_base`` /
``outside_box_conversion_base`` / ``corner_shot_conversion_base`` profile
parameters are calibrated against -- see
``scripts/calibrate_shot_locations.py``.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary

_NON_GOAL_SHOT_TYPES = {"shot-on-target", "shot-off-target", "shot-blocked"}
_CORNER_MARKER = "following a corner"

# Checked in order -- "outside the box" must win before the generic "box"
# markers below it, since it contains the substring "box".
_LOCATION_MARKERS: tuple[tuple[str, str], ...] = (
    ("outside the box", "outside_box"),
    ("six yard box", "six_yard_box"),
    ("the box", "box"),
    ("close range", "box"),
    ("difficult angle", "outside_box"),
    ("yards", "outside_box"),
)


def _classify_location(text: str) -> str:
    lowered = text.lower()
    for marker, location in _LOCATION_MARKERS:
        if marker in lowered:
            return location
    return "unknown"


def _classify_outcome(type_key: str) -> str:
    # ESPN uses distinct type keys for goal variants ("goal", "goal---volley",
    # "goal---header", ...) -- match the prefix, or non-plain goals silently
    # fall through to "unknown" and vanish from conversion-rate measurement.
    # "own-goal" doesn't share this prefix, so it's correctly excluded.
    if type_key.startswith("goal"):
        return "goal"
    return {
        "shot-on-target": "saved",
        "shot-off-target": "off_target",
        "shot-blocked": "blocked",
    }.get(type_key, "unknown")


def extract_shot_events(summary: dict[str, Any], *, event_id: str) -> list[dict[str, Any]]:
    """One row per shot (incl. goals) from a match's commentary feed."""
    commentary = summary.get("commentary") or []
    rows: list[dict[str, Any]] = []
    for entry in commentary:
        play = entry.get("play") or {}
        type_key = str((play.get("type") or {}).get("type") or "").lower()
        if type_key not in _NON_GOAL_SHOT_TYPES and not type_key.startswith("goal"):
            continue
        text = str(play.get("text") or "")
        clock = play.get("clock") or {}
        participants = play.get("participants") or []
        shooter = participants[0].get("athlete", {}) if participants else {}
        assister = participants[1].get("athlete", {}) if len(participants) > 1 else {}
        rows.append(
            {
                "event_id": event_id,
                "team": (play.get("team") or {}).get("displayName"),
                "period": (play.get("period") or {}).get("number"),
                "clock_seconds": float(clock.get("value") or 0.0),
                "player_id": str(shooter.get("id") or ""),
                "player_name": shooter.get("displayName"),
                "assist_player_id": str(assister.get("id") or ""),
                "assist_player_name": assister.get("displayName"),
                "outcome": _classify_outcome(type_key),
                "location": _classify_location(text),
                "from_corner": _CORNER_MARKER in text.lower(),
                "field_position_x": play.get("fieldPositionX"),
                "field_position_y": play.get("fieldPositionY"),
                "text": text,
            }
        )
    return rows


def aggregate_season_shot_events(league: str, *, date_windows: list[str]) -> list[dict[str, Any]]:
    """All shot rows across a league's completed matches in the given
    windows. One HTTP round trip per match (summary carries commentary
    already, no extra endpoint)."""
    completed = fetch_completed_events(league, date_windows=date_windows)
    rows: list[dict[str, Any]] = []
    for event in completed:
        try:
            summary = fetch_match_summary(league, event["event_id"])
        except Exception:
            continue
        rows.extend(extract_shot_events(summary, event_id=event["event_id"]))
    return rows


__all__ = ["aggregate_season_shot_events", "extract_shot_events"]
