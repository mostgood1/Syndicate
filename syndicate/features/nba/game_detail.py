from __future__ import annotations

from datetime import timedelta

from syndicate.features.nba.cards import _game_by_id_from_artifacts
from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.shared.game_board_contract import build_single_game_board_context


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
            "status": "NBA game unavailable",
            "detail": selected_date,
            "summary": "No processed NBA game detail artifact was available for this date and game id.",
            "metrics": [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Date", "value": selected_date},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Game unavailable",
                    "title": "No saved game detail artifact",
                    "body": "Syndicate could not find a stored NBA game card for this date and game id.",
                    "items": ["Return to the NBA cards board to pick a date with stored artifacts."],
                }
            ],
            "href": f"/nba/cards?date={selected_date}",
            "href_label": "Back to NBA cards",
        }

    return build_single_game_board_context(
        selected_date=selected_date,
        prev_date=prev_date,
        next_date=next_date,
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(selected_date, "Cards"),
        source_path=str(bundle["paths"]["cards"]),
        source_title="NBA processed game cards" if game.get("status") != "NBA game unavailable" else "NBA game unavailable",
        using_sample_data=using_sample_data,
        route_path=f"/nba/game/{game_pk}",
        intro_title=f"NBA Game {game_pk}",
        intro_body="This next NBA Syndicate pass turns board navigation into a real single-game artifact-backed surface rather than dead-ending at the cards page.",
        cards_grid_class="wnba-cards-grid",
        cards_stylesheet="nba/cards.css",
        teaser={
            "label": "NBA cards board",
            "body": "Use the full cards board for the rest of the slate on this date.",
            "href": f"/nba/cards?date={selected_date}",
            "cta": "Back to NBA cards",
        },
        sport="nba",
        module="game_detail",
    )
