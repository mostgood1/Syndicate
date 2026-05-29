from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.nba.cards import build_cards_api_payload
from syndicate.features.nba.cards import build_cards_page_context
from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


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
    href = str(game.get("href") or f"/nba/cards?date={selected_date}").strip()
    metrics = _metric_rows(game)
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _safe_text(game.get("status") or game.get("status_badge"), "Live Lens"),
        "badge": badge,
        "meta": _safe_text(game.get("detail"), selected_date),
        "away_logo": str(away.get("logo") or game.get("away_logo") or "").strip() or None,
        "home_logo": str(home.get("logo") or game.get("home_logo") or "").strip() or None,
        "metrics": metrics,
        "summary": _safe_text(game.get("summary"), "NBA live lens row."),
        "list_items": _signal_items(game),
        "href": href,
        "href_label": _safe_text(game.get("href_label"), "Open NBA game"),
    }


def build_live_lens_page_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    requested_date = str(cards_context.get("requested_date") or selected_date).strip() or selected_date
    resolved_date = str(cards_context.get("date") or selected_date).strip() or selected_date
    resolved_season = int(season) if season is not None else parse_iso_date(resolved_date).year
    normalized_profile = str(profile or "").strip().lower() or None
    games = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    rank_cards = [_rank_card(game, resolved_date) for game in games if isinstance(game, dict)]
    prop_signal_count = sum(
        len(game.get("shared_prop_rows") or [])
        for game in games
        if isinstance(game, dict) and isinstance(game.get("shared_prop_rows"), list)
    )
    top_play_count = sum(
        len(game.get("shared_top_play_rows") or [])
        for game in games
        if isinstance(game, dict) and isinstance(game.get("shared_top_play_rows"), list)
    )
    warning_panel = {
        "eyebrow": "Artifact-backed lens",
        "title": "NBA live lens now runs off the same cards artifact used by the main board",
        "body": "This route surfaces the current saved game and prop signals for the selected NBA slate instead of dropping into the settled audit surface.",
        "list_items": [
            f"Games surfaced: {len(games)}",
            f"Top-play signals surfaced: {top_play_count}",
            f"Prop signals surfaced: {prop_signal_count}",
        ],
    }
    if not rank_cards:
        warning_panel = {
            "eyebrow": "NBA live lens",
            "title": "No stored NBA live-lens rows were available for this date",
            "body": "The live-lens board only renders saved NBA cards and props snapshot artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {requested_date}"],
        }

    route_path = "/nba/live-lens"
    hidden_fields: list[dict[str, str]] | None = None
    prev_href = None
    next_href = None
    if season is not None:
        route_path = f"/nba/season/{resolved_season}/live-lens"
        query_suffix = f"&profile={normalized_profile}" if normalized_profile else ""
        hidden_fields = [{"name": "profile", "value": normalized_profile}] if normalized_profile else None
        prev_href = f"{route_path}?date={cards_context.get('prev_date') or requested_date}{query_suffix}"
        next_href = f"{route_path}?date={cards_context.get('next_date') or requested_date}{query_suffix}"

    return build_rank_page_context(
        selected_date=resolved_date,
        route_path=route_path,
        intro_title="NBA Live Lens",
        intro_body="NBA live lens now reuses the shared cards contract so the route surfaces actual game and prop signals instead of a settled audit shell.",
        aria_label="NBA live lens board",
        source_path=str(cards_context.get("source_path") or "NBA cards artifact"),
        source_title="NBA live game and props lens" if rank_cards else "NBA live lens unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(games))},
            {"label": "Top plays", "value": str(top_play_count)},
            {"label": "Prop signals", "value": str(prop_signal_count)},
            {"label": "Source", "value": Path(str(cards_context.get('source_path') or '')).name if cards_context.get("source_path") else "Fallback"},
        ],
        module_links=build_module_links(resolved_date, "Live Lens"),
        warning_panel=warning_panel,
        hidden_fields=hidden_fields,
        prev_href=prev_href,
        next_href=next_href,
        empty_state={
            "eyebrow": "NBA live lens",
            "title": "No stored NBA live-lens rows were available for this date",
            "body": "The live-lens board only renders saved NBA cards and props snapshot artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {requested_date}"],
        } if not rank_cards else None,
    )


def build_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    return build_cards_api_payload(selected_date)