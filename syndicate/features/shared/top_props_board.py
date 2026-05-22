from __future__ import annotations

from collections.abc import Callable
from typing import Any

from syndicate.features.shared.rank_board import build_rank_page_context


CardBuilder = Callable[[dict[str, Any], int], list[dict[str, Any]]]
SummaryLoader = Callable[[str], dict[str, Any] | None]
ModuleLinksBuilder = Callable[[str, str], list[dict[str, Any]]]


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
    summary = load_summary(source_path) or {}
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
        source_path=source_path,
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
