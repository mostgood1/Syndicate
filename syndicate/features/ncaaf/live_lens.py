from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context
from syndicate.features.ncaaf.cards import build_cards_page_context
from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.rank_board import build_rank_page_context


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _rank_card(game: dict[str, Any]) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    metrics = game.get("metrics") if isinstance(game.get("metrics"), list) else []
    badge = _safe_text(((metrics[4] or {}).get("value") if len(metrics) > 4 and isinstance(metrics[4], dict) else None), "Watch")
    signal_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    list_items = []
    for row in signal_rows[:4]:
        if not isinstance(row, dict):
            continue
        list_items.append(
            " | ".join(
                part
                for part in [
                    _safe_text(row.get("name"), "Signal"),
                    _safe_text(row.get("value"), "-"),
                    _safe_text(row.get("detail"), ""),
                ]
                if part and part != "-"
            )
        )
    if not list_items:
        list_items = ["No stored matchup signals were available for this game."]
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _safe_text(game.get("status"), "Weekly board"),
        "badge": badge,
        "meta": _safe_text(game.get("detail"), "Historical summary"),
        "metrics": [metric for metric in metrics[:4] if isinstance(metric, dict)],
        "summary": _safe_text(game.get("summary"), "NCAAF live lens row."),
        "list_items": list_items,
        "href": _safe_text(game.get("href"), "/ncaaf/cards"),
        "href_label": _safe_text(game.get("href_label"), "Open NCAAF game detail"),
    }


def _runtime_rank_card(game: dict[str, Any]) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    ncaaf_card = game.get("ncaaf_card") if isinstance(game.get("ncaaf_card"), dict) else {}
    scoreboard = ncaaf_card.get("scoreboard") if isinstance(ncaaf_card.get("scoreboard"), dict) else {}
    summary = ncaaf_card.get("summary") if isinstance(ncaaf_card.get("summary"), dict) else {}
    metrics = [
        {"label": "Home mean", "value": scoreboard.get("home_points") or "-"},
        {"label": "Away mean", "value": scoreboard.get("away_points") or "-"},
        {"label": "Projected spread", "value": scoreboard.get("spread_label") or "-"},
        {"label": "Projected total", "value": scoreboard.get("total_points") or "-"},
    ]
    list_items = [
        f"Predicted final: {home.get('abbr', 'HOM')} {scoreboard.get('home_points') or '-'} - {scoreboard.get('away_points') or '-'} {away.get('abbr', 'AWY')}",
        f"Projected spread: {scoreboard.get('spread_label') or '-'}",
        f"Projected total: {scoreboard.get('total_points') or '-'}",
        f"Win probability: {scoreboard.get('win_probability') or '-'}",
    ]
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": "SmartSim runtime",
        "badge": _safe_text(scoreboard.get("win_probability"), "Watch"),
        "meta": _safe_text(scoreboard.get("source_label"), "SmartSim runtime"),
        "metrics": metrics,
        "summary": _safe_text(game.get("summary"), "NCAAF live lens row."),
        "list_items": list_items,
        "href": _safe_text(game.get("href"), "/ncaaf/cards"),
        "href_label": _safe_text(game.get("href_label"), "Open NCAAF game detail"),
        "live_lens_note": _safe_text(summary.get("ready_label"), "SmartSim runtime"),
    }


