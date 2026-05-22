from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.nfl.cards import build_cards_page_context
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.shared.rank_board import build_rank_page_context


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _rank_card(game: dict[str, Any]) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    metrics = game.get("metrics") if isinstance(game.get("metrics"), list) else []
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    badge = _safe_text((((top_rows or [None])[0] or {}).get("value") if top_rows else None), "Watch")
    list_items = []
    for row in top_rows[:4]:
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
        list_items = ["No stored live bet signals were available for this matchup."]
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _safe_text(game.get("status"), "Weekly board"),
        "badge": badge,
        "meta": _safe_text(game.get("detail"), "Week board"),
        "metrics": [metric for metric in metrics[:4] if isinstance(metric, dict)],
        "summary": _safe_text(game.get("summary"), "NFL live lens row."),
        "list_items": list_items,
        "href": _safe_text(game.get("href"), "/nfl/cards"),
        "href_label": _safe_text(game.get("href_label"), "Open NFL game detail"),
    }


def build_live_lens_page_context(selected_week: int, *, season: int) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_week, season=season)
    resolved_week = int(cards_context.get("control_value") or cards_context.get("week") or selected_week)
    resolved_season = int(season)
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    rank_cards = [_rank_card(game) for game in games if isinstance(game, dict)]
    warning_panel = {
        "eyebrow": "Cards-backed lens",
        "title": "NFL live lens now uses the same game-card contract that feeds the home game signals",
        "body": "This route no longer reuses the picks board. It reads the snapshot-backed cards payload so matchup-level edges and context stay aligned with the shared game board.",
        "list_items": [f"Games surfaced: {len(games)}", f"Season: {resolved_season} Week {resolved_week}"],
    }
    if not rank_cards:
        warning_panel = {
            "eyebrow": "NFL live lens",
            "title": "No NFL live-lens rows were available for this week",
            "body": "The live-lens board only renders stored weekly snapshot card rows, and none were available for the requested season and week.",
            "list_items": [f"Season: {resolved_season}", f"Week: {selected_week}"],
        }

    context = build_rank_page_context(
        selected_date=f"{resolved_season} Week {resolved_week}",
        route_path="/nfl/live-lens",
        intro_title="NFL Live Lens",
        intro_body="NFL live lens now uses the shared snapshot-backed cards contract so weekly matchup signals and home-board game rails stay aligned.",
        aria_label="NFL live lens board",
        source_path=str(cards_context.get("source_path") or "NFL weekly recommendation snapshot"),
        source_title="NFL live game lens" if rank_cards else "NFL live lens unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(games))},
            {"label": "Season", "value": str(resolved_season)},
            {"label": "Week", "value": str(resolved_week)},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "API"},
        ],
        module_links=build_module_links(resolved_week, "Live Lens", season=resolved_season),
        warning_panel=warning_panel,
        source_date_display=f"{resolved_season} Week {resolved_week}",
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
        prev_href=f"/nfl/live-lens?season={resolved_season}&week={cards_context.get('prev_date') or resolved_week}",
        next_href=f"/nfl/live-lens?season={resolved_season}&week={cards_context.get('next_date') or resolved_week}",
        reset_href=f"/nfl/live-lens?season={resolved_season}",
        empty_state={
            "eyebrow": "NFL live lens",
            "title": "No NFL live-lens rows were available for this week",
            "body": "The live-lens board only renders stored weekly snapshot card rows, and none were available for the requested season and week.",
            "list_items": [f"Season: {resolved_season}", f"Week: {selected_week}"],
        } if not rank_cards else None,
    )
    context["season"] = resolved_season
    context["week"] = resolved_week
    context["available_weeks"] = available_weeks(resolved_season)
    context["rows"] = len(rank_cards)
    context["data"] = rank_cards
    context["groups"] = {"Games": rank_cards}
    context["have_data"] = bool(rank_cards)
    return context