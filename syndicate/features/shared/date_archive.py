from __future__ import annotations

from typing import Any

from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


def windowed_discrete_dates(dates: list[str], selected_date: str, limit: int = 12) -> list[str]:
    if not dates:
        return []
    try:
        index = dates.index(selected_date)
    except ValueError:
        index = len(dates) - 1
    start = max(0, index - (limit // 2))
    end = min(len(dates), start + limit)
    start = max(0, end - limit)
    return list(reversed(dates[start:end]))


def selected_first_rank_cards(rank_cards: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    return sorted(
        rank_cards,
        key=lambda card: (0 if str(card.get("title") or "") == selected_date else 1, str(card.get("title") or "")),
        reverse=False,
    )


def build_discrete_date_archive_page_context(
    *,
    selected_date: str,
    dates: list[str],
    route_path: str,
    intro_title: str,
    intro_body: str,
    aria_label: str,
    source_path: str,
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
) -> dict[str, Any]:
    prev_date, next_date = neighboring_values(dates, selected_date, fallback=selected_date)
    return build_rank_page_context(
        selected_date=selected_date,
        route_path=route_path,
        intro_title=intro_title,
        intro_body=intro_body,
        aria_label=aria_label,
        source_path=source_path,
        source_title=source_title,
        rank_cards=rank_cards,
        using_sample_data=using_sample_data,
        header_stats=header_stats,
        module_links=module_links,
        warning_panel=warning_panel,
        source_date_display=source_date_display,
        control_label=control_label,
        control_type=control_type,
        control_name=control_name,
        prev_href=f"{route_path}?date={prev_date}",
        next_href=f"{route_path}?date={next_date}",
    )


def build_discrete_date_archive_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    return build_rank_api_payload(context)