from __future__ import annotations

from syndicate.features.ncaaf.cards import build_cards_page_context
from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_trial_monitoring import record_trial_page_view
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.shared.game_board_contract import build_single_game_board_context


def _team_name(game: dict, side: str) -> str:
    team = game.get(side) if isinstance(game.get(side), dict) else {}
    return str(team.get("name") or team.get("school_name") or "Unavailable").strip() or "Unavailable"


def build_game_detail_page_context(selected_week: int, game_pk: str) -> dict:
    cards_context = build_smartsim_cards_page_context(selected_week)
    if not isinstance(cards_context, dict) or cards_context.get("games") is None:
        cards_context = build_cards_page_context(selected_week)
    week_label = cards_context["date"]
    resolved_week = int(cards_context.get("control_value") or selected_week)
    games = cards_context.get("games") or []
    game = next((item for item in games if str(item.get("gamePk")) == str(game_pk)), None)
    using_sample_data = False
    game_is_unavailable = game is None
    if game is None:
        game = {
            "gamePk": str(game_pk),
            "away": {"abbr": "AWY", "name": "Unavailable"},
            "home": {"abbr": "HOM", "name": "Unavailable"},
            "status": f"{LEGACY_ENGINE_SOURCE_LABEL} game unavailable",
            "detail": week_label,
            "summary": f"No stored NCAAF {LEGACY_ENGINE_SOURCE_LABEL} game card was available for this week and game id.",
            "metrics": [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "No data"},
            ],
            "panels": [
                {
                    "eyebrow": "Game unavailable",
                    "title": "No saved NCAAF game card",
                    "body": f"Syndicate could not find a stored weekly {LEGACY_ENGINE_SOURCE_LABEL} NCAAF card for this week and game id.",
                    "items": ["Return to the NCAAF cards board to choose a week with saved runtime cards."],
                }
            ],
            "team_context": {"summary": "No context available", "items": []},
        }
    game["href"] = f"/ncaaf/cards?week={resolved_week}"
    game["href_label"] = "Back to NCAAF cards"
    if isinstance(game.get("ncaaf_card"), dict):
        scoreboard = game["ncaaf_card"].get("scoreboard") if isinstance(game["ncaaf_card"].get("scoreboard"), dict) else {}
        matchup_context = game["ncaaf_card"].get("matchup_context") if isinstance(game["ncaaf_card"].get("matchup_context"), dict) else {}
        smartsim_reasons = game["ncaaf_card"].get("smartsim_reasons") if isinstance(game["ncaaf_card"].get("smartsim_reasons"), dict) else {}
    else:
        scoreboard = {}
        matchup_context = {}
        smartsim_reasons = {}

    if scoreboard:
        try:
            season_for_monitoring = int(str(week_label or "0").split()[0])
        except (ValueError, IndexError):
            season_for_monitoring = 0
        record_trial_page_view(
            route="/ncaaf/game/<id>",
            season=season_for_monitoring,
            week=resolved_week,
            scoreboards=[scoreboard],
        )

    board_header_title = f"{_team_name(game, 'away')} @ {_team_name(game, 'home')}"
    board_header_meta = "NCAAF Game Hub | " + str(scoreboard.get("source_label") or game.get("status") or "NCAAF").strip()

    header_stats = [
        {"label": "Game", "value": f"{game['away']['abbr']} @ {game['home']['abbr']}"},
        {"label": "Projection", "value": f"{scoreboard.get('home_points') or '-'} - {scoreboard.get('away_points') or '-'}"},
        {"label": "Total", "value": str(scoreboard.get("total_points") or "-")},
        {"label": "Win Prob", "value": str(scoreboard.get("win_probability") or "-")},
    ]

    context_sections = []
    if isinstance(game.get("ncaaf_card"), dict):
        context_sections = game["ncaaf_card"].get("context_sections") if isinstance(game["ncaaf_card"].get("context_sections"), list) else []

    if matchup_context:
        game["matchup_context"] = matchup_context
    if smartsim_reasons:
        game["smartsim_reasons"] = smartsim_reasons

    detail_context = build_single_game_board_context(
        selected_date=week_label,
        prev_date=str(cards_context.get("prev_date") or resolved_week),
        next_date=str(cards_context.get("next_date") or resolved_week),
        game=game,
        game_pk=game_pk,
        module_links=build_module_links(resolved_week, "Cards"),
        source_path=str(cards_context.get("source_path") or f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} cards runtime"),
        source_title="NCAAF game unavailable" if game_is_unavailable else f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} game hub",
        using_sample_data=using_sample_data,
        route_path=f"/ncaaf/game/{game_pk}",
        intro_title="NCAAF Game Hub",
        intro_body="NCAAF Game Hub surfaces the projection, the evidence behind it, and the matchup context that explains why the model leans the way it does.",
        cards_grid_class="cards-grid",
        cards_stylesheet=None,
        teaser={
            "label": "NCAAF picks",
            "body": "Use the picks board for ranked recommendation rows that sit behind this game hub.",
            "href": f"/ncaaf/picks?week={resolved_week}",
            "cta": "Open NCAAF picks",
        },
        sport="ncaaf",
        module="game_detail",
        header_stats=header_stats,
        control_action=f"/ncaaf/game/{game_pk}",
        controls_prev_href=f"/ncaaf/game/{game_pk}?week={cards_context.get('prev_date') or resolved_week}",
        controls_next_href=f"/ncaaf/game/{game_pk}?week={cards_context.get('next_date') or resolved_week}",
        control_value=str(resolved_week),
        control_label="Week",
        control_type="number",
        control_name="week",
    )
    detail_context.update(
        {
            "board_header_title": board_header_title,
            "board_header_meta": board_header_meta,
            "cards_header_title": board_header_title,
            "cards_header_meta": board_header_meta,
            "show_source_summary": True,
            "show_smartsim_reasons": bool(smartsim_reasons.get("items")),
            "show_matchup_context": bool(matchup_context.get("items")),
            "smartsim_reasons": smartsim_reasons,
            "matchup_context": matchup_context,
            "source_title": "NCAAF game unavailable" if game_is_unavailable else f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} game hub",
            "source_path": str(cards_context.get("source_path") or f"NCAAF {LEGACY_ENGINE_SOURCE_LABEL} cards runtime"),
            "header_stats": header_stats,
        }
    )
    if context_sections:
        game["context_sections"] = context_sections
    return detail_context