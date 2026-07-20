from __future__ import annotations

from syndicate.features.soccer.cards import week_games
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.shared.game_board_contract import build_single_game_board_context


def build_game_detail_page_context(league: str, week: int | None, season: int | None, game_pk: str) -> dict:
    league = normalize_league(league)
    league_label = league_display_name(league)
    resolved_season = int(season) if season else default_season(league)
    resolved_week = int(week) if week else default_week(league, resolved_season)

    games = week_games(league, resolved_week, resolved_season)
    game = next((item for item in games if str(item.get("gamePk")) == str(game_pk)), None)
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": f"{league_label} match unavailable",
            "detail": f"Week {resolved_week}",
            "summary": f"No saved {league_label} SoccerSim match card was available for this week and match id.",
            "metrics": [
                {"label": "Match", "value": str(game_pk)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Match unavailable",
                    "title": f"No saved {league_label} match card",
                    "body": "Syndicate could not find a stored SoccerSim match card, or a scheduled fixture, for this week and match id.",
                    "items": ["Return to the cards board to choose a week with saved artifacts."],
                }
            ],
        }
    query = f"?week={resolved_week}&season={resolved_season}"
    game["href"] = f"/soccer/{league}/cards{query}"
    game["href_label"] = f"Back to {league_label} cards"

    return build_single_game_board_context(
        selected_date=f"Week {resolved_week}",
        prev_date=str(resolved_week),
        next_date=str(resolved_week),
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(league, resolved_week, resolved_season, "Cards"),
        source_path="",
        source_title=f"{league_label} SoccerSim match card" if game.get("status") != f"{league_label} match unavailable" else f"{league_label} match unavailable",
        using_sample_data=False,
        route_path=f"/soccer/{league}/game/{game_pk}",
        intro_title=f"{league_label} Match {game_pk}",
        intro_body=f"This {league_label} drill-in narrows the SoccerSim cards board to one matchup while keeping the shared game-board shell.",
        cards_grid_class="cards-grid",
        cards_stylesheet=None,
        teaser={
            "label": f"{league_label} cards",
            "body": f"Return to the {league_label} cards board to compare this matchup against the rest of the week's simulated matches.",
            "href": f"/soccer/{league}/cards{query}",
            "cta": f"Open {league_label} cards",
        },
        sport="soccer",
        module="game_detail",
        control_action=f"/soccer/{league}/game/{game_pk}",
        controls_prev_href=f"/soccer/{league}/game/{game_pk}{query}",
        controls_next_href=f"/soccer/{league}/game/{game_pk}{query}",
        control_value=str(resolved_week),
        control_label="Week",
        control_type="number",
        control_name="week",
    )
