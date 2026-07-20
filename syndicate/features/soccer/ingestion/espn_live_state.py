"""Reconstruct match state as of a point in time from ESPN summary data.

The one function this module exists for -- ``build_live_state`` -- works
identically whether the summary comes from a genuinely in-progress match
(``as_of_seconds=None``: use everything ESPN has posted so far, which *is*
the live cutoff by construction) or a completed match being replayed for
backtesting (``as_of_seconds=<some clock value>``: only events at or before
that point count). That symmetry is what makes the live lens's forward
projections testable without needing a real live match: cut a finished
match off at, say, the 60th minute, and the "current state" this module
reconstructs is exactly what a live poll would have returned at that
moment -- see ``scripts/backtest_soccer_live_lens.py``.

Score, cards, and confirmed lineup come from ``keyEvents``/rosters (already
used for minutes and lineups). Corners and shots-so-far -- per team and per
player -- come from the ``commentary`` feed (``espn_shot_events.py``'s
source), since ``keyEvents`` doesn't carry them.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
from syndicate.features.soccer.ingestion.espn_match_events import extract_key_events
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

_HALF_SECONDS = 2700.0
_MATCH_SECONDS = 5400.0
_ON_TARGET_OUTCOMES = {"goal", "saved"}


def _extract_corner_events(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Corners aren't in keyEvents and aren't reliably inferrable from shots
    (not every corner produces one) -- ``commentary`` carries them directly
    as their own play type."""
    corners: list[dict[str, Any]] = []
    for entry in summary.get("commentary") or []:
        play = entry.get("play") or {}
        if str((play.get("type") or {}).get("type") or "").lower() != "corner-awarded":
            continue
        clock = play.get("clock") or {}
        corners.append(
            {
                "team": (play.get("team") or {}).get("displayName"),
                "clock_seconds": float(clock.get("value") or 0.0),
            }
        )
    return corners


def _current_half_and_clock_remaining(as_of_seconds: float, *, half_seconds: float = _HALF_SECONDS) -> tuple[int, float]:
    """(half, clock_remaining_in_that_half) for a continuous match-clock
    value. Stoppage time is folded into the current half (a cutoff at
    2650s, five minutes from the half boundary, is still half 1)."""
    if as_of_seconds < half_seconds:
        return 1, max(0.0, half_seconds - as_of_seconds)
    return 2, max(0.0, (2 * half_seconds) - as_of_seconds)


def _team_names_from_summary(summary: dict[str, Any]) -> tuple[str, str]:
    """Derive home/away display names from the summary's own rosters,
    rather than trusting a caller-supplied name -- ESPN's own naming isn't
    always what a fixture built from another source (Odds API, football-
    data.co.uk) would guess ("AFC Bournemouth" vs "Bournemouth"), and a
    mismatch here would silently zero out one side's entire live state."""
    home = ""
    away = ""
    for block in summary.get("rosters") or []:
        name = ((block.get("team") or {}).get("displayName")) or ""
        if block.get("homeAway") == "home":
            home = name
        elif block.get("homeAway") == "away":
            away = name
    return home, away


