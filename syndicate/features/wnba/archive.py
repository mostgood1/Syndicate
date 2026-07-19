from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from syndicate.features.shared.date_archive import build_discrete_date_archive_api_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_page_context
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.wnba.sources import available_dates
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import default_date
from syndicate.features.wnba.sources import load_json
from syndicate.features.wnba.sources import processed_path_or_default


def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except Exception:
        return 0


def _summary_counts(path: Path) -> tuple[int, int]:
    payload = load_json(path) or {}
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    games = int(counts.get("games") or 0)
    picks = int(counts.get("picks") or 0)
    return games, picks


def _archive_card(date_str: str) -> dict[str, Any]:
    cards_path = processed_path_or_default(f"game_cards_{date_str}.csv")
    picks_path = processed_path_or_default(f"recommendations_slate_{date_str}.json")
    sim_path = processed_path_or_default(f"cards_sim_detail_{date_str}.json")
    props_path = processed_path_or_default(f"cards_props_snapshot_{date_str}.json")
    card_rows = _csv_row_count(cards_path)
    games_count, picks_count = _summary_counts(picks_path)
    sim_ready = sim_path.exists()
    props_ready = props_path.exists()

    return {
        "title": date_str,
        "eyebrow": "WNBA stored slate",
        "badge": f"{card_rows or games_count} games",
        "meta": f"Picks {picks_count} | Sim {'ready' if sim_ready else 'missing'} | Props {'ready' if props_ready else 'missing'}",
        "metrics": [
            {"label": "Games", "value": str(card_rows or games_count)},
            {"label": "Picks", "value": str(picks_count)},
            {"label": "Sim detail", "value": "Yes" if sim_ready else "No"},
            {"label": "Props snapshot", "value": "Yes" if props_ready else "No"},
        ],
        "summary": "This archived WNBA date is backed by stored processed slate files, so historical dates can reopen the real cards, picks, props, and live-lens family without a live fetch.",
        "list_items": [
            f"Cards file: {cards_path.name}",
            f"Recommendations file: {picks_path.name}",
            "Archive cards link into the cards board for the same stored date.",
        ],
        "href": f"/wnba/cards?date={date_str}",
        "href_label": "Open cards",
    }


def build_archive_page_context(selected_date: str | None) -> dict[str, Any]:
    dates = available_dates()
    requested_date = str(selected_date or default_date()).strip() or default_date()
    fallback = dates[-1] if dates else requested_date
    resolved_date = resolve_selected_value(requested_date, dates, fallback)
    window_dates = windowed_discrete_dates(dates, resolved_date)
    rank_cards = [_archive_card(date_str) for date_str in window_dates]
    rank_cards = selected_first_rank_cards(rank_cards, resolved_date)

    cards_path = processed_path_or_default(f"game_cards_{resolved_date}.csv")
    picks_path = processed_path_or_default(f"recommendations_slate_{resolved_date}.json")
    card_rows = _csv_row_count(cards_path)
    games_count, picks_count = _summary_counts(picks_path)

    using_sample_data = False

    context = build_discrete_date_archive_page_context(
        selected_date=requested_date,
        dates=dates,
        route_path="/wnba/archive",
        intro_title="WNBA Daily Archive",
        intro_body="This archive board turns stored WNBA processed dates into a daily archive lane, so past slates can reopen the shared cards and ranked-board family from real artifacts.",
        aria_label="WNBA daily archive board",
        source_path=f"{cards_path} | {picks_path}",
        source_title="WNBA daily archive artifacts" if rank_cards else "WNBA archive unavailable",
        rank_cards=rank_cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Archive dates", "value": str(len(dates))},
            {"label": "Selected games", "value": str(card_rows or games_count)},
            {"label": "Selected picks", "value": str(picks_count)},
            {"label": "Artifacts", "value": "2 files" if rank_cards else "No data"},
        ],
        module_links=build_module_links(requested_date, "Daily archive"),
        warning_panel={
            "eyebrow": "Historical lane",
            "title": "Archived WNBA dates reopen the shared board family",
            "body": "Use the daily archive when you want to start from stored processed dates, then drill into cards, picks, props, or live lens on that same slate.",
            "list_items": [
                *( [f"Requested date: {requested_date}", f"Showing stored slate: {resolved_date}"] if requested_date != resolved_date else [] ),
                "Each card summarizes one stored WNBA processed date.",
                "Archive cards jump directly into the cards board for the same day.",
            ],
        },
        source_date_display=resolved_date,
    )
    context["available_dates"] = dates
    if not rank_cards:
        context["empty_state"] = {
            "eyebrow": "WNBA daily archive",
            "title": "No stored WNBA archive dates were available",
            "body": "The archive board only renders stored WNBA slate dates, and none were available in the local mirror or sibling source repo.",
            "list_items": ["Mirror WNBA processed artifacts before using the archive lane."],
        }
    return context


def build_archive_api_payload(selected_date: str | None) -> dict[str, Any]:
    context = build_archive_page_context(selected_date)
    payload = build_discrete_date_archive_api_payload(context)
    payload["available_dates"] = context.get("available_dates")
    return payload