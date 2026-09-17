"""Shot-level truth from ESPN's match commentary feed.

ESPN's match summary carries two event feeds: the sparse ``keyEvents``
timeline (goals/cards/subs, used by ``espn_match_events.py`` for minutes)
and a much richer ``commentary`` feed -- roughly 5x the entries -- covering
every shot (on/off target, blocked, off the woodwork, and the penalty
variants), corner, foul, and offside, each with
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

# EVERY non-goal commentary type that IS a shot. Measured 2026-09-17 over 24
# finished matches (epl/la_liga/serie_a/bundesliga, 09-01..09-17): with only the
# first three, extracted totals matched ESPN's own `totalShots` in 9 of 24
# matches; with `shot-hit-woodwork` and the penalty variants, 24 of 24, and each
# match's shortfall equalled its dropped-event count exactly. 23 woodwork events
# and 1 `penalty---saved` in that sample = 1.42 shots/match, 5.0 per 100 kept --
# shots that were not off target, not blocked, but ABSENT.
#
# `penalty---missed` and `penalty---post` did not occur in the sample and are
# included from the naming pattern of the two that did. A wrong guess costs an
# unused entry; omitting a real one costs a silent drop, which is the defect
# this lane exists to fix -- and `_UNMAPPED_SHOT_TEXT` below makes the next
# unknown key loud either way.
_NON_GOAL_SHOT_TYPES = {
    "shot-on-target",
    "shot-off-target",
    "shot-blocked",
    "shot-hit-woodwork",
    "penalty---saved",
    "penalty---missed",
    "penalty---post",
}
_CORNER_MARKER = "following a corner"

# A commentary entry whose TEXT describes a shot while its type key is not one
# this module knows. ESPN adds and renames these keys with no notice and the
# failure mode is SILENT -- the shot stops existing, and every total downstream
# is quietly short. Across those 24 matches this matched exactly the types added
# above and nothing else, so it is a tripwire, not a source of noise.
_UNMAPPED_SHOT_TEXT = ("shot", "attempt", "header", "effort", "strike")

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


def _is_goal_by_the_shooter(type_key: str) -> bool:
    # ESPN uses distinct type keys for goal variants ("goal", "goal---volley",
    # "goal---header", ...) -- match the prefix, or non-plain goals silently
    # fall through to "unknown" and vanish from conversion-rate measurement.
    # "own-goal" doesn't share this prefix, so it's correctly excluded: it is
    # nobody's shot.
    #
    # A CONVERTED PENALTY IS THE TAKER'S GOAL, and its key is NOT goal-prefixed.
    # Commentary files it as `penalty---scored` ("Goal! ... converts the
    # penalty"), measured on por.1 401885443 2026-09-15; it made up 23 of 293
    # scoring plays over 95 finished matches. Without this, every penalty
    # taker's live shots and goals came up one short.
    return type_key.startswith("goal") or type_key.startswith("penalty---scored")


def _classify_outcome(type_key: str) -> str:
    if _is_goal_by_the_shooter(type_key):
        return "goal"
    return {
        "shot-on-target": "saved",
        "shot-off-target": "off_target",
        "shot-blocked": "blocked",
        # ITS OWN VALUE, NOT FOLDED INTO on/off TARGET, and that is a measurement
        # rather than caution. Against ESPN's own `shotsOnTarget` over the same
        # 24 matches, counting woodwork as OFF target reconciles 15 of 24 and as
        # ON target 10 of 24, with residuals in BOTH directions -- so ESPN's
        # on-target figure is not a function of these keys and either choice
        # would be a guess wearing a fix's clothes. `woodwork` counts as a SHOT
        # (which is exact, 24/24) and is absent from `espn_live_state`'s
        # `_ON_TARGET_OUTCOMES`, so it lands off target there while the open
        # question stays visible instead of being silently decided here.
        "shot-hit-woodwork": "woodwork",
        "penalty---saved": "saved",
        "penalty---missed": "off_target",
        "penalty---post": "woodwork",
    }.get(type_key, "unknown")


def extract_shot_events(summary: dict[str, Any], *, event_id: str) -> list[dict[str, Any]]:
    """One row per shot (incl. goals) from a match's commentary feed."""
    commentary = summary.get("commentary") or []
    rows: list[dict[str, Any]] = []
    unmapped: set[str] = set()
    for entry in commentary:
        play = entry.get("play") or {}
        type_key = str((play.get("type") or {}).get("type") or "").lower()
        if type_key not in _NON_GOAL_SHOT_TYPES and not _is_goal_by_the_shooter(type_key):
            # THE TRIPWIRE. Dropping an entry is normal -- fouls, cards, subs and
            # substitutions are most of this feed. Dropping one whose TEXT calls
            # it a shot is the defect that hid `shot-hit-woodwork` for the life
            # of this module, and it hid because nothing said a word. One line
            # per unknown type per match, not per entry: enough to name the key
            # and read the sentence, bounded when a whole feed changes shape.
            text_lower = str(play.get("text") or "").lower()
            if type_key not in unmapped and any(word in text_lower for word in _UNMAPPED_SHOT_TEXT):
                unmapped.add(type_key)
                print(
                    f"[espn_shot_events] SHOT_EVENT_TYPE_UNMAPPED event_id={event_id} "
                    f"type={type_key or '(empty)'} text={text_lower[:120]!r}",
                    flush=True,
                )
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
