from __future__ import annotations

from syndicate.features.ncaab.cards import build_cards_page_context
from syndicate.features.ncaab.sources import build_module_links
from syndicate.features.shared.game_board_contract import build_single_game_board_context


def build_game_detail_page_context(selected_date: str, game_pk: str) -> dict:
    cards_context = build_cards_page_context(selected_date)
    resolved_date = str(cards_context.get("control_value") or cards_context["date"])
    games = cards_context.get("games") or []
    game = next((item for item in games if str(item.get("gamePk")) == str(game_pk)), None)
    using_sample_data = False
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": "NCAAB game unavailable",
            "detail": resolved_date,
            "summary": "No saved NCAAB source recommendation card was available for this date and game id.",
            "metrics": [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Date", "value": resolved_date},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Game unavailable",
                    "title": "No saved NCAAB game card",
                    "body": "Syndicate could not find a stored NCAAB source recommendation card for this date and game id.",
                    "items": ["Return to the NCAAB cards board to choose a date with saved source output."],
                }
            ],
        }
    game["href"] = f"/ncaab/cards?date={resolved_date}"
    game["href_label"] = "Back to NCAAB cards"

    return build_single_game_board_context(
        selected_date=resolved_date,
        prev_date=str(cards_context.get("prev_date") or resolved_date),
        next_date=str(cards_context.get("next_date") or resolved_date),
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(resolved_date, "Cards"),
        source_path=str(cards_context.get("source_path") or f"data/ncaab_source/api/recommendations/recommendations_{resolved_date}.json"),
        source_title="NCAAB mirrored game card" if game.get("status") != "NCAAB game unavailable" else "NCAAB game unavailable",
        using_sample_data=using_sample_data,
        route_path=f"/ncaab/game/{game_pk}",
        intro_title=f"NCAAB Game {game_pk}",
        intro_body="This NCAAB drill-in narrows the mirrored recommendations board to one matchup while keeping the shared game-board shell.",
        cards_grid_class="cards-grid",
        cards_stylesheet=None,
        teaser={
            "label": "NCAAB cards",
            "body": "Return to the NCAAB cards board to compare this matchup against the rest of the date's mirrored recommendations.",
            "href": f"/ncaab/cards?date={resolved_date}",
            "cta": "Open NCAAB cards",
        },
        sport="ncaab",
        module="game_detail",
        control_action=f"/ncaab/game/{game_pk}",
        controls_prev_href=f"/ncaab/game/{game_pk}?date={cards_context.get('prev_date') or resolved_date}",
        controls_next_href=f"/ncaab/game/{game_pk}?date={cards_context.get('next_date') or resolved_date}",
        control_value=resolved_date,
        control_label="Date",
        control_type="date",
        control_name="date",
    )