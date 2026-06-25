from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any

from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.wnba.cards import build_cards_page_context
from syndicate.features.wnba.cards import build_live_lines_payload
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import load_json


LIVE_LENS_SNAPSHOT_PATH = Path("/opt/render/project/data/live/wnba_live_lens.json")


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _live_line_value(game: dict[str, Any]) -> float | None:
    if not isinstance(game, dict):
        return None
    if game.get("total") is not None:
        return _safe_number(game.get("total"))
    lines = game.get("lines") if isinstance(game.get("lines"), dict) else {}
    if lines.get("total") is not None:
        return _safe_number(lines.get("total"))
    return None


def _live_line_map(selected_date: str, games: list[dict[str, Any]]) -> dict[str, float]:
    return {}


def _load_live_lens_snapshot() -> dict[str, Any] | None:
    payload = load_json(LIVE_LENS_SNAPSHOT_PATH)
    return payload if isinstance(payload, dict) else None


def _live_lens_snapshot_is_current(snapshot: dict[str, Any] | None, selected_date: str) -> bool:
    if not validate_live_lens_snapshot(snapshot):
        return False
    snapshot_date = str((snapshot or {}).get("date") or "").strip()
    requested_date = str(selected_date or "").strip()
    if not snapshot_date or not requested_date:
        return False
    if requested_date == central_today_iso() and snapshot_date != requested_date:
        return False
    return True


