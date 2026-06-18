from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
import re
from typing import Any

from syndicate.features.shared.rank_board import build_rank_page_context


CardBuilder = Callable[[dict[str, Any], int], list[dict[str, Any]]]
SummaryLoader = Callable[[str], dict[str, Any] | None]
ModuleLinksBuilder = Callable[[str, str], list[dict[str, Any]]]


_DATE_PATTERN = re.compile(r"(\d{4}[-_]\d{2}[-_]\d{2})")


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value).strip().replace("_", "-"))
    except Exception:
        return None


def _resolve_top_props_source_path(*, source_path: str, selected_date: str, available_dates: list[str] | None) -> Path:
    candidate_path = Path(source_path)
    if not available_dates:
        return candidate_path

    dates = sorted({str(value).strip() for value in available_dates if str(value).strip()})
    if not dates:
        return candidate_path

    requested_date = str(selected_date or "").strip()
    if not requested_date:
        return candidate_path

    match = _DATE_PATTERN.search(candidate_path.name)
    if not match:
        return candidate_path

    parsed_requested = _parse_iso_date(requested_date)
    if parsed_requested is None:
        return candidate_path

    parsed_dates = [(parsed_date, value) for value in dates if (parsed_date := _parse_iso_date(value)) is not None]
    if not parsed_dates:
        return candidate_path
    parsed_dates.sort(key=lambda item: item[0])

    earliest_date = parsed_dates[0][0]
    latest_date = parsed_dates[-1][0]
    if parsed_requested < earliest_date:
        return candidate_path

    resolved_date = parsed_dates[-1][1] if parsed_requested >= latest_date else None
    if resolved_date is None:
        prior_dates = [value for parsed_value, value in parsed_dates if parsed_value <= parsed_requested]
        if prior_dates:
            resolved_date = prior_dates[-1]

    if resolved_date is None:
        return candidate_path

    token = candidate_path.name[match.start():match.end()]
    replacement_date = resolved_date.replace("-", "_") if "_" in token and "-" not in token else resolved_date
    resolved_path = candidate_path.with_name(f"{candidate_path.name[:match.start()]}{replacement_date}{candidate_path.name[match.end():]}")
    return resolved_path


def build_top_props_page_context(
    *,
    selected_date: str,
    route_path: str,
    intro_title: str,
    intro_body: str,
    aria_label: str,
    source_path: str,
    source_title: str,
    active_label: str,
    load_summary: SummaryLoader,
    build_cards: CardBuilder,
    build_module_links: ModuleLinksBuilder,
    available_dates: list[str] | None = None,
    warning_panel: dict[str, Any] | None = None,
    extra_controls: list[dict[str, Any]] | None = None,
    empty_state: dict[str, Any] | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    resolved_source_path = _resolve_top_props_source_path(
        source_path=source_path,
        selected_date=selected_date,
        available_dates=available_dates,
    )
    summary = load_summary(str(resolved_source_path)) or {}
    cards = build_cards(summary, limit)

    rows = summary.get("data") if isinstance(summary.get("data"), list) else []
    high_tier_count = sum(
        1
        for row in rows
        if isinstance(row, dict) and str(row.get("tier") or "").strip().lower() == "high"
    )

    context = build_rank_page_context(
        selected_date=selected_date,
        route_path=route_path,
        intro_title=intro_title,
        intro_body=intro_body,
        aria_label=aria_label,
        source_path=str(resolved_source_path),
        source_title=source_title,
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Cards", "value": str(len(cards))},
            {"label": "High tier", "value": str(high_tier_count)},
        ],
        module_links=build_module_links(selected_date, active_label),
        warning_panel=warning_panel,
        extra_controls=extra_controls,
        empty_state=empty_state if not cards else None,
    )
    if available_dates is not None:
        context["available_dates"] = list(available_dates)
    return context