def build_live_lens_page_context(selected_week: int) -> dict[str, object]:
    cards_context = build_cards_page_context(selected_week)
    resolved_week = int(cards_context.get("control_value") or selected_week)
    season = int(str(cards_context.get("date") or "0").split()[0] or 0)
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    rank_cards = [_rank_card(game) for game in games if isinstance(game, dict)]
    warning_panel = {
        "eyebrow": "Cards-backed lens",
        "title": "NCAAF live lens now uses the shared game-card contract",
        "body": "This route no longer reuses the picks board. It reads the weekly game-card summary so matchup signals stay aligned with the home game rails when football is in season.",
        "list_items": [f"Season: {season}", f"Week: {resolved_week}", f"Games surfaced: {len(games)}"],
    }
    if not rank_cards:
        warning_panel = {
            "eyebrow": "NCAAF live lens",
            "title": "No NCAAF live-lens rows were available for this week",
            "body": "The live-lens board only renders saved weekly game-card rows, and none were available for the requested week.",
            "list_items": [f"Week: {selected_week}"],
        }

    context = build_rank_page_context(
        selected_date=f"{season} Week {resolved_week}",
        route_path="/ncaaf/live-lens",
        intro_title="NCAAF Live Lens",
        intro_body="NCAAF live lens now uses the shared cards contract so weekly matchup signals and home-board game rails stay aligned.",
        aria_label="NCAAF live lens board",
        source_path=str(cards_context.get("source_path") or "NCAAF summary artifact"),
        source_title="NCAAF live game lens" if rank_cards else "NCAAF live lens unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(games))},
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(resolved_week)},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "Summary"},
        ],
        module_links=build_module_links(resolved_week, "Live Lens", season=season),
        warning_panel=warning_panel,
        source_date_display=f"{season} Week {resolved_week}",
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/ncaaf/live-lens?week={cards_context.get('prev_date') or resolved_week}",
        next_href=f"/ncaaf/live-lens?week={cards_context.get('next_date') or resolved_week}",
        reset_href="/ncaaf/live-lens",
        empty_state={
            "eyebrow": "NCAAF live lens",
            "title": "No NCAAF live-lens rows were available for this week",
            "body": "The live-lens board only renders saved weekly game-card rows, and none were available for the requested week.",
            "list_items": [f"Week: {selected_week}"],
        } if not rank_cards else None,
    )
    context["season"] = season
    context["week"] = resolved_week
    context["available_weeks"] = available_weeks()
    context["rows"] = len(rank_cards)
    context["data"] = rank_cards
    context["groups"] = {"Games": rank_cards}
    context["have_data"] = bool(rank_cards)
    return attach_live_lens_contract(context, sport="ncaaf", module="live_lens")


def build_smartsim_live_lens_page_context(selected_week: int) -> dict[str, object]:
    cards_context = build_smartsim_cards_page_context(selected_week)
    board_contract = cards_context.get("board_contract") if isinstance(cards_context.get("board_contract"), dict) else {}
    if board_contract.get("source_kind") != "smartsim_runtime":
        return build_live_lens_page_context(selected_week)

    resolved_week = int(cards_context.get("control_value") or selected_week)
    season = int(str(cards_context.get("date") or "0").split()[0] or 0)
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    rank_cards = [_runtime_rank_card(game) for game in games if isinstance(game, dict)]
    warning_panel = {
        "eyebrow": "SmartSim runtime",
        "title": "NCAAF live lens now uses runtime SmartSim cards",
        "body": "This live-lens board reads the SmartSim cards runtime first so matchup signals stay aligned with projected score, spread, total, and win probability.",
        "list_items": [f"Season: {season}", f"Week: {resolved_week}", f"Games surfaced: {len(games)}"],
    }
    if not rank_cards:
        return build_live_lens_page_context(selected_week)

    context = build_rank_page_context(
        selected_date=f"{season} Week {resolved_week}",
        route_path="/ncaaf/live-lens",
        intro_title="NCAAF Live Lens",
        intro_body="NCAAF live lens now uses SmartSim runtime cards first so the board stays aligned with the projected game shape.",
        aria_label="NCAAF live lens board",
        source_path=str(cards_context.get("source_path") or "NCAAF SmartSim predicted totals"),
        source_title="NCAAF SmartSim live lens runtime",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(games))},
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(resolved_week)},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "SmartSim"},
        ],
        module_links=build_module_links(resolved_week, "Live Lens", season=season),
        warning_panel=warning_panel,
        source_date_display=f"{season} Week {resolved_week}",
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/ncaaf/live-lens?week={cards_context.get('prev_date') or resolved_week}",
        next_href=f"/ncaaf/live-lens?week={cards_context.get('next_date') or resolved_week}",
        reset_href="/ncaaf/live-lens",
        empty_state={
            "eyebrow": "NCAAF live lens",
            "title": "No NCAAF live-lens rows were available for this week",
            "body": "The SmartSim live-lens board only renders runtime cards, and none were available for the requested week.",
            "list_items": [f"Week: {selected_week}"],
        } if not rank_cards else None,
    )
    context["season"] = season
    context["week"] = resolved_week
    context["available_weeks"] = cards_context.get("available_weeks") or available_weeks()
    context["rows"] = len(rank_cards)
    context["data"] = rank_cards
    context["groups"] = {"Games": rank_cards}
    context["have_data"] = bool(rank_cards)
    return attach_live_lens_contract(context, sport="ncaaf", module="live_lens")