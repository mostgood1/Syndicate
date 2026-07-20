"""ESPN match-event (play-by-play) extraction: exact minutes played.

ESPN's match summary carries a ``keyEvents`` timeline -- kickoff, goals,
cards, substitutions -- each with a continuous match clock (seconds from
kickoff: 0 at kickoff, 2700 at halftime, 5400 at full time) and, for
substitutions and red cards, the athlete(s) involved. That's enough to
compute each player's *exact* minutes played for a match, replacing the
appearance-count proxy ``espn_player_stats.py`` used before this existed.

Clock precision note: ``clock.value`` is exact during regulation play but
caps at the period boundary (2700 / 5400) for events that happen during
stoppage time -- e.g. a 90+4' substitution and the 90+7' final whistle both
report ``clock.value == 5400``. That's a fine default for *per-90* rates
specifically (which normalize to a nominal 90-minute match by definition),
but it means minutes computed here slightly overcount playing time for
players subbed off deep in stoppage and slightly undercount it for players
subbed on then. The error is bounded by the stoppage-time length (usually
1-8 minutes) and only touches the small share of subs made in stoppage.
"""

from __future__ import annotations

from typing import Any

_NOMINAL_HALF_SECONDS = 2700.0
_NOMINAL_MATCH_SECONDS = 5400.0
_SUBSTITUTION_TYPE = "substitution"
_RED_CARD_MARKERS = ("red-card", "red card")


def extract_key_events(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize ESPN's raw ``keyEvents`` block into a simpler event list."""
    events: list[dict[str, Any]] = []
    for raw in summary.get("keyEvents") or []:
        event_type = raw.get("type") or {}
        clock = raw.get("clock") or {}
        participants = [
            {
                "athlete_id": str((p.get("athlete") or {}).get("id") or ""),
                "athlete_name": (p.get("athlete") or {}).get("displayName"),
            }
            for p in raw.get("participants") or []
        ]
        events.append(
            {
                "type": str(event_type.get("type") or "").lower(),
                "type_text": event_type.get("text"),
                "period": (raw.get("period") or {}).get("number"),
                "clock_seconds": float(clock.get("value") or 0.0),
                "clock_display": clock.get("displayValue"),
                "team": (raw.get("team") or {}).get("displayName"),
                "participants": participants,
            }
        )
    return events


def compute_minutes_played(
    key_events: list[dict[str, Any]],
    roster_rows: list[dict[str, Any]],
    *,
    match_end_seconds: float = _NOMINAL_MATCH_SECONDS,
) -> dict[str, float]:
    """Exact minutes played per player_id for one match.

    ``roster_rows`` need ``player_id`` and ``starter`` (the shape
    ``espn_lineups.extract_match_player_rows`` already produces). Returns
    only players who actually appeared -- an unused substitute (on the
    bench roster but mentioned in no substitution event) is omitted
    entirely rather than given 0.0, so callers can distinguish "played 0
    minutes" (impossible) from "didn't play this match" (absent from the
    dict). A player red-carded stops accruing minutes at the card's clock
    time; a starter or sub never removed plays to ``match_end_seconds``.
    """
    starters = {str(row.get("player_id")) for row in roster_rows if row.get("starter")}
    all_ids = {str(row.get("player_id")) for row in roster_rows}

    entry_time: dict[str, float] = {player_id: 0.0 for player_id in starters}
    exit_time: dict[str, float] = {}

    for event in key_events:
        if event["type"] == _SUBSTITUTION_TYPE and len(event["participants"]) >= 2:
            # ESPN orders substitution participants [player_in, player_out].
            player_in, player_out = event["participants"][0], event["participants"][1]
            in_id, out_id = player_in["athlete_id"], player_out["athlete_id"]
            if in_id:
                entry_time[in_id] = event["clock_seconds"]
            if out_id and out_id not in exit_time:
                exit_time[out_id] = event["clock_seconds"]
        elif event["type"] in _RED_CARD_MARKERS or "red card" in (event.get("type_text") or "").lower():
            for participant in event["participants"]:
                player_id = participant["athlete_id"]
                if player_id and player_id not in exit_time:
                    exit_time[player_id] = event["clock_seconds"]

    minutes: dict[str, float] = {}
    for player_id in all_ids:
        if player_id not in entry_time and player_id not in exit_time:
            continue  # never entered the match
        start = entry_time.get(player_id, 0.0)
        end = exit_time.get(player_id, match_end_seconds)
        minutes[player_id] = max(0.0, round((end - start) / 60.0, 2))
    return minutes


__all__ = ["compute_minutes_played", "extract_key_events"]
