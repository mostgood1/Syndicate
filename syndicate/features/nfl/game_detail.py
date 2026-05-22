from __future__ import annotations

from syndicate.features.nfl.cards import build_cards_page_context
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.shared.game_board_contract import build_single_game_board_context


def build_game_detail_page_context(selected_week: int, game_pk: str, *, season: int | None = None) -> dict:
    cards_context = build_cards_page_context(selected_week, season=season)
    week_label = cards_context["date"]
    resolved_week = int(cards_context.get("control_value") or selected_week)
    resolved_season = int(cards_context.get("header_stats", [{}, {"value": 0}])[1].get("value") or 0)
    games = cards_context.get("games") or []
    game = next((item for item in games if str(item.get("gamePk")) == str(game_pk)), None)
    using_sample_data = False
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": "NFL game unavailable",
            "detail": week_label,
            "summary": "No stored NFL weekly snapshot card was available for this season, week, and game id.",
            "metrics": [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Season", "value": str(resolved_season)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Game unavailable",
                    "title": "No saved NFL game card",
                    "body": "Syndicate could not find a stored NFL weekly snapshot card for this season, week, and game id.",
                    "items": ["Return to the NFL cards board to choose a week with saved snapshot output."],
                }
            ],
        }
        game["detail"] = week_label
    game["href"] = f"/nfl/cards?season={resolved_season}&week={resolved_week}"
    game["href_label"] = "Back to NFL cards"

    return build_single_game_board_context(
        selected_date=week_label,
        prev_date=str(cards_context.get("prev_date") or resolved_week),
        next_date=str(cards_context.get("next_date") or resolved_week),
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(resolved_week, "Cards", season=resolved_season),
        source_path=str(cards_context.get("source_path") or "NFL weekly recommendation snapshot"),
        source_title="NFL weekly snapshot game card" if game.get("status") != "NFL game unavailable" else "NFL game unavailable",
        using_sample_data=using_sample_data,
        route_path=f"/nfl/game/{game_pk}",
        intro_title=f"NFL Game {game_pk}",
        intro_body="This NFL drill-in keeps the shared Syndicate board shell but narrows the stored weekly snapshot board down to a single matchup.",
        cards_grid_class="cards-grid",
        cards_stylesheet=None,
        teaser={
            "label": "NFL picks",
            "body": "Use the weekly picks board for the saved recommendation snapshot across this NFL week.",
            "href": f"/nfl/picks?season={resolved_season}&week={resolved_week}",
            "cta": "Open NFL picks",
        },
        sport="nfl",
        module="game_detail",
        control_action=f"/nfl/game/{game_pk}",
        controls_prev_href=f"/nfl/game/{game_pk}?season={resolved_season}&week={cards_context.get('prev_date') or resolved_week}",
        controls_next_href=f"/nfl/game/{game_pk}?season={resolved_season}&week={cards_context.get('next_date') or resolved_week}",
        control_value=str(resolved_week),
        control_label="Week",
        control_type="number",
        control_name="week",
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
    )