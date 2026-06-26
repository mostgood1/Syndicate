from __future__ import annotations

from datetime import datetime
from datetime import date
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE
from syndicate.features.shared.timezone import central_today


def _parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return central_today()


def _centralize_iso_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=CENTRAL_TIMEZONE)
        return stamp.astimezone(CENTRAL_TIMEZONE).isoformat(timespec="seconds")
    except Exception:
        return text


def build_rank_page_context(
    *,
    selected_date: str,
    route_path: str,
    intro_title: str,
    intro_body: str,
    aria_label: str,
    source_path: str | Path,
    source_title: str,
    rank_cards: list[dict[str, Any]],
    using_sample_data: bool,
    header_stats: list[dict[str, str]],
    module_links: list[dict[str, Any]],
    warning_panel: dict[str, Any] | None = None,
    source_date_display: str | None = None,
    control_label: str = "Date",
    control_type: str = "date",
    control_name: str = "date",
    control_value: str | None = None,
    submit_label: str = "Load",
    prev_href: str | None = None,
    next_href: str | None = None,
    reset_href: str | None = None,
    hidden_fields: list[dict[str, str]] | None = None,
    empty_state: dict[str, Any] | None = None,
    extra_controls: list[dict[str, Any]] | None = None,
    focus_panel: dict[str, Any] | None = None,
    summary_panel: dict[str, Any] | None = None,
    card_sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed_date = _parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    resolved_prev_href = prev_href or f"{route_path}?date={prev_date}"
    resolved_next_href = next_href or f"{route_path}?date={next_date}"
    return {
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "rank_cards": rank_cards,
        "using_sample_data": using_sample_data,
        "source_path": str(source_path),
        "source_date_display": source_date_display or selected_date,
        "source_title": source_title,
        "header_stats": header_stats,
        "route_path": route_path,
        "intro_title": intro_title,
        "intro_body": intro_body,
        "aria_label": aria_label,
        "module_links": module_links,
        "warning_panel": warning_panel,
        "control_label": control_label,
        "control_type": control_type,
        "control_name": control_name,
        "control_value": control_value or selected_date,
        "submit_label": submit_label,
        "prev_href": resolved_prev_href,
        "next_href": resolved_next_href,
        "reset_href": reset_href,
        "hidden_fields": list(hidden_fields or []),
        "empty_state": empty_state,
        "extra_controls": list(extra_controls or []),
        "focus_panel": focus_panel,
        "summary_panel": summary_panel,
        "card_sections": list(card_sections or []),
    }


def build_rank_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "date": context["date"],
        "rank_cards": context.get("rank_cards", []),
        "using_sample_data": context.get("using_sample_data", False),
        "source_path": context.get("source_path"),
    }
    if "generatedAt" in context:
        payload["generatedAt"] = _centralize_iso_timestamp(context.get("generatedAt"))
    if "generated_at" in context:
        payload["generated_at"] = _centralize_iso_timestamp(context.get("generated_at"))
    if "oddsRefreshedAt" in context:
        payload["oddsRefreshedAt"] = _centralize_iso_timestamp(context.get("oddsRefreshedAt"))
    if "odds_refreshed_at" in context:
        payload["odds_refreshed_at"] = _centralize_iso_timestamp(context.get("odds_refreshed_at"))
    payload.setdefault("route_path", context.get("route_path"))
    payload.setdefault("control_label", context.get("control_label") or "Date")
    payload.setdefault("control_type", context.get("control_type") or "date")
    payload.setdefault("control_name", context.get("control_name") or "date")
    payload.setdefault("control_value", context.get("control_value") or context.get("date"))
    optional_keys = (
        "source_title",
        "source_date_display",
        "generatedAt",
        "generated_at",
        "oddsRefreshedAt",
        "odds_refreshed_at",
        "live_lens_contract",
        "refresh_policy",
        "header_stats",
        "route_path",
        "module_links",
        "warning_panel",
        "available_dates",
        "control_label",
        "control_type",
        "control_name",
        "control_value",
        "submit_label",
        "prev_href",
        "next_href",
        "reset_href",
        "hidden_fields",
        "empty_state",
        "extra_controls",
        "focus_panel",
        "summary_panel",
        "card_sections",
    )
    for key in optional_keys:
        if key in context:
            payload[key] = context.get(key)
    if "odds_refreshed_at" not in payload:
        fallback_ts = _centralize_iso_timestamp(payload.get("oddsRefreshedAt") or payload.get("generatedAt") or payload.get("generated_at"))
        if fallback_ts:
            payload["odds_refreshed_at"] = fallback_ts
    if "oddsRefreshedAt" not in payload:
        camel_ts = _centralize_iso_timestamp(payload.get("odds_refreshed_at") or payload.get("generatedAt") or payload.get("generated_at"))
        if camel_ts:
            payload["oddsRefreshedAt"] = camel_ts
    return payload
