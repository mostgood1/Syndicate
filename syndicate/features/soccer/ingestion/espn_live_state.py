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
from syndicate.features.soccer.ingestion.espn_match_events import counts_toward_score
from syndicate.features.soccer.ingestion.espn_match_events import extract_key_events
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

_HALF_SECONDS = 2700.0
_MATCH_SECONDS = 5400.0
# THIS IS THE BEST AVAILABLE RULE, NOT THE RIGHT ANSWER, AND THE DIFFERENCE IS
# MEASURED (lane `soccer-shot-on-target-definition`, 2026-09-17, 48 team-matches
# across epl/la_liga/serie_a/bundesliga 09-01..09-17, ESPN's public feeds).
#
# Against ESPN's OWN per-team `shotsOnTarget`: this rule is exact for 39 of 48
# teams and SHORT for 9 (seven by 1, one by 2, one by 3) -- never over. Total
# shortfall 12 shots, 0.25 per team per match.
#
# IT IS NOT A MISSING TYPE, so do not "fix" it by widening this set. Every one
# of those 9 teams has an EXACT total-shot count (48/48 per team), so the events
# are all present and ESPN's boxscore simply classifies some of them as on
# target while its own commentary types them `shot-off-target` / `shot-blocked`.
# No subset of commentary type keys reconciles: a search over every combination
# scored 39/48 at best, and adding `shot-hit-woodwork` makes it WORSE -- 10
# teams that are exact today each had 1-3 woodwork shots, so ESPN does not count
# those as on target either.
#
# So `shots_on_target_so_far` is a commentary-derived LOWER BOUND on ESPN's
# figure. That matters beyond display: `soccer_live_gameline_source.py` banks
# this field under the live `player_shots_on_target` market, so the banked count
# can sit ~0.25/team/match low and understate an over. Widening the set to close
# the gap would overshoot 39 teams to rescue 9.
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


def _summary_state(summary: dict[str, Any]) -> str:
    """ESPN's own match state for this summary: ``pre`` / ``in`` / ``post`` (empty when absent)."""
    competition = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    return str((((competition.get("status") or {}).get("type") or {}).get("state")) or "").strip().lower()


def _box_corners(summary: dict[str, Any]) -> tuple[int, int] | None:
    """(home, away) ``wonCorners`` from the summary's box score, sides keyed off ESPN's ``homeAway``."""
    found: dict[str, int] = {}
    for team_block in ((summary.get("boxscore") or {}).get("teams") or []):
        side = str(team_block.get("homeAway") or "").strip().lower()
        if side not in {"home", "away"}:
            continue
        for stat in team_block.get("statistics") or []:
            if stat.get("name") != "wonCorners":
                continue
            raw = stat.get("value", stat.get("displayValue"))
            try:
                found[side] = int(float(raw))
            except (TypeError, ValueError):
                pass
    if "home" in found and "away" in found:
        return found["home"], found["away"]
    return None


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
    commentary_has_corners = bool(corner_events)

    if as_of_seconds is not None:
        key_events = [e for e in key_events if e["clock_seconds"] <= as_of_seconds]
        shot_events = [e for e in shot_events if e["clock_seconds"] <= as_of_seconds]
        corner_events = [e for e in corner_events if e["clock_seconds"] <= as_of_seconds]
        cutoff = as_of_seconds
    else:
        cutoff = 2.0 * half_seconds

    # THE TEAM SCORE IS EVERY NON-SHOOTOUT SCORING PLAY, for the team ESPN tags.
    #
    # This counted `type.startswith("goal")` and its comment said "own-goal ...
    # is correctly excluded here". That is right for a PLAYER's tally and wrong
    # for the scoreboard, and the prefix also missed every `penalty---scored`.
    # Measured 2026-09-15 over 95 finished matches: that rule reproduced ESPN's
    # final score on 68, `counts_toward_score` on 95. Live the same evening,
    # Real Madrid at Elche read 1-0 against ESPN's 2-0 (a 25' own goal), and the
    # live projection resumes from this number.
    home_goals = sum(1 for e in key_events if counts_toward_score(e) and e["team"] == home_team)
    away_goals = sum(1 for e in key_events if counts_toward_score(e) and e["team"] == away_team)
    home_red_cards = sum(1 for e in key_events if "red" in e["type"] and e["team"] == home_team)
    away_red_cards = sum(1 for e in key_events if "red" in e["type"] and e["team"] == away_team)

    home_shots = [s for s in shot_events if s["team"] == home_team]
    away_shots = [s for s in shot_events if s["team"] == away_team]

    half, clock_remaining = _current_half_and_clock_remaining(cutoff, half_seconds=half_seconds)

    # CORNERS SO FAR: commentary first, the box score only as a LIVE fallback.
    #
    # Commentary `corner-awarded` events reconcile exactly with ESPN's box `wonCorners` in nine leagues
    # (530 of 530 completed matches within +-1, measured 2026-09-17), and they carry a clock, so a replay at
    # any cutoff is exact. Belgian Pro League's commentary carries NONE (0 of 554 box corners), so there the
    # count was structurally 0 and every live corners projection added nothing for the corners already taken.
    #
    # The box score fills that gap, but ONLY for a match ESPN reports as in progress, and only when the
    # commentary has no corner events at all. A completed match's box is its FINAL total, so reading it for a
    # replay at a cutoff would leak the future into every backtest; there the commentary count (0) stands and
    # `corners_source` says why. Commentary with any corner events is never mixed with the box.
    home_corners = sum(1 for e in corner_events if e["team"] == home_team)
    away_corners = sum(1 for e in corner_events if e["team"] == away_team)
    corners_source = "commentary" if commentary_has_corners else "commentary_empty"
    if not commentary_has_corners and _summary_state(summary) == "in":
        box = _box_corners(summary)
        if box is not None and sum(box) > 0:
            home_corners, away_corners = box
            corners_source = "box_fallback"

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

    state = {
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
        "home_corners_so_far": home_corners,
        "away_corners_so_far": away_corners,
        "corners_source": corners_source,
        "player_stats": player_stats,
    }
    # GAME SHAPE -- the state a live projection is computed FROM, kept rather
    # than left implicit. Lane `game-shape-capture`; contract in
    # `shared/game_shape.py`. Soccer is the only sport here whose live state
    # carries real in-game EVENTS (shots, shots on target, corners, red cards),
    # so it is the only one that can express a true event rate and a dominance
    # share -- the things a 0-0 scoreline hides.
    #
    # Built from `state` and NOT from the projection: the shape must stay free
    # of model output or the error analysis it feeds becomes circular. The
    # caller attaches its `projection` block to this same record afterwards;
    # this runs first, on purpose.
    #
    # Function-local import and a bare except: instrumentation must never take
    # down the live-state build, which is the product.
    try:
        from syndicate.features.shared.game_shape import soccer_game_shape

        state["game_shape"] = soccer_game_shape(state)
    except Exception:
        state["game_shape"] = None
    return state


__all__ = ["build_live_state"]
