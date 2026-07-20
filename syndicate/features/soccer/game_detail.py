from __future__ import annotations

from syndicate.features.soccer.cards import build_cards_page_context
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.shared.game_board_contract import build_single_game_board_context


def build_game_detail_page_context(league: str, selected_date: str, game_pk: str) -> dict:
    league = normalize_league(league)
    league_label = league_display_name(league)
    cards_context = build_cards_page_context(league, selected_date)
    resolved_date = str(cards_context.get("control_value") or cards_context["date"])
    games = cards_context.get("games") or []
    game = next((item for item in games if str(item.get("gamePk")) == str(game_pk)), None)
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": f"{league_label} match unavailable",
            "detail": resolved_date,
            "summary": f"No saved {league_label} SoccerSim match card was available for this date and match id.",
            "metrics": [
                {"label": "Match", "value": str(game_pk)},
                {"label": "Date", "value": resolved_date},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Match unavailable",
                    "title": f"No saved {league_label} match card",
                    "body": "Syndicate could not find a stored SoccerSim match card for this date and match id.",
                    "items": ["Return to the cards board to choose a date with saved artifacts."],
                }
            ],
        }
    game["href"] = f"/soccer/{league}/cards?date={resolved_date}"
    game["href_label"] = f"Back to {league_label} cards"

    return build_single_game_board_context(
        selected_date=resolved_date,
        prev_date=str(cards_context.get("prev_date") or resolved_date),
        next_date=str(cards_context.get("next_date") or resolved_date),
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(league, resolved_date, "Cards"),
        source_path=str(cards_context.get("source_path") or ""),
        source_title=f"{league_label} SoccerSim match card" if game.get("status") != f"{league_label} match unavailable" else f"{league_label} match unavailable",
        using_sample_data=False,
        route_path=f"/soccer/{league}/game/{game_pk}",
        intro_title=f"{league_label} Match {game_pk}",
        intro_body=f"This {league_label} drill-in narrows the SoccerSim cards board to one matchup while keeping the shared game-board shell.",
        cards_grid_class="cards-grid",
        cards_stylesheet=None,
        teaser={
            "label": f"{league_label} cards",
            "body": f"Return to the {league_label} cards board to compare this matchup against the rest of the date's simulated matches.",
            "href": f"/soccer/{league}/cards?date={resolved_date}",
            "cta": f"Open {league_label} cards",
        },
        sport="soccer",
        module="game_detail",
        control_action=f"/soccer/{league}/game/{game_pk}",
        controls_prev_href=f"/soccer/{league}/game/{game_pk}?date={cards_context.get('prev_date') or resolved_date}",
        controls_next_href=f"/soccer/{league}/game/{game_pk}?date={cards_context.get('next_date') or resolved_date}",
        control_value=resolved_date,
        control_label="Date",
        control_type="date",
        control_name="date",
    )
