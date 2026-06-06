from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.nba.cards import build_cards_page_context
from syndicate.features.nba.cards import build_live_lines_payload
from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _format_signed_number(value: float | None) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{value:+.0f}"
    return f"{value:+.1f}"


def _live_line_snapshot(game: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(game, dict):
        return {}
    lines = game.get("lines") if isinstance(game.get("lines"), dict) else {}
    total = _safe_number(game.get("total"))
    if total is None:
        total = _safe_number(lines.get("total"))
    home_spread = _safe_number(game.get("home_spread"))
    if home_spread is None:
        home_spread = _safe_number(lines.get("home_spread"))
    away_spread = _safe_number(game.get("away_spread"))
    if away_spread is None:
        away_spread = _safe_number(lines.get("away_spread"))
    return {
        "total": total,
        "home_spread": home_spread,
        "away_spread": away_spread,
    }


def _live_line_map(selected_date: str, games: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    event_ids = [
        str(game.get("event_id") or "").strip()
        for game in games
        if isinstance(game, dict) and str(game.get("event_id") or "").strip()
    ]
    if not event_ids:
        return {}
    payload = build_live_lines_payload(selected_date, event_ids)
    live_games = payload.get("games") if isinstance(payload.get("games"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for live_game in live_games:
        if not isinstance(live_game, dict):
            continue
        event_id = str(live_game.get("event_id") or "").strip()
        snapshot = _live_line_snapshot(live_game)
        if event_id and any(snapshot.get(key) is not None for key in ("total", "home_spread", "away_spread")):
            out[event_id] = snapshot
    return out


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


def _signal_items(game: dict[str, Any], *, limit: int = 6) -> list[str]:
    panels = game.get("panels") if isinstance(game.get("panels"), list) else []
    panel_items: list[str] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        eyebrow = _safe_text(panel.get("eyebrow"), "").strip()
        title = _safe_text(panel.get("title"), "").strip()
        body = _safe_text(panel.get("body"), "").strip()
        summary_stats = panel.get("summary_stats") if isinstance(panel.get("summary_stats"), list) else []
        items = panel.get("items") if isinstance(panel.get("items"), list) else []
        table_groups = panel.get("table_groups") if isinstance(panel.get("table_groups"), list) else []

        if eyebrow or title or body:
            head = f"{eyebrow}: {title}" if eyebrow and title else title or eyebrow
            if body:
                panel_items.append(f"{head} | {body}" if head else body)
            elif head:
                panel_items.append(head)

        for stat in summary_stats[:2]:
            if not isinstance(stat, dict):
                continue
            label = _safe_text(stat.get("label"), "Stat")
            value = _safe_text(stat.get("value"), "-")
            panel_items.append(f"{label} {value}")

        for item in items[:2]:
            cleaned = _safe_text(item, "").strip()
            if cleaned:
                panel_items.append(cleaned)

        for group in table_groups[:1]:
            if not isinstance(group, dict):
                continue
            rows = group.get("rows") if isinstance(group.get("rows"), list) else []
            for row in rows[:1]:
                if not isinstance(row, dict):
                    continue
                row_title = _safe_text(row.get("title") or row.get("name") or row.get("player"), "")
                row_detail = _safe_text(row.get("detail") or row.get("summary") or row.get("meta"), "")
                if row_title and row_detail:
                    panel_items.append(f"{row_title} | {row_detail}")
                elif row_title:
                    panel_items.append(row_title)
                elif row_detail:
                    panel_items.append(row_detail)

    if panel_items:
        seen_panel_items: set[str] = set()
        deduped_panel_items: list[str] = []
        for item in panel_items:
            cleaned = str(item or "").strip()
            if not cleaned or cleaned in seen_panel_items:
                continue
            seen_panel_items.add(cleaned)
            deduped_panel_items.append(cleaned)
        if deduped_panel_items:
            return deduped_panel_items[:limit]

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


def _rank_card(game: dict[str, Any], selected_date: str, *, live_lines: dict[str, Any] | None = None) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    away_score = _safe_number(away.get("score"))
    home_score = _safe_number(home.get("score"))
    current_total = (away_score + home_score) if away_score is not None and home_score is not None else None
    lines = live_lines if isinstance(live_lines, dict) else {}
    live_total = _safe_number(lines.get("total"))
    live_home_spread = _safe_number(lines.get("home_spread"))
    if live_home_spread is None:
        live_home_spread = _safe_number(betting.get("home_spread"))
    badge = _safe_text((((top_rows or [None])[0] or {}).get("value") if top_rows else None), "Watch")
    href = str(game.get("href") or f"/nba/cards?date={selected_date}").strip()
    metrics = _metric_rows(game)
    if current_total is not None:
        metrics = [{"label": "Total pts", "value": str(int(round(current_total)))}] + metrics
    if live_total is not None:
        metrics = [{"label": "Live total", "value": f"{live_total:.1f}"}] + metrics
    if live_home_spread is not None:
        metrics = [{"label": "Live ATS", "value": f"{_safe_text(home.get('abbr'), 'HOM')} {_format_signed_number(live_home_spread)}"}] + metrics
    summary = _safe_text(game.get("summary"), "NBA live lens row.")
    if current_total is not None and live_total is not None and live_home_spread is not None:
        summary = f"Total pts {int(round(current_total))} vs Live total {live_total:.1f} and Live ATS {_safe_text(home.get('abbr'), 'HOM')} {_format_signed_number(live_home_spread)}. {summary}"
    elif current_total is not None and live_total is not None:
        summary = f"Total pts {int(round(current_total))} vs Live total {live_total:.1f}. {summary}"
    elif live_home_spread is not None:
        summary = f"Live ATS {_safe_text(home.get('abbr'), 'HOM')} {_format_signed_number(live_home_spread)}. {summary}"
    elif current_total is not None:
        summary = f"Total pts {int(round(current_total))}. {summary}"
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _safe_text(game.get("status") or game.get("status_badge"), "Live Lens"),
        "badge": badge,
        "meta": _safe_text(game.get("detail"), selected_date),
        "away_logo": str(away.get("logo") or game.get("away_logo") or "").strip() or None,
        "home_logo": str(home.get("logo") or game.get("home_logo") or "").strip() or None,
        "metrics": metrics,
        "summary": summary,
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
    live_line_by_event_id = _live_line_map(resolved_date, games)
    rank_cards = [
        _rank_card(game, resolved_date, live_lines=live_line_by_event_id.get(str(game.get("event_id") or "").strip()))
        for game in games
        if isinstance(game, dict)
    ]
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
    cards_context = build_cards_page_context(selected_date)
    payload = build_rank_api_payload(build_live_lens_page_context(selected_date))
    payload["requested_date"] = cards_context.get("requested_date")
    payload["lookahead_applied"] = bool(cards_context.get("lookahead_applied"))
    payload["players_included"] = False
    payload["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    payload["games"] = [dict(game) for game in (cards_context.get("games") or []) if isinstance(game, dict)]
    return payload