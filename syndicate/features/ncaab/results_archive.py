from __future__ import annotations

from typing import Any

from syndicate.features.ncaab.sources import build_module_links
from syndicate.features.ncaab.sources import mirrored_results_by_date_payload
from syndicate.features.ncaab.sources import mirrored_results_dates
from syndicate.features.ncaab.sources import season_for_date
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.date_archive import build_discrete_date_archive_api_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_page_context
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates


# Preserve the historical module-level names that the regression suite patches.
results_dates = mirrored_results_dates
results_by_date_payload = mirrored_results_by_date_payload


def _fmt_pct(value: Any) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "-"
        return f"{float(value):.1f}%"
    except Exception:
        return "-"


def _archive_card(date_str: str, payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    season = season_for_date(date_str)
    return {
        "title": date_str,
        "eyebrow": f"Season {season} results",
        "badge": f"{len(rows)} games",
        "meta": f"ATS {summary.get('ats_correct', 0)}/{summary.get('ats_total', 0)} | Totals {summary.get('totals_correct', 0)}/{summary.get('totals_total', 0)}",
        "metrics": [
            {"label": "Games", "value": str(len(rows))},
            {"label": "ATS acc", "value": _fmt_pct(summary.get("ats_accuracy"))},
            {"label": "Totals acc", "value": _fmt_pct(summary.get("totals_accuracy"))},
            {"label": "Season", "value": str(season)},
        ],
        "summary": "This archive date is sourced directly from the settled NCAAB daily results payload and links back into the season-review board for matchup-level historical detail.",
        "list_items": [
            f"ATS correct: {summary.get('ats_correct', 0)} of {summary.get('ats_total', 0)}",
            f"Totals correct: {summary.get('totals_correct', 0)} of {summary.get('totals_total', 0)}",
            f"Results date: {date_str}",
        ],
        "href": f"/ncaab/season/{season}?date={date_str}",
        "href_label": "Open season review",
    }


def build_results_archive_page_context(selected_date: str) -> dict[str, Any]:
    dates = results_dates()
    fallback = dates[-1] if dates else selected_date
    resolved_date = resolve_selected_value(selected_date or fallback, dates, fallback)
    selected_payload = results_by_date_payload(resolved_date) or {}
    window_dates = windowed_discrete_dates(dates, resolved_date)
    cards = []
    for date_str in window_dates:
        payload = results_by_date_payload(date_str) or {}
        cards.append(_archive_card(date_str, payload))
    cards = selected_first_rank_cards(cards, resolved_date)

    selected_rows = selected_payload.get("rows") if isinstance(selected_payload.get("rows"), list) else []
    selected_summary = selected_payload.get("summary") if isinstance(selected_payload.get("summary"), dict) else {}
    using_sample_data = False

    context = build_discrete_date_archive_page_context(
        selected_date=resolved_date,
        dates=dates,
        route_path="/ncaab/archive",
        intro_title="NCAAB Daily Archive",
        intro_body="This archive board lists real settled NCAAB dates and turns each one into a drill-in entry point for the existing season-review surface.",
        aria_label="NCAAB daily archive",
        source_path=f"Syndicate data/ncaab_source/api/results_dates.json | data/ncaab_source/api/results_by_date/results_{resolved_date}.json",
        source_title="NCAAB mirrored daily archive" if cards else "NCAAB archive unavailable",
        rank_cards=cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Archive dates", "value": str(len(dates))},
            {"label": "Selected games", "value": str(len(selected_rows))},
            {"label": "ATS acc", "value": _fmt_pct(selected_summary.get("ats_accuracy"))},
            {"label": "Totals acc", "value": _fmt_pct(selected_summary.get("totals_accuracy"))},
        ],
        module_links=build_module_links(resolved_date, "Daily archive"),
        warning_panel={
            "eyebrow": "Archive lane",
            "title": "Daily archive dates drill back into season review",
            "body": "Use this archive when you want date-level settled performance first, then jump into season review for matchup-level cards and merged recommendation context.",
            "list_items": [
                "Each card summarizes one settled date from the source results payload.",
                "Archive cards link into the existing season-review page for deeper game detail.",
            ],
        },
        source_date_display=resolved_date,
    )
    if not cards:
        context["empty_state"] = {
            "eyebrow": "NCAAB daily archive",
            "title": "No settled NCAAB results dates were available",
            "body": "The daily archive only renders mirrored settled NCAAB dates, and none were available for the selected window.",
            "list_items": ["Refresh the NCAAB source mirror to populate this archive lane."],
        }
    return context


def build_results_archive_api_payload(selected_date: str) -> dict[str, Any]:
    context = build_results_archive_page_context(selected_date)
    return build_discrete_date_archive_api_payload(context)