from __future__ import annotations

from datetime import timedelta

from syndicate.features.wnba.cards import _game_by_id_from_artifacts
from syndicate.features.shared.game_board_contract import build_single_game_board_context
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import parse_iso_date


def build_game_detail_page_context(selected_date: str, game_pk: str) -> dict:
    parsed_date = parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    game, bundle = _game_by_id_from_artifacts(selected_date, game_pk)
    using_sample_data = False
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": "WNBA game unavailable",
            "detail": selected_date,
            "summary": "No processed WNBA game detail artifact was available for this date and game id.",
            "metrics": [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Date", "value": selected_date},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Game unavailable",
                    "title": "No saved game detail artifact",
                    "body": "Syndicate could not find a stored WNBA game card for this date and game id.",
                    "items": ["Return to the WNBA cards board to pick a date with stored artifacts."],
                }
            ],
            "href": f"/wnba/cards?date={selected_date}",
            "href_label": "Back to WNBA cards",
        }

    return build_single_game_board_context(
        selected_date=selected_date,
        prev_date=prev_date,
        next_date=next_date,
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(selected_date, "Cards"),
        source_path=str(bundle["paths"]["cards"]),
        source_title="WNBA processed game cards" if game.get("status") != "WNBA game unavailable" else "WNBA game unavailable",
        using_sample_data=using_sample_data,
        route_path=f"/wnba/game/{game_pk}",
        intro_title=f"WNBA Game {game_pk}",
        intro_body="This first WNBA Syndicate pass turns the card drill-in into a real artifact-backed game surface instead of sending users to a neighboring module.",
        cards_grid_class="wnba-cards-grid",
        cards_stylesheet="wnba/cards.css",
        teaser={
            "label": "WNBA picks",
            "body": "Use the picks module for the strongest slate-wide recommendations on this date.",
            "href": f"/wnba/picks?date={selected_date}",
            "cta": "Open WNBA picks",
        },
        sport="wnba",
        module="game_detail",
    )