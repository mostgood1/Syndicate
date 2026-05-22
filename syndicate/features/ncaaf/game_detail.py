from __future__ import annotations

from syndicate.features.ncaaf.cards import build_cards_page_context
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.shared.game_board_contract import build_single_game_board_context


def build_game_detail_page_context(selected_week: int, game_pk: str) -> dict:
    cards_context = build_cards_page_context(selected_week)
    week_label = cards_context["date"]
    resolved_week = int(cards_context.get("control_value") or selected_week)
    games = cards_context.get("games") or []
    game = next((item for item in games if str(item.get("gamePk")) == str(game_pk)), None)
    using_sample_data = False
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": "NCAAF game unavailable",
            "detail": week_label,
            "summary": "No stored NCAAF summary-backed game card was available for this week and game id.",
            "metrics": [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Game unavailable",
                    "title": "No saved NCAAF game card",
                    "body": "Syndicate could not find a stored weekly summary-backed NCAAF card for this week and game id.",
                    "items": ["Return to the NCAAF cards board to choose a week with saved summary artifacts."],
                }
            ],
        }
    game["href"] = f"/ncaaf/cards?week={resolved_week}"
    game["href_label"] = "Back to NCAAF cards"

    return build_single_game_board_context(
        selected_date=week_label,
        prev_date=str(cards_context.get("prev_date") or resolved_week),
        next_date=str(cards_context.get("next_date") or resolved_week),
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(resolved_week, "Cards"),
        source_path=str(cards_context.get("source_path") or "NCAAF recommendations summary"),
        source_title="NCAAF summary-backed game card" if game.get("status") != "NCAAF game unavailable" else "NCAAF game unavailable",
        using_sample_data=using_sample_data,
        route_path=f"/ncaaf/game/{game_pk}",
        intro_title=f"NCAAF Game {game_pk}",
        intro_body="This first NCAAF drill-in keeps the shared board shell but narrows the weekly summary-backed cards surface to one matchup.",
        cards_grid_class="cards-grid",
        cards_stylesheet=None,
        teaser={
            "label": "NCAAF picks",
            "body": "Use the picks board for the ranked weekly recommendation rows behind this matchup card.",
            "href": f"/ncaaf/picks?week={resolved_week}",
            "cta": "Open NCAAF picks",
        },
        sport="ncaaf",
        module="game_detail",
        control_action=f"/ncaaf/game/{game_pk}",
        controls_prev_href=f"/ncaaf/game/{game_pk}?week={cards_context.get('prev_date') or resolved_week}",
        controls_next_href=f"/ncaaf/game/{game_pk}?week={cards_context.get('next_date') or resolved_week}",
        control_value=str(resolved_week),
        control_label="Week",
        control_type="number",
        control_name="week",
    )