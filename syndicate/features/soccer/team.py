from __future__ import annotations

from typing import Any

from syndicate.features.soccer.sources import SPARSE_ROSTER_THRESHOLD
from syndicate.features.soccer.sources import all_teams
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import league_select_control
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import rosters_path
from syndicate.features.soccer.sources import schedule_path
from syndicate.features.soccer.sources import team_by_id
from syndicate.features.soccer.sources import team_roster_rows
from syndicate.features.soccer.sources import team_schedule_rows
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context

_POSITION_ORDER = {"goalkeeper": 0, "defender": 1, "midfielder": 2, "forward": 3, "attacker": 3}


def _position_rank(position: str) -> int:
    return _POSITION_ORDER.get(str(position or "").strip().lower(), 9)


def _team_label(league: str, team_id: str) -> tuple[dict[str, Any], str]:
    team = team_by_id(league, team_id) or {}
    name = str(team.get("name") or f"Team {team_id}").strip()
    return team, name


def _player_rank_card(row: dict[str, Any], *, league: str, team_name: str) -> dict[str, Any]:
    player_name = str(row.get("player_name") or "Player").strip() or "Player"
    position = str(row.get("position") or "").strip()
    jersey = str(row.get("jersey") or "").strip()
    return {
        "title": player_name,
        "eyebrow": position or "Squad",
        "badge": f"#{jersey}" if jersey else "-",
        "meta": team_name,
        "team": team_name,
        "headshot_url": str(row.get("headshot_url") or "").strip() or None,
        "metrics": [
            {"label": "Position", "value": position or "-"},
            {"label": "Jersey", "value": jersey or "-"},
            {"label": "Age", "value": str(row.get("age") or "-")},
            {"label": "Height", "value": str(row.get("height") or "-")},
            {"label": "Weight", "value": str(row.get("weight") or "-")},
        ],
        "summary": f"{player_name} ({position or 'Squad'}) is on {team_name}'s full ESPN roster.",
        "list_items": [
            f"Jersey: {jersey or '-'}",
            f"Age: {row.get('age') or '-'}",
            f"Height / weight: {row.get('height') or '-'} / {row.get('weight') or '-'}",
        ],
        "href": None,
    }


def build_roster_page_context(league: str, team_id: str, season: int | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    resolved_season = int(season) if season else default_season(league)
    _, team_name = _team_label(league, team_id)
    rows = team_roster_rows(league, resolved_season, team_id)
    rows_sorted = sorted(rows, key=lambda row: (_position_rank(row.get("position")), str(row.get("player_name") or "")))
    rank_cards = [_player_rank_card(row, league=league, team_name=team_name) for row in rows_sorted]

    query = f"?season={resolved_season}"
    is_sparse = 0 < len(rank_cards) < SPARSE_ROSTER_THRESHOLD
    context = build_rank_page_context(
        selected_date=str(resolved_season),
        route_path=f"/soccer/{league}/team/{team_id}/roster",
        intro_title=f"{team_name} Roster",
        intro_body=f"The full {team_name} squad from ESPN's roster feed -- every rostered player, not just those with accumulated per-90 stats used for prop allocation.",
        aria_label=f"{team_name} roster",
        source_path=str(rosters_path(league, resolved_season)),
        source_title=f"{league_label} roster snapshot" if rank_cards else f"{league_label} roster snapshot unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Players", "value": str(len(rank_cards))},
            {"label": "Team", "value": team_name},
            {"label": "League", "value": league_label},
        ],
        warning_panel={
            "eyebrow": "Data completeness",
            "title": f"ESPN's roster feed for {team_name} looks incomplete",
            "body": (
                f"Only {len(rank_cards)} players are on file, well under a typical full squad "
                f"(20-30+, or a bare matchday squad of 18). This is an upstream ESPN data gap for "
                f"this club, not a parsing issue here -- re-run scripts/build_soccer_rosters.py "
                f"closer to the season if this club's ESPN roster page has since been filled in."
            ),
            "list_items": [f"Players on file: {len(rank_cards)}", f"Sparse-roster threshold: {SPARSE_ROSTER_THRESHOLD}"],
        } if is_sparse else None,
        module_links=[
            {"label": "Roster", "href": f"/soccer/{league}/team/{team_id}/roster{query}", "active": True},
            {"label": "Schedule", "href": f"/soccer/{league}/team/{team_id}/schedule{query}", "active": False},
            {"label": "Cards", "href": f"/soccer/{league}/cards", "active": False},
            {"label": "Hub", "href": "/soccer/hub", "active": False},
        ],
        empty_state={
            "eyebrow": f"{team_name} roster",
            "title": "No stored roster rows were available",
            "body": "The roster board reads a stored ESPN roster snapshot for this league/season, and none was available.",
            "list_items": [f"Run scripts/build_team_branding_snapshot.py --sport {league} then scripts/build_soccer_rosters.py --league {league} --season {resolved_season}."],
        } if not rank_cards else None,
        control_label="Season",
        control_type="number",
        control_name="season",
        control_value=str(resolved_season),
        prev_href=f"/soccer/{league}/team/{team_id}/roster?season={resolved_season - 1}",
        next_href=f"/soccer/{league}/team/{team_id}/roster?season={resolved_season + 1}",
        extra_controls=[team_select_control(league, team_id, page_suffix="roster", query_suffix=query)],
    )
    return context


