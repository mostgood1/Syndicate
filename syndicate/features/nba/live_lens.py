from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any

from syndicate.features.nba.cards import build_cards_page_context as _compute_cards_page_context
from syndicate.features.nba.cards import build_live_lines_payload as _compute_live_lines_payload
from syndicate.features.nba.cards import build_live_pbp_stats_payload as _compute_live_pbp_stats_payload
from syndicate.features.nba.cards import build_live_player_lens_payload as _compute_live_player_lens_payload
from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file


build_cards_page_context = _compute_cards_page_context


def live_lens_snapshot_path() -> Path:
    return data_root() / "live" / "nba_live_lens.json"


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


def _snapshot_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _snapshot_text(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = str(payload.get(key) or "").strip()
    return value or fallback


def _load_live_lens_snapshot() -> dict[str, Any] | None:
    payload = read_json_file(live_lens_snapshot_path())
    return payload if isinstance(payload, dict) else None


def _live_line_map(selected_date: str, games: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    event_ids = [
        str(game.get("event_id") or "").strip()
        for game in games
        if isinstance(game, dict) and str(game.get("event_id") or "").strip()
    ]
    if not event_ids:
        return {}
    payload = build_live_lines_payload(selected_date, event_ids, ttl=20, include_period_totals=True, allow_stored_date_fallback=True)
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


def _route_shell_updates(selected_date: str, *, season: int | None = None, profile: str | None = None, embed_mode: str | None = None) -> dict[str, Any]:
    resolved_season = int(season) if season is not None else parse_iso_date(selected_date).year
    normalized_profile = str(profile or "").strip().lower() or None
    normalized_embed_mode = str(embed_mode or "").strip().lower() or ""
    route_path = f"/nba/season/{resolved_season}/live-lens" if season is not None else "/nba/live-lens"
    query_suffix = f"&profile={normalized_profile}" if normalized_profile else ""
    updates: dict[str, Any] = {
        "route_path": route_path,
        "cards_base_path": route_path,
        "cards_api_base_path": "/nba/api",
        "cards_payload_path": f"/nba/api/season/{resolved_season}/live-lens" if season is not None else "/nba/api/live-lens",
        "cards_query_suffix": query_suffix,
        "season_betting_profile": normalized_profile or "retuned",
        "cards_live_audit_href": f"{route_path}?date={selected_date}&profile=retuned" if season is not None else f"/nba/live-lens?date={selected_date}",
        "cards_live_audit_label": "Live Lens",
        "query_hidden_fields": ([{"name": "profile", "value": normalized_profile}] if normalized_profile else []),
        "embed_mode": normalized_embed_mode,
        "page_title": "NBA Live Lens",
        "page_heading": "NBA Live Lens",
    }
    return updates


def _apply_route_shell_context(context: dict[str, Any], selected_date: str, *, season: int | None = None, profile: str | None = None, embed_mode: str | None = None) -> dict[str, Any]:
    updated = dict(context)
    updated.update(_route_shell_updates(selected_date, season=season, profile=profile, embed_mode=embed_mode))
    return updated


def _empty_live_lens_context(selected_date: str, *, season: int | None = None, profile: str | None = None, embed_mode: str | None = None) -> dict[str, Any]:
    resolved_season = int(season) if season is not None else parse_iso_date(selected_date).year
    route_path = f"/nba/season/{resolved_season}/live-lens" if season is not None else "/nba/live-lens"
    requested_date = selected_date
    context = build_rank_page_context(
        selected_date=selected_date,
        route_path=route_path,
        intro_title="NBA Live Lens",
        intro_body="NBA live lens serves the stored snapshot artifact directly.",
        aria_label="NBA live lens board",
        source_path=str(live_lens_snapshot_path()),
        source_title="NBA live lens snapshot",
        rank_cards=[],
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": "0"},
            {"label": "Top plays", "value": "0"},
            {"label": "Prop signals", "value": "0"},
            {"label": "Source", "value": live_lens_snapshot_path().name},
        ],
        module_links=build_module_links(selected_date, "Live Lens"),
        warning_panel={
            "eyebrow": "NBA live lens",
            "title": "No stored NBA live-lens rows were available for this date",
            "body": "The live-lens board only reads the published NBA live-lens snapshot artifact, and none was available for the requested date.",
            "list_items": [f"Requested date: {requested_date}"],
        },
        empty_state={
            "eyebrow": "NBA live lens",
            "title": "No stored NBA live-lens rows were available for this date",
            "body": "The live-lens board only reads the published NBA live-lens snapshot artifact, and none was available for the requested date.",
            "list_items": [f"Requested date: {requested_date}"],
        },
    )
    context["games"] = []
    context["requested_date"] = requested_date
    context["lookahead_applied"] = False
    context["players_included"] = False
    context["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    return attach_live_lens_contract(_apply_route_shell_context(context, selected_date, season=season, profile=profile, embed_mode=embed_mode), sport="nba", module="live_lens")


def _compute_live_lens_page_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    requested_date = str(cards_context.get("requested_date") or selected_date).strip() or selected_date
    resolved_date = str(cards_context.get("date") or selected_date).strip() or selected_date
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
            "body": "The live-lens board only reads the published NBA live-lens snapshot artifact, and none was available for the requested date.",
            "list_items": [f"Requested date: {requested_date}"],
        }

    route_path = f"/nba/season/{int(season)}/live-lens" if season is not None else "/nba/live-lens"
    hidden_fields: list[dict[str, str]] | None = None
    prev_href = None
    next_href = None
    if season is not None:
        normalized_profile = str(profile or "").strip().lower() or None
        query_suffix = f"&profile={normalized_profile}" if normalized_profile else ""
        hidden_fields = [{"name": "profile", "value": normalized_profile}] if normalized_profile else None
        prev_href = f"{route_path}?date={cards_context.get('prev_date') or requested_date}{query_suffix}"
        next_href = f"{route_path}?date={cards_context.get('next_date') or requested_date}{query_suffix}"

    context = build_rank_page_context(
        selected_date=resolved_date,
        route_path=route_path,
        intro_title="NBA Live Lens",
        intro_body="NBA live lens now serves the stored snapshot artifact directly.",
        aria_label="NBA live lens board",
        source_path=str(cards_context.get("source_path") or live_lens_snapshot_path()),
        source_title="NBA live lens snapshot" if rank_cards else "NBA live lens unavailable",
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
            "body": "The live-lens board only reads the published NBA live-lens snapshot artifact, and none was available for the requested date.",
            "list_items": [f"Requested date: {requested_date}"],
        } if not rank_cards else None,
    )
    context["games"] = [dict(game) for game in games if isinstance(game, dict)]
    context["requested_date"] = requested_date
    context["lookahead_applied"] = bool(cards_context.get("lookahead_applied"))
    context["players_included"] = False
    context["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    return attach_live_lens_contract(_apply_route_shell_context(context, selected_date, season=season, profile=profile), sport="nba", module="live_lens")


def _empty_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    context = _empty_live_lens_context(selected_date)
    payload = build_rank_api_payload(context)
    payload["ok"] = True
    payload["requested_date"] = selected_date
    payload["lookahead_applied"] = False
    payload["players_included"] = False
    payload["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    payload["games"] = []
    return payload


def _compute_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    cards_context = _compute_cards_page_context(selected_date)
    payload = build_rank_api_payload(_compute_live_lens_page_context(selected_date))
    payload["requested_date"] = cards_context.get("requested_date")
    payload["lookahead_applied"] = bool(cards_context.get("lookahead_applied"))
    payload["players_included"] = False
    payload["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    payload["games"] = [dict(game) for game in (cards_context.get("games") or []) if isinstance(game, dict)]
    return payload


def _coerce_snapshot_payload(payload: dict[str, Any] | None, *, key: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    section = payload.get(key)
    return dict(section) if isinstance(section, dict) else None


def _filter_games_payload(payload: dict[str, Any] | None, event_ids: list[str], *, default_factory) -> dict[str, Any]:
    requested_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not isinstance(payload, dict):
        return default_factory(requested_ids)
    games = payload.get("games") if isinstance(payload.get("games"), list) else []
    if requested_ids:
        filtered_games = [dict(game) for game in games if isinstance(game, dict) and str(game.get("event_id") or "").strip() in requested_ids]
        if filtered_games:
            result = dict(payload)
            result["games"] = filtered_games
            return result
        return default_factory(requested_ids)
    result = dict(payload)
    result["games"] = [dict(game) for game in games if isinstance(game, dict)]
    return result


def _empty_live_player_lens_payload(selected_date: str, event_ids: list[str], ttl: int = 20) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    if not normalized_event_ids:
        normalized_event_ids = []
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date or None,
        "requested_date": selected_date,
        "lookahead_applied": False,
        "games": [{"event_id": event_id, "players": []} for event_id in normalized_event_ids],
        "generated_at": None,
    }


def _empty_live_lines_payload(selected_date: str, event_ids: list[str], ttl: int = 20, *, include_period_totals: bool = False) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date,
        "requested_date": selected_date,
        "lookahead_applied": False,
        "include_period_totals": bool(include_period_totals),
        "games": [{"event_id": event_id, "found": False} for event_id in normalized_event_ids],
        "generated_at": None,
    }


def _empty_live_pbp_stats_payload(selected_date: str, event_ids: list[str], ttl: int = 20) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date or None,
        "requested_date": selected_date,
        "lookahead_applied": False,
        "games": [
            {
                "event_id": event_id,
                "game_id": None,
                "home": None,
                "away": None,
                "pbp_attempts": {"home": {}, "away": {}, "unknown": {}, "total": {}},
                "pbp_attempts_periods": {},
                "pbp_possessions": {"home": {}, "away": {}, "unknown": {}, "total": {}},
                "pbp_possessions_periods": {},
                "pbp_quarters": {"q_totals": {"q1": None, "q2": None, "q3": None, "q4": None}, "current": {"period": None, "q_total": None}},
                "pbp_recent": {"window_sec": 180, "points_total": None, "attempts": None, "possessions": None, "current_scoring_run": {"team": None, "points": None}, "seconds_since_score": None},
            }
            for event_id in normalized_event_ids
        ],
        "generated_at": None,
    }


def validate_live_lens_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    rank_cards = snapshot.get("rank_cards")
    if rank_cards is None:
        page_context = snapshot.get("page_context") if isinstance(snapshot.get("page_context"), dict) else {}
        rank_cards = page_context.get("rank_cards") if isinstance(page_context.get("rank_cards"), list) else []
    if not isinstance(rank_cards, list):
        return False

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

    return not _value_has_non_finite_number(snapshot)


def build_live_lens_snapshot(selected_date: str, *, limit: int = 50) -> dict[str, Any]:
    try:
        cards_context = _compute_cards_page_context(selected_date, allow_stored_date_fallback=False)
    except Exception:
        cards_context = {}
    resolved_date = str(cards_context.get("date") or selected_date).strip() or selected_date
    games = [dict(game) for game in (cards_context.get("games") if isinstance(cards_context.get("games"), list) else []) if isinstance(game, dict)]
    event_ids = [str(game.get("event_id") or "").strip() for game in games if str(game.get("event_id") or "").strip()]
    page_context = _compute_live_lens_page_context(selected_date)
    api_payload = _compute_live_lens_api_payload(selected_date)
    live_player_lens_payload = _compute_live_player_lens_payload(resolved_date, event_ids, ttl=20, allow_stored_date_fallback=True)
    live_lines_payload = _compute_live_lines_payload(resolved_date, event_ids, ttl=20, include_period_totals=True, allow_stored_date_fallback=True)
    live_pbp_stats_payload = _compute_live_pbp_stats_payload(resolved_date, event_ids, ttl=20, allow_stored_date_fallback=True)
    snapshot = {
        "ok": True,
        "date": resolved_date,
        "requested_date": selected_date,
        "generated_at": api_payload.get("generated_at") if isinstance(api_payload, dict) else None,
        "source_path": str(page_context.get("source_path") or live_lens_snapshot_path()),
        "page_context": dict(page_context),
        "api_payload": dict(api_payload),
        "live_player_lens_payload": dict(live_player_lens_payload) if isinstance(live_player_lens_payload, dict) else _empty_live_player_lens_payload(resolved_date, event_ids),
        "live_lines_payload": dict(live_lines_payload) if isinstance(live_lines_payload, dict) else _empty_live_lines_payload(resolved_date, event_ids, include_period_totals=True),
        "live_pbp_stats_payload": dict(live_pbp_stats_payload) if isinstance(live_pbp_stats_payload, dict) else _empty_live_pbp_stats_payload(resolved_date, event_ids),
        "games": games[:limit],
        "rank_cards": [dict(card) for card in (page_context.get("rank_cards") if isinstance(page_context.get("rank_cards"), list) else []) if isinstance(card, dict)][:limit],
    }
    return snapshot


def _snapshot_route_context(selected_date: str, *, season: int | None = None, profile: str | None = None, embed_mode: str | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        base_context = snapshot.get("page_context") if isinstance(snapshot.get("page_context"), dict) else snapshot
        if isinstance(base_context, dict):
            context = dict(base_context)
        else:
            context = _empty_live_lens_context(selected_date, season=season, profile=profile, embed_mode=embed_mode)
    else:
        context = _empty_live_lens_context(selected_date, season=season, profile=profile, embed_mode=embed_mode)
    context = _apply_route_shell_context(context, selected_date, season=season, profile=profile, embed_mode=embed_mode)
    context["asset_version"] = context.get("asset_version") or "1"
    return context


def read_latest_live_lens_snapshot() -> dict[str, Any] | None:
    snapshot = _load_live_lens_snapshot()
    return dict(snapshot) if isinstance(snapshot, dict) else None


def _safe_empty_live_lens_response(selected_date: str) -> dict[str, Any]:
    return {
        "games": [],
        "cards": [],
        "date": selected_date,
        "status": "empty",
    }


def read_latest_live_lens_page_context(selected_date: str, *, season: int | None = None, profile: str | None = None, embed_mode: str | None = None) -> dict[str, Any]:
    try:
        snapshot = read_latest_live_lens_snapshot()
        if not isinstance(snapshot, dict):
            return _empty_live_lens_context(selected_date, season=season, profile=profile, embed_mode=embed_mode)
        return _snapshot_route_context(selected_date, season=season, profile=profile, embed_mode=embed_mode, snapshot=snapshot)
    except Exception as error:
        print("WNBA SNAPSHOT ERROR:", error)
        return _empty_live_lens_context(selected_date, season=season, profile=profile, embed_mode=embed_mode)


def read_latest_live_lens_api_payload(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, Any]:
    try:
        snapshot = read_latest_live_lens_snapshot()
        if not isinstance(snapshot, dict):
            return build_rank_api_payload(_empty_live_lens_context(selected_date, season=season, profile=profile))
        api_payload = _coerce_snapshot_payload(snapshot, key="api_payload")
        if api_payload is None:
            return build_rank_api_payload(_empty_live_lens_context(selected_date, season=season, profile=profile))
        payload = dict(api_payload)
        payload.setdefault("ok", True)
        payload.setdefault("requested_date", selected_date)
        payload.setdefault("lookahead_applied", False)
        payload.setdefault("players_included", False)
        payload.setdefault("pregame_portfolio", {"enabled": False, "selected": 0, "candidates": 0})
        payload.setdefault("games", [])
        return payload
    except Exception as error:
        print("WNBA SNAPSHOT ERROR:", error)
        return build_rank_api_payload(_empty_live_lens_context(selected_date, season=season, profile=profile))


def read_latest_live_player_lens_payload(selected_date: str, event_ids: list[str], ttl: int = 20, *, allow_stored_date_fallback: bool = True) -> dict[str, Any]:
    _ = allow_stored_date_fallback
    snapshot = read_latest_live_lens_snapshot()
    payload = _coerce_snapshot_payload(snapshot, key="live_player_lens_payload") if snapshot is not None else None
    if payload is None:
        return _empty_live_player_lens_payload(selected_date, event_ids, ttl=ttl)
    return _filter_games_payload(payload, event_ids, default_factory=lambda requested_ids: _empty_live_player_lens_payload(selected_date, requested_ids, ttl=ttl))


def read_latest_live_lines_payload(selected_date: str, event_ids: list[str], ttl: int = 20, include_period_totals: bool = False, *, allow_stored_date_fallback: bool = True) -> dict[str, Any]:
    _ = allow_stored_date_fallback
    snapshot = read_latest_live_lens_snapshot()
    payload = _coerce_snapshot_payload(snapshot, key="live_lines_payload") if snapshot is not None else None
    if payload is None:
        return _empty_live_lines_payload(selected_date, event_ids, ttl=ttl, include_period_totals=include_period_totals)
    filtered = _filter_games_payload(payload, event_ids, default_factory=lambda requested_ids: _empty_live_lines_payload(selected_date, requested_ids, ttl=ttl, include_period_totals=include_period_totals))
    if not include_period_totals and isinstance(filtered, dict):
        for game in filtered.get("games") if isinstance(filtered.get("games"), list) else []:
            if isinstance(game, dict):
                lines = game.get("lines") if isinstance(game.get("lines"), dict) else None
                if isinstance(lines, dict):
                    lines = dict(lines)
                    lines.pop("period_totals", None)
                    lines.pop("period_spreads", None)
                    game["lines"] = lines
    return filtered


def read_latest_live_pbp_stats_payload(selected_date: str, event_ids: list[str], ttl: int = 20, *, allow_stored_date_fallback: bool = True) -> dict[str, Any]:
    _ = allow_stored_date_fallback
    snapshot = read_latest_live_lens_snapshot()
    payload = _coerce_snapshot_payload(snapshot, key="live_pbp_stats_payload") if snapshot is not None else None
    if payload is None:
        return _empty_live_pbp_stats_payload(selected_date, event_ids, ttl=ttl)
    return _filter_games_payload(payload, event_ids, default_factory=lambda requested_ids: _empty_live_pbp_stats_payload(selected_date, requested_ids, ttl=ttl))


def build_live_lens_page_context(selected_date: str, *, season: int | None = None, profile: str | None = None) -> dict[str, Any]:
    return _compute_live_lens_page_context(selected_date, season=season, profile=profile)


def build_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    return _compute_live_lens_api_payload(selected_date)


def build_live_player_lens_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    _ = allow_stored_date_fallback
    snapshot = _load_live_lens_snapshot()
    payload = _coerce_snapshot_payload(snapshot, key="live_player_lens_payload") if snapshot is not None else None
    if payload is None:
        return _empty_live_player_lens_payload(selected_date, event_ids, ttl=ttl)
    return _filter_games_payload(payload, event_ids, default_factory=lambda requested_ids: _empty_live_player_lens_payload(selected_date, requested_ids, ttl=ttl))


def build_live_lines_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    include_period_totals: bool = False,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    _ = allow_stored_date_fallback
    snapshot = _load_live_lens_snapshot()
    payload = _coerce_snapshot_payload(snapshot, key="live_lines_payload") if snapshot is not None else None
    if payload is None:
        return _empty_live_lines_payload(selected_date, event_ids, ttl=ttl, include_period_totals=include_period_totals)
    filtered = _filter_games_payload(payload, event_ids, default_factory=lambda requested_ids: _empty_live_lines_payload(selected_date, requested_ids, ttl=ttl, include_period_totals=include_period_totals))
    if not include_period_totals and isinstance(filtered, dict):
        for game in filtered.get("games") if isinstance(filtered.get("games"), list) else []:
            if isinstance(game, dict):
                lines = game.get("lines") if isinstance(game.get("lines"), dict) else None
                if isinstance(lines, dict):
                    lines = dict(lines)
                    lines.pop("period_totals", None)
                    lines.pop("period_spreads", None)
                    game["lines"] = lines
    return filtered


def build_live_pbp_stats_payload(
    selected_date: str,
    event_ids: list[str],
    ttl: int = 20,
    *,
    allow_stored_date_fallback: bool = True,
) -> dict[str, Any]:
    _ = allow_stored_date_fallback
    snapshot = _load_live_lens_snapshot()
    payload = _coerce_snapshot_payload(snapshot, key="live_pbp_stats_payload") if snapshot is not None else None
    if payload is None:
        return _empty_live_pbp_stats_payload(selected_date, event_ids, ttl=ttl)
    return _filter_games_payload(payload, event_ids, default_factory=lambda requested_ids: _empty_live_pbp_stats_payload(selected_date, requested_ids, ttl=ttl))


def build_live_lens_api_payload(selected_date: str) -> dict[str, Any]:
    cards_context = build_cards_page_context(selected_date)
    payload = build_rank_api_payload(build_live_lens_page_context(selected_date))
    payload["requested_date"] = cards_context.get("requested_date")
    payload["lookahead_applied"] = bool(cards_context.get("lookahead_applied"))
    payload["players_included"] = False
    payload["pregame_portfolio"] = {"enabled": False, "selected": 0, "candidates": 0}
    payload["games"] = [dict(game) for game in (cards_context.get("games") or []) if isinstance(game, dict)]
    return payload