def _snapshot_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _snapshot_text(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = str(payload.get(key) or "").strip()
    return value or fallback


def _snapshot_context(selected_date: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = payload if isinstance(payload, dict) else {}
    resolved_date = str(snapshot.get("date") or selected_date).strip() or selected_date
    rank_cards = [dict(card) for card in _snapshot_list(snapshot, "rank_cards") if isinstance(card, dict)]
    if not rank_cards:
        rank_cards = [dict(card) for card in _snapshot_list(snapshot, "cards") if isinstance(card, dict)]
    games = [dict(game) for game in _snapshot_list(snapshot, "games") if isinstance(game, dict)]
    source_path = str(snapshot.get("source_path") or LIVE_LENS_SNAPSHOT_PATH).strip()
    header_stats = [dict(item) for item in _snapshot_list(snapshot, "header_stats") if isinstance(item, dict)]
    if not header_stats:
        header_stats = [
            {"label": "Games", "value": str(len(games))},
            {"label": "Cards", "value": str(len(rank_cards))},
            {"label": "Source", "value": Path(source_path).name if source_path else "Fallback"},
        ]
    warning_panel = snapshot.get("warning_panel") if isinstance(snapshot.get("warning_panel"), dict) else None
    empty_state = snapshot.get("empty_state") if isinstance(snapshot.get("empty_state"), dict) else None
    if warning_panel is None:
        if rank_cards:
            warning_panel = {
                "eyebrow": "Artifact-backed lens",
                "title": "WNBA live lens is reading the stored snapshot artifact",
                "body": "The route serves the published WNBA live-lens snapshot directly instead of recomputing rank cards on request.",
                "list_items": [
                    f"Games surfaced: {len(games)}",
                    f"Cards surfaced: {len(rank_cards)}",
                ],
            }
        else:
            warning_panel = {
                "eyebrow": "WNBA live lens",
                "title": "No stored WNBA live-lens rows were available for this date",
                "body": "The route only reads the published WNBA live-lens snapshot artifact, and none was available for the requested date.",
                "list_items": [f"Requested date: {selected_date}"],
            }
    if empty_state is None and not rank_cards:
        empty_state = {
            "eyebrow": "WNBA live lens",
            "title": "No stored WNBA live-lens snapshot was available for this date",
            "body": "The route only reads the published WNBA live-lens snapshot artifact, and no snapshot was present for the requested date.",
            "list_items": [f"Requested date: {selected_date}"],
        }

    context = build_rank_page_context(
        selected_date=resolved_date,
        route_path="/wnba/live-lens",
        intro_title=_snapshot_text(snapshot, "intro_title", "WNBA Live Lens"),
        intro_body=_snapshot_text(snapshot, "intro_body", "WNBA live lens now serves the stored snapshot artifact directly."),
        aria_label=_snapshot_text(snapshot, "aria_label", "WNBA live lens board"),
        source_path=source_path,
        source_title=_snapshot_text(snapshot, "source_title", "WNBA live lens snapshot"),
        rank_cards=rank_cards,
        using_sample_data=bool(snapshot.get("using_sample_data", False)),
        header_stats=header_stats,
        module_links=[dict(link) for link in (_snapshot_list(snapshot, "module_links") or build_module_links(resolved_date, "Live Lens")) if isinstance(link, dict)],
        warning_panel=warning_panel,
        source_date_display=_snapshot_text(snapshot, "source_date_display", resolved_date),
        control_label=_snapshot_text(snapshot, "control_label", "Date"),
        control_type=_snapshot_text(snapshot, "control_type", "date"),
        control_name=_snapshot_text(snapshot, "control_name", "date"),
        control_value=_snapshot_text(snapshot, "control_value", resolved_date),
        submit_label=_snapshot_text(snapshot, "submit_label", "Load"),
        prev_href=_snapshot_text(snapshot, "prev_href", f"/wnba/live-lens?date={resolved_date}"),
        next_href=_snapshot_text(snapshot, "next_href", f"/wnba/live-lens?date={resolved_date}"),
        reset_href=_snapshot_text(snapshot, "reset_href", f"/wnba/live-lens?date={resolved_date}"),
        hidden_fields=[dict(field) for field in _snapshot_list(snapshot, "hidden_fields") if isinstance(field, dict)],
        empty_state=empty_state,
        extra_controls=[dict(control) for control in _snapshot_list(snapshot, "extra_controls") if isinstance(control, dict)],
        focus_panel=snapshot.get("focus_panel") if isinstance(snapshot.get("focus_panel"), dict) else None,
        summary_panel=snapshot.get("summary_panel") if isinstance(snapshot.get("summary_panel"), dict) else None,
        card_sections=[dict(section) for section in _snapshot_list(snapshot, "card_sections") if isinstance(section, dict)],
    )
    context["games"] = games
    context["requested_date"] = _snapshot_text(snapshot, "requested_date", selected_date)
    context["lookahead_applied"] = bool(snapshot.get("lookahead_applied", False))
    context["players_included"] = bool(snapshot.get("players_included", False))
    context["pregame_portfolio"] = deepcopy(snapshot.get("pregame_portfolio")) if isinstance(snapshot.get("pregame_portfolio"), dict) else {"enabled": False, "selected": 0, "candidates": 0}
    if snapshot.get("generated_at"):
        context["generated_at"] = _snapshot_text(snapshot, "generated_at", "")
        context["generatedAt"] = context["generated_at"]
    if snapshot.get("odds_refreshed_at"):
        context["odds_refreshed_at"] = _snapshot_text(snapshot, "odds_refreshed_at", "")
        context["oddsRefreshedAt"] = context["odds_refreshed_at"]
    if snapshot.get("live_lens_contract"):
        context["live_lens_contract"] = deepcopy(snapshot.get("live_lens_contract"))
    if snapshot.get("refresh_policy"):
        context["refresh_policy"] = deepcopy(snapshot.get("refresh_policy"))
    return context


def _empty_live_lens_context(selected_date: str) -> dict[str, Any]:
    return _snapshot_context(selected_date, None)


def _live_lens_card_limit(limit: int | None = None) -> int:
    try:
        value = int(limit if limit is not None else 50)
    except Exception:
        value = 50
    return max(0, min(50, value))


def _value_has_non_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_value_has_non_finite_number(item) for item in value.values())
    if isinstance(value, list):
        return any(_value_has_non_finite_number(item) for item in value)
    if isinstance(value, tuple):
        return any(_value_has_non_finite_number(item) for item in value)
    return False


def validate_live_lens_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if not str(snapshot.get("date") or "").strip():
        return False
    if not isinstance(snapshot.get("games"), list):
        return False
    cards = snapshot.get("cards")
    if not isinstance(cards, list):
        return False
    if _value_has_non_finite_number(snapshot):
        return False
    return True


def build_live_lens_snapshot(selected_date: str, *, limit: int = 50) -> dict[str, Any]:
    try:
        cards_context = build_cards_page_context(selected_date, allow_stored_date_fallback=False)
    except Exception:
        cards_context = {}
    resolved_date = str(cards_context.get("date") or selected_date).strip() or selected_date
    games = [dict(game) for game in (cards_context.get("games") if isinstance(cards_context.get("games"), list) else []) if isinstance(game, dict)]
    event_ids = [str(game.get("event_id") or "").strip() for game in games if str(game.get("event_id") or "").strip()]
    live_line_by_event_id: dict[str, float] = {}
    if event_ids:
        try:
            live_lines_payload = build_live_lines_payload(resolved_date, event_ids, allow_stored_date_fallback=False)
        except Exception:
            live_lines_payload = {}
        live_games = live_lines_payload.get("games") if isinstance(live_lines_payload, dict) and isinstance(live_lines_payload.get("games"), list) else []
        for live_game in live_games:
            if not isinstance(live_game, dict):
                continue
            event_id = str(live_game.get("event_id") or "").strip()
            line_value = _live_line_value(live_game)
            if event_id and line_value is not None:
                live_line_by_event_id[event_id] = line_value

    rank_cards = [
        _rank_card(game, resolved_date, live_line=live_line_by_event_id.get(str(game.get("event_id") or "").strip()))
        for game in games
        if isinstance(game, dict)
    ]
    rank_cards = rank_cards[: _live_lens_card_limit(limit)]
    prop_signal_count = sum(
        len(game.get("shared_prop_rows") or [])
        for game in games
        if isinstance(game, dict) and isinstance(game.get("shared_prop_rows"), list)
    )
    source_path = str(cards_context.get("source_path") or LIVE_LENS_SNAPSHOT_PATH).strip()
    warning_panel = {
        "eyebrow": "Artifact-backed lens",
        "title": "WNBA live lens now runs off the same cards and props snapshots as the board contract",
        "body": "This worker reads stored WNBA card artifacts, overlays live lines, and writes a snapshot for the request path to consume.",
        "list_items": [
            f"Games surfaced: {len(games)}",
            f"Prop signals surfaced: {prop_signal_count}",
        ],
    }
    empty_state = None
    if not rank_cards:
        warning_panel = {
            "eyebrow": "WNBA live lens",
            "title": "No stored WNBA live-lens rows were available for this date",
            "body": "The background worker only writes saved WNBA cards and props snapshot artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {resolved_date}"],
        }
        empty_state = {
            "eyebrow": "WNBA live lens",
            "title": "No stored WNBA live-lens snapshot was available for this date",
            "body": "The background worker only writes saved WNBA cards and props snapshot artifacts, and none were available for the requested date.",
            "list_items": [f"Requested date: {resolved_date}"],
        }

    context = build_rank_page_context(
        selected_date=resolved_date,
        route_path="/wnba/live-lens",
        intro_title="WNBA Live Lens",
        intro_body="WNBA live lens now serves a stored snapshot that is rebuilt in the background from local WNBA artifacts.",
        aria_label="WNBA live lens board",
        source_path=source_path,
        source_title="WNBA live lens snapshot",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(games))},
            {"label": "Cards", "value": str(len(rank_cards))},
            {"label": "Source", "value": Path(source_path).name if source_path else "Fallback"},
        ],
        module_links=build_module_links(resolved_date, "Live Lens"),
        warning_panel=warning_panel,
        empty_state=empty_state,
    )
    context["games"] = games
    context["cards"] = [dict(card) for card in rank_cards]
    context["requested_date"] = resolved_date
    context["lookahead_applied"] = bool(cards_context.get("lookahead_applied", False))
    context["players_included"] = False
    context["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    context["source_path"] = source_path
    context["source_title"] = str(context.get("source_title") or "WNBA live lens snapshot").strip() or "WNBA live lens snapshot"
    context["source_date_display"] = str(cards_context.get("source_date_display") or resolved_date).strip() or resolved_date
    context["generated_at"] = str(cards_context.get("generated_at") or cards_context.get("generatedAt") or "").strip() or None
    context["odds_refreshed_at"] = str(cards_context.get("odds_refreshed_at") or cards_context.get("oddsRefreshedAt") or "").strip() or None
    context["live_lens_contract"] = {
        "sport": "wnba",
        "module": "live_lens",
    }
    context = attach_live_lens_contract(context, sport="wnba", module="live_lens")
    context["api_payload"] = build_rank_api_payload(context)
    context["contract_ready_payload"] = dict(context["api_payload"])
    return context


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
            panel_items.append(_safe_text(item, "").strip())

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


def _rank_card(game: dict[str, Any], selected_date: str, *, live_line: float | None = None) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    away_score = _safe_number(away.get("score"))
    home_score = _safe_number(home.get("score"))
    if away_score is None:
        away_score = _safe_number(live_state.get("away_pts"))
    if home_score is None:
        home_score = _safe_number(live_state.get("home_pts"))
    current_total = (away_score + home_score) if away_score is not None and home_score is not None else None
    live_total = _safe_number(live_line)
    badge = _safe_text((((top_rows or [None])[0] or {}).get("value") if top_rows else None), "Watch")
    href = str(game.get("href") or f"/wnba/cards?date={selected_date}").strip()
    metrics = _metric_rows(game)
    if current_total is not None:
        metrics = [{"label": "Total pts", "value": str(int(round(current_total)))}] + metrics
    if live_total is not None:
        metrics = [{"label": "Live line", "value": f"{live_total:.1f}"}] + metrics
    summary = _safe_text(game.get("summary"), "WNBA live lens row.")
    if current_total is not None and live_total is not None:
        summary = f"Total pts {int(round(current_total))} vs Live line {live_total:.1f}. {summary}"
    elif current_total is not None:
        summary = f"Total pts {int(round(current_total))}. {summary}"
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _safe_text(game.get("status"), "Stored lens"),
        "badge": badge,
        "meta": _safe_text(game.get("detail"), selected_date),
        "metrics": metrics,
        "summary": summary,
        "list_items": _signal_items(game),
        "href": href,
        "href_label": _safe_text(game.get("href_label"), "Open WNBA game"),
    }


def build_live_lens_page_context(selected_date: str) -> dict[str, Any]:
    warn_if_compute_in_request_path("build_live_lens_page_context")
    snapshot = _load_live_lens_snapshot()
    context = _empty_live_lens_context(selected_date) if snapshot is None else _snapshot_context(selected_date, snapshot)
    return attach_live_lens_contract(context, sport="wnba", module="live_lens")


def build_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    context = build_live_lens_page_context(selected_date)
    payload = build_rank_api_payload(context)
    payload["ok"] = True
    payload["requested_date"] = context.get("requested_date") or selected_date
    payload["lookahead_applied"] = bool(context.get("lookahead_applied"))
    payload["players_included"] = bool(context.get("players_included", False))
    payload["pregame_portfolio"] = deepcopy(context.get("pregame_portfolio")) if isinstance(context.get("pregame_portfolio"), dict) else {"enabled": False, "selected": 0, "candidates": 0}
    payload["games"] = [dict(game) for game in (context.get("games") or []) if isinstance(game, dict)]
    return payload