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


def _team_starters(rosters: list[dict[str, Any]]) -> dict[str, list[str]]:
    """{side: [player_id, ...]} for players ESPN's post-match boxscore marks
    `starter: True` -- the ACTUAL starting XI, not a pregame projection.
    Available for every completed match (validated: 11/11 on 3 real fixtures),
    unlike a pregame confirmed lineup which only exists near kickoff. That is
    what makes an AVAILABILITY signal backtestable at all: the concept ("did
    the team's regulars start") is answerable from history even though a LIVE
    feed would still need the separate, already-existing pregame
    `attach_confirmed_starters` mechanism -- these are not the same thing and
    must not be conflated."""
    out: dict[str, list[str]] = {}
    for r in rosters or []:
        side = str(r.get("homeAway") or "").lower()
        if side not in ("home", "away"):
            continue
        ids = [str((p.get("athlete") or {}).get("id") or "")
               for p in (r.get("roster") or []) if p.get("starter")]
        out[side] = [i for i in ids if i]
    return out


def extract_match_stats(summary: dict[str, Any], *, event_id: str, date: str) -> dict[str, Any] | None:
    """One row: both teams' possession share, corner-goal share, and actual
    starting-XI player ids, for one match."""
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

    starters = _team_starters(summary.get("rosters") or [])
    out: dict[str, Any] = {"event_id": event_id, "date": date}
    for side, team in teams_by_side.items():
        out[f"{side}_team"] = team
        out[f"{side}_possession_share"] = possession.get(team)
        g = goals_by_team.get(team, 0)
        cg = corner_goals_by_team.get(team, 0)
        out[f"{side}_goals"] = g
        out[f"{side}_corner_goals"] = cg
        out[f"{side}_set_piece_goal_share"] = (cg / g) if g > 0 else None
        out[f"{side}_starter_ids"] = starters.get(side, [])
    return out


def _merge_walk_forward_availability(
    rows: list[dict[str, Any]], *, window: int = 10, min_prior_matches: int = 5
) -> None:
    """Adds `{side}_starters_available_share` to each row IN PLACE: this
    fixture's actual starting-XI overlap with the team's CORE XI as of that
    date -- the 11 players with the most starts across the team's prior
    `window` matches. WALK-FORWARD BY CONSTRUCTION: only matches strictly
    before a given row inform that row's own core XI, so a team's early-season
    rows (fewer than `min_prior_matches` behind them) get no value rather than
    one built partly from the future -- the identical hazard `compute_team_
    ratings`'s own `as_of` guards against, applied here to lineup history
    instead of goals/shots history.

    VALIDATED BEFORE WIRING: pooled OLS across all nine leagues (14,246
    team-match rows, league fixed effects) found this term significant
    predicting goals scored, net of attack_rating/shots/form/opponent
    strength (coef +0.143, t=+2.06). See lane `soccer-model-dispersion` for
    the full regression and the paired-backtest validation that followed it.

    BACKTEST-HONEST, NOT A LIVE-PRODUCTION LINEUP SOURCE: this uses each
    match's ACTUAL observed starting XI (`{side}_starter_ids`, from ESPN's
    POST-match boxscore, `starter: True`) -- correct for validating the
    concept against history, the same way Brier scoring uses the actual final
    score, which also isn't known live. A live/upcoming fixture's actual
    lineup is not known until near kickoff; that is what the SEPARATE,
    already-existing `attach_confirmed_starters` pregame mechanism is for.
    These are NOT the same thing and must not be conflated -- wiring this
    walk-forward artifact into a FUTURE-fixture production path would silently
    use a value that cannot exist yet.
    """
    from collections import Counter, defaultdict

    ordered = sorted(rows, key=lambda r: r.get("date") or "")
    history: dict[str, list[list[str]]] = defaultdict(list)
    for row in ordered:
        for side in ("home", "away"):
            team = row.get(f"{side}_team")
            starters = row.get(f"{side}_starter_ids") or []
            if not team or not starters:
                continue
            prior = history[team][-window:]
            if len(prior) >= min_prior_matches:
                counts: Counter[str] = Counter()
                for s in prior:
                    counts.update(s)
                core = {pid for pid, _ in counts.most_common(11)}
                if core:
                    row[f"{side}_starters_available_share"] = len(core & set(starters)) / len(core)
            history[team].append(starters)


def aggregate_season_match_stats(league: str, *, date_windows: list[str]) -> list[dict[str, Any]]:
    """All match-stat rows across a league's completed matches in the given
    windows. One HTTP round trip per match -- same cost class as
    `espn_shot_events.aggregate_season_shot_events`, and covers what that one
    covers plus possession, so callers wanting both should use this instead of
    calling both aggregators.

    Also merges `{side}_starters_available_share` via
    `_merge_walk_forward_availability` -- a season-scope, cross-row
    computation, so it runs here rather than in `extract_match_stats`, which
    sees one match in isolation."""
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
    _merge_walk_forward_availability(rows)
    return rows


__all__ = ["aggregate_season_match_stats", "extract_match_stats"]
