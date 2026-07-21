from __future__ import annotations

from typing import Any

from syndicate.features.soccer.cards import week_games
from syndicate.features.soccer.sources import available_weeks
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import league_select_control
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import week_label
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context

_WINDOW = 12


def _week_card(league: str, season: int, week: int) -> dict[str, Any]:
    games = week_games(league, week, season)
    simulated = sum(1 for game in games if game.get("panels", [{}])[0].get("eyebrow") == "Match projection")
    league_label = league_display_name(league)
    return {
        "title": str(week),
        "eyebrow": week_label(league, season, week),
        "badge": f"{len(games)} matches",
        "meta": f"{league_label} season {season}",
        "metrics": [
            {"label": "Matches", "value": str(len(games))},
            {"label": "Simulated", "value": str(simulated)},
            {"label": "Season", "value": str(season)},
        ],
        "summary": f"Week {week} of the {league_label} season {season} schedule, {simulated} of {len(games)} matches simulated.",
        "list_items": [f"{game['away']['name']} @ {game['home']['name']}" for game in games[:6]] or ["No fixtures on the schedule for this week."],
        "href": f"/soccer/{league}/cards?week={week}&season={season}",
        "href_label": "Open cards board",
    }


def build_archive_page_context(league: str, week: int | None = None, season: int | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    resolved_season = int(season) if season else default_season(league)
    weeks = available_weeks(league, resolved_season)
    resolved_week = int(week) if week else default_week(league, resolved_season)

    if weeks:
        try:
            index = weeks.index(resolved_week)
        except ValueError:
            index = len(weeks) - 1
        start = max(0, index - (_WINDOW // 2))
        end = min(len(weeks), start + _WINDOW)
        start = max(0, end - _WINDOW)
        window_weeks = list(reversed(weeks[start:end]))
    else:
        window_weeks = []

    cards = [_week_card(league, resolved_season, week_number) for week_number in window_weeks]
    cards.sort(key=lambda card: (0 if card.get("title") == str(resolved_week) else 1, card.get("title")))

    prev_week = max([w for w in weeks if w < resolved_week], default=resolved_week)
    next_week = min([w for w in weeks if w > resolved_week], default=resolved_week)
    query = f"?week={resolved_week}&season={resolved_season}"

    context = build_rank_page_context(
        selected_date=str(resolved_week),
        route_path=f"/soccer/{league}/archive",
        intro_title=f"{league_label} Weekly Archive",
        intro_body=f"This archive board lists {league_label} season {resolved_season} matchweeks and links each one back into the cards board.",
        aria_label=f"{league_label} weekly archive",
        source_path=f"data/soccer_source/{league}/api/schedule/schedule_{resolved_season}.json",
        source_title=f"{league_label} SoccerSim schedule" if cards else f"{league_label} schedule unavailable",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Weeks in season", "value": str(len(weeks))},
            {"label": "Selected week matches", "value": str(len(week_games(league, resolved_week, resolved_season)))},
            {"label": "League", "value": league_label},
        ],
        module_links=build_module_links(league, resolved_week, resolved_season, "Weekly Archive"),
        warning_panel={
            "eyebrow": "Archive lane",
            "title": "Weekly archive weeks drill back into cards",
            "body": "Use this archive to browse the season's matchweeks, then jump into the cards board for matchup-level detail.",
            "list_items": [
                "Each card summarizes one matchweek from the SoccerSim schedule artifact.",
                f"Run scripts/build_soccer_schedule.py --league {league} --season {resolved_season} to (re)populate the season schedule.",
            ],
        },
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/soccer/{league}/archive?week={prev_week}&season={resolved_season}",
        next_href=f"/soccer/{league}/archive?week={next_week}&season={resolved_season}",
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
        # No query_suffix -- see cards.py's build_cards_page_context for why.
        extra_controls=[league_select_control(league, page_path="/archive")],
    )
    if not cards:
        context["empty_state"] = {
            "eyebrow": f"{league_label} weekly archive",
            "title": "No stored SoccerSim weeks were available",
            "body": "The weekly archive only renders weeks present in the SoccerSim schedule artifact, and none were available.",
            "list_items": [f"Run scripts/build_soccer_schedule.py --league {league} --season {resolved_season} to populate this archive lane."],
        }
    return context


def build_archive_api_payload(league: str, week: int | None = None, season: int | None = None) -> dict[str, Any]:
    context = build_archive_page_context(league, week, season)
    return build_rank_api_payload(context)