def build_roster_api_payload(league: str, team_id: str, season: int | None = None) -> dict[str, Any]:
    return build_rank_api_payload(build_roster_page_context(league, team_id, season))


def _fixture_rank_card(row: dict[str, Any], *, league: str, team_name: str, season: int) -> dict[str, Any]:
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    is_home = home_team.strip().lower() == team_name.strip().lower()
    opponent = away_team if is_home else home_team
    week = row.get("week")
    status = str(row.get("status_state") or "pre")
    home_score = row.get("home_score")
    away_score = row.get("away_score")
    score_text = f"{away_score}-{home_score}" if status == "post" and home_score is not None else "-"
    event_id = str(row.get("event_id") or "").strip()

    return {
        "title": f"{'vs' if is_home else '@'} {opponent}",
        "eyebrow": f"Week {week}" if week is not None else "Unscheduled",
        "badge": score_text if score_text != "-" else str(row.get("date") or "")[:10],
        "meta": f"{team_name} {'home' if is_home else 'away'}",
        "metrics": [
            {"label": "Date", "value": str(row.get("date") or "")[:10] or "-"},
            {"label": "Opponent", "value": opponent},
            {"label": "Venue", "value": "Home" if is_home else "Away"},
            {"label": "Status", "value": {"pre": "Scheduled", "in": "Live", "post": "Final"}.get(status, status)},
        ],
        "summary": f"{team_name} {'hosts' if is_home else 'travels to'} {opponent} in week {week} of the {league_display_name(league)} season {season} schedule.",
        "list_items": [f"Score: {score_text}"] if score_text != "-" else ["Not yet played."],
        "href": f"/soccer/{league}/game/{event_id}?week={week}&season={season}" if event_id and week is not None else None,
        "href_label": "Open match card",
    }


def team_select_control(league: str, team_id: str, *, page_suffix: str, query_suffix: str = "") -> dict[str, Any]:
    """An `extra_controls` entry to jump between teams on the same
    roster/schedule page, reusing `_date_controls.html`'s onchange slot."""
    teams = sorted(all_teams(league), key=lambda team: str(team.get("name") or ""))
    options = [{"value": team["team_id"], "label": team.get("name") or team["team_id"]} for team in teams]
    onchange = f"window.location.href = '/soccer/{league}/team/' + this.value + '/{page_suffix}{query_suffix}'"
    return {
        "label": "Team",
        "name": "team",
        "type": "select",
        "value": str(team_id),
        "options": options,
        "onchange": onchange,
    }


def build_team_schedule_page_context(league: str, team_id: str, season: int | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    resolved_season = int(season) if season else default_season(league)
    _, team_name = _team_label(league, team_id)
    rows = team_schedule_rows(league, resolved_season, team_id)
    rows_sorted = sorted(rows, key=lambda row: str(row.get("date") or ""))
    rank_cards = [_fixture_rank_card(row, league=league, team_name=team_name, season=resolved_season) for row in rows_sorted]

    query = f"?season={resolved_season}"
    context = build_rank_page_context(
        selected_date=str(resolved_season),
        route_path=f"/soccer/{league}/team/{team_id}/schedule",
        intro_title=f"{team_name} Schedule",
        intro_body=f"The full {team_name} season {resolved_season} fixture list, from the SoccerSim schedule artifact, linking into the cards board for each matchweek.",
        aria_label=f"{team_name} schedule",
        source_path=str(schedule_path(league, resolved_season)),
        source_title=f"{league_label} schedule" if rank_cards else f"{league_label} schedule unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Fixtures", "value": str(len(rank_cards))},
            {"label": "Team", "value": team_name},
            {"label": "Season", "value": str(resolved_season)},
        ],
        module_links=[
            {"label": "Schedule", "href": f"/soccer/{league}/team/{team_id}/schedule{query}", "active": True},
            {"label": "Roster", "href": f"/soccer/{league}/team/{team_id}/roster{query}", "active": False},
            {"label": "Cards", "href": f"/soccer/{league}/cards", "active": False},
            {"label": "Hub", "href": "/soccer/hub", "active": False},
        ],
        empty_state={
            "eyebrow": f"{team_name} schedule",
            "title": "No stored schedule rows were available",
            "body": "The schedule board reads the SoccerSim season-schedule artifact, and none was available for this team/season.",
            "list_items": [f"Run scripts/build_soccer_schedule.py --league {league} --season {resolved_season}."],
        } if not rank_cards else None,
        control_label="Season",
        control_type="number",
        control_name="season",
        control_value=str(resolved_season),
        prev_href=f"/soccer/{league}/team/{team_id}/schedule?season={resolved_season - 1}",
        next_href=f"/soccer/{league}/team/{team_id}/schedule?season={resolved_season + 1}",
        extra_controls=[team_select_control(league, team_id, page_suffix="schedule", query_suffix=query)],
    )
    return context


def build_team_schedule_api_payload(league: str, team_id: str, season: int | None = None) -> dict[str, Any]:
    return build_rank_api_payload(build_team_schedule_page_context(league, team_id, season))