def build_live_state(
    summary: dict[str, Any],
    *,
    event_id: str,
    home_team: str | None = None,
    away_team: str | None = None,
    as_of_seconds: float | None = None,
    half_seconds: float = _HALF_SECONDS,
) -> dict[str, Any]:
    """Match state as of ``as_of_seconds`` (or "everything posted so far"
    when ``None`` -- the live case).

    ``home_team``/``away_team`` default to the summary's own roster names
    (see ``_team_names_from_summary``) -- pass them explicitly only to
    override, e.g. for a summary shape that lacks a ``rosters`` block.

    ``as_of_seconds=None`` means "full match" (cutoff at nominal full time,
    ``2 * half_seconds``) -- the right default for backtesting against a
    completed match. It is **not** a substitute for a true live clock: a
    genuinely in-progress match's current time can't be reliably inferred
    from "the last event seen so far" (a quiet spell with no shots/cards
    would make it look earlier than it is). Live callers must source the
    actual current clock from ESPN's live status and pass it explicitly.

    Returns a plain dict (not a PossessionState) because it carries more
    than the engine's resume state needs -- accumulated shots/goals per
    player, corner counts, red-card counts -- all of which ``live_lens.py``
    uses to combine "already happened" with "projected remainder."
    """
    summary_home, summary_away = _team_names_from_summary(summary)
    home_team = home_team or summary_home
    away_team = away_team or summary_away
    roster_rows = extract_match_player_rows(summary, event_id=event_id)
    key_events = extract_key_events(summary)
    shot_events = extract_shot_events(summary, event_id=event_id)
    corner_events = _extract_corner_events(summary)

    if as_of_seconds is not None:
        key_events = [e for e in key_events if e["clock_seconds"] <= as_of_seconds]
        shot_events = [e for e in shot_events if e["clock_seconds"] <= as_of_seconds]
        corner_events = [e for e in corner_events if e["clock_seconds"] <= as_of_seconds]
        cutoff = as_of_seconds
    else:
        cutoff = 2.0 * half_seconds

    # ESPN uses distinct type keys for goal variants ("goal", "goal---volley",
    # "goal---header", ...) -- match the prefix, not an exact string, or
    # non-plain goals silently drop from the count. "own-goal" doesn't share
    # this prefix, so it's correctly excluded here.
    home_goals = sum(1 for e in key_events if e["type"].startswith("goal") and e["team"] == home_team)
    away_goals = sum(1 for e in key_events if e["type"].startswith("goal") and e["team"] == away_team)
    home_red_cards = sum(1 for e in key_events if "red" in e["type"] and e["team"] == home_team)
    away_red_cards = sum(1 for e in key_events if "red" in e["type"] and e["team"] == away_team)

    home_shots = [s for s in shot_events if s["team"] == home_team]
    away_shots = [s for s in shot_events if s["team"] == away_team]

    half, clock_remaining = _current_half_and_clock_remaining(cutoff, half_seconds=half_seconds)

    player_stats: dict[str, dict[str, Any]] = {}
    for row in roster_rows:
        player_id = str(row.get("player_id") or "")
        if not player_id:
            continue
        player_stats[player_id] = {
            "player_id": player_id,
            "player_name": row.get("player_name"),
            "team": row.get("team"),
            "position": row.get("position"),
            "starter": row.get("starter"),
            "is_goalkeeper": row.get("is_goalkeeper"),
            "shots_so_far": 0,
            "shots_on_target_so_far": 0,
            "goals_so_far": 0,
            "assists_so_far": 0,
        }
    for shot in shot_events:
        entry = player_stats.get(shot["player_id"])
        if entry is None:
            continue
        entry["shots_so_far"] += 1
        if shot["outcome"] in _ON_TARGET_OUTCOMES:
            entry["shots_on_target_so_far"] += 1
        if shot["outcome"] == "goal":
            entry["goals_so_far"] += 1
        assist_entry = player_stats.get(shot["assist_player_id"])
        if shot["outcome"] == "goal" and assist_entry is not None:
            assist_entry["assists_so_far"] += 1

    return {
        "event_id": event_id,
        "home_team": home_team,
        "away_team": away_team,
        "as_of_seconds": cutoff,
        "half": half,
        "clock_remaining": clock_remaining,
        "score_home": home_goals,
        "score_away": away_goals,
        "home_red_cards": home_red_cards,
        "away_red_cards": away_red_cards,
        "home_shots_so_far": len(home_shots),
        "away_shots_so_far": len(away_shots),
        "home_shots_on_target_so_far": sum(1 for s in home_shots if s["outcome"] in _ON_TARGET_OUTCOMES),
        "away_shots_on_target_so_far": sum(1 for s in away_shots if s["outcome"] in _ON_TARGET_OUTCOMES),
        "home_corners_so_far": sum(1 for e in corner_events if e["team"] == home_team),
        "away_corners_so_far": sum(1 for e in corner_events if e["team"] == away_team),
        "player_stats": player_stats,
    }


__all__ = ["build_live_state"]
