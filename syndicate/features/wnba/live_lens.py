from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.wnba.cards import build_cards_page_context
from syndicate.features.wnba.sources import build_module_links


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _metric_rows(game: dict[str, Any], *, limit: int = 4) -> list[dict[str, str]]:
    metrics = game.get("metrics") if isinstance(game.get("metrics"), list) else []
    rows: list[dict[str, str]] = []
    for metric in metrics[:limit]:
        if not isinstance(metric, dict):
            continue
        rows.append(
            {
                "label": _safe_text(metric.get("label"), "Signal"),
                "value": _safe_text(metric.get("value"), "-"),
            }
        )
    return rows


def _signal_items(game: dict[str, Any], *, limit: int = 4) -> list[str]:
    rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    items: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = _safe_text(row.get("name"), "Play")
        value = _safe_text(row.get("value"), "-")
        detail = _safe_text(row.get("detail"), "")
        rendered = name
        if value != "-":
            rendered = f"{rendered} | {value}"
        if detail:
            rendered = f"{rendered} | {detail}"
        items.append(rendered)
    if items:
        return items
    prop_rows = game.get("shared_prop_rows") if isinstance(game.get("shared_prop_rows"), list) else []
    for row in prop_rows[:limit]:
        if not isinstance(row, dict):
            continue
        items.append(f"{_safe_text(row.get('name'), 'Prop')} | {_safe_text(row.get('value'), '-')}")
    return items or ["No live lens signals were stored for this matchup."]


def _rank_card(game: dict[str, Any], selected_date: str) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    badge = _safe_text((((top_rows or [None])[0] or {}).get("value") if top_rows else None), "Watch")
    href = str(game.get("href") or f"/wnba/cards?date={selected_date}").strip()
    metrics = _metric_rows(game)
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _safe_text(game.get("status"), "Stored lens"),
        "badge": badge,
        "meta": _safe_text(game.get("detail"), selected_date),
        "metrics": metrics,
        "summary": _safe_text(game.get("summary"), "WNBA live lens row."),
        "list_items": _signal_items(game),
        "href": href,
        "href_label": _safe_text(game.get("href_label"), "Open WNBA game"),
    }


def build_live_lens_page_context(selected_date: str) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    resolved_date = str(cards_context.get("date") or selected_date).strip() or selected_date
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    rank_cards = [
        _rank_card(game, resolved_date)
        for game in games
        if isinstance(game, dict)
    ]
    prop_signal_count = sum(
        len(game.get("shared_prop_rows") or [])
        for game in games
        if isinstance(game, dict) and isinstance(game.get("shared_prop_rows"), list)
    )
    warning_panel = {
        "eyebrow": "Artifact-backed lens",
        "title": "WNBA live lens now runs off the same cards and props snapshots as the home rails",
        "body": "This route no longer points at standalone sim leaders. It reads the actual shared game-board artifact so live game and prop signals stay aligned with the card lane.",
        "list_items": [
            f"Games surfaced: {len(games)}",
            f"Prop signals surfaced: {prop_signal_count}",
        ],
    }
    if not rank_cards:
        warning_panel = {
            "eyebrow": "WNBA live lens",
            "title": "No stored WNBA live-lens rows were available for this date",
            "body": "The live-lens board only renders saved WNBA cards and props snapshot artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {selected_date}"],
        }

    return build_rank_page_context(
        selected_date=resolved_date,
        route_path="/wnba/live-lens",
        intro_title="WNBA Live Lens",
        intro_body="WNBA live lens now reuses the shared cards contract so the route surfaces actual game and prop signals instead of a separate sim-leaders-only page.",
        aria_label="WNBA live lens board",
        source_path=str(cards_context.get("source_path") or "WNBA cards artifact"),
        source_title="WNBA live game and props lens" if rank_cards else "WNBA live lens unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(games))},
            {"label": "Prop signals", "value": str(prop_signal_count)},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "Fallback"},
        ],
        module_links=build_module_links(resolved_date, "Live Lens"),
        warning_panel=warning_panel,
        empty_state={
            "eyebrow": "WNBA live lens",
            "title": "No stored WNBA live-lens rows were available for this date",
            "body": "The live-lens board only renders saved WNBA cards and props snapshot artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {selected_date}"],
        } if not rank_cards else None,
    )


def build_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    return {
        "date": cards_context.get("date"),
        "requested_date": cards_context.get("requested_date"),
        "lookahead_applied": bool(cards_context.get("lookahead_applied")),
        "players_included": False,
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "games": [dict(game) for game in (cards_context.get("games") or []) if isinstance(game, dict)],
    }