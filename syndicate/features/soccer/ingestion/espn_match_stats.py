"""Per-match possession% and set-piece goal share from ESPN's match summary.

Two fields the sim engine has read since it was written and nothing has ever
fed: `possession_metrics.possession_share` and
`set_piece_metrics.set_piece_goal_share`
(`scripts/soccer_sim_input_checklist.py`). Both come from data ESPN's summary
endpoint already returns on every call `espn_shot_events.py` already makes --
`boxscore.teams[].statistics[].possessionPct` (a real, direct field, confirmed
present as far back as 2023) and the SAME `commentary` feed's `from_corner`
shot tagging, aggregated to a goal-share instead of a shot-share because
`set_piece_goal_share` is the key name the engine's `_first_float` call
actually looks for first.

ONE fetch per match serves both -- this module does not call
`espn_shot_events.aggregate_season_shot_events` separately, to avoid paying
for the same HTTP round trip twice across ~900 matches/league.

CONSERVATIVE ON SET PIECES ON PURPOSE: `_CORNER_MARKER` only catches
"following a corner" in ESPN's commentary text, so this counts corner-derived
goals only -- free kicks and penalties are NOT included. That undercounts true
set-piece share; it does not overcount, which is the safer direction to be
wrong in for a numerator this small (a handful of goals per team per season).
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

_POSSESSION_STAT = "possessionPct"


def _team_possession(boxscore: dict[str, Any]) -> dict[str, float]:
    """{team_display_name: possession_pct as a 0-1 share}, or {} if absent."""
    out: dict[str, float] = {}
    for team_block in boxscore.get("teams") or []:
        name = ((team_block.get("team") or {}).get("displayName") or "").strip()
        if not name:
            continue
        for stat in team_block.get("statistics") or []:
            if stat.get("name") == _POSSESSION_STAT:
                try:
                    value = float(stat.get("displayValue") or 0.0)
                except (TypeError, ValueError):
                    continue
                # ESPN reports this as a 0-100 number ("46.6"); the engine's own
                # `_possession_share` divides by 100 only when it sees a value
                # >1.0 -- match that convention here for consistency, storing
                # the 0-1 share directly so a caller need not guess the units.
                out[name] = value / 100.0 if value > 1.0 else value
                break
    return out


def extract_match_stats(summary: dict[str, Any], *, event_id: str, date: str) -> dict[str, Any] | None:
    """One row: both teams' possession share and corner-goal share for one match."""
    header = summary.get("header") or {}
    competitions = header.get("competitions") or []
    if not competitions:
        return None
    competitors = (competitions[0] or {}).get("competitors") or []
    if len(competitors) != 2:
        return None
    teams_by_side: dict[str, str] = {}
    for c in competitors:
        side = str(c.get("homeAway") or "").lower()
        name = ((c.get("team") or {}).get("displayName") or "").strip()
        if side in ("home", "away") and name:
            teams_by_side[side] = name
    if "home" not in teams_by_side or "away" not in teams_by_side:
        return None

    possession = _team_possession(summary.get("boxscore") or {})
    shots = extract_shot_events(summary, event_id=event_id)
    goals_by_team: dict[str, int] = {}
    corner_goals_by_team: dict[str, int] = {}
    for row in shots:
        if row.get("outcome") != "goal":
            continue
        team = str(row.get("team") or "")
        goals_by_team[team] = goals_by_team.get(team, 0) + 1
        if row.get("from_corner"):
            corner_goals_by_team[team] = corner_goals_by_team.get(team, 0) + 1

    out: dict[str, Any] = {"event_id": event_id, "date": date}
    for side, team in teams_by_side.items():
        out[f"{side}_team"] = team
        out[f"{side}_possession_share"] = possession.get(team)
        g = goals_by_team.get(team, 0)
        cg = corner_goals_by_team.get(team, 0)
        out[f"{side}_goals"] = g
        out[f"{side}_corner_goals"] = cg
        out[f"{side}_set_piece_goal_share"] = (cg / g) if g > 0 else None
    return out


def aggregate_season_match_stats(league: str, *, date_windows: list[str]) -> list[dict[str, Any]]:
    """All match-stat rows across a league's completed matches in the given
    windows. One HTTP round trip per match -- same cost class as
    `espn_shot_events.aggregate_season_shot_events`, and covers what that one
    covers plus possession, so callers wanting both should use this instead of
    calling both aggregators."""
    completed = fetch_completed_events(league, date_windows=date_windows)
    rows: list[dict[str, Any]] = []
    for event in completed:
        try:
            summary = fetch_match_summary(league, event["event_id"])
        except Exception:
            continue
        row = extract_match_stats(summary, event_id=event["event_id"], date=str(event.get("date") or ""))
        if row is not None:
            rows.append(row)
    return rows


__all__ = ["aggregate_season_match_stats", "extract_match_stats"]
