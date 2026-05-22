from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from syndicate.features.nhl.sources import available_dates
from syndicate.features.nhl.sources import build_module_links
from syndicate.features.nhl.sources import default_date
from syndicate.features.nhl.sources import processed_path
from syndicate.features.nhl.sources import recommendation_path
from syndicate.features.nhl.sources import slate_summaries
from syndicate.features.shared.date_archive import build_discrete_date_archive_api_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_page_context
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates
from syndicate.features.shared.discrete_nav import resolve_selected_value


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except Exception:
        return 0


def _archive_card(date_str: str, kind: str) -> dict[str, Any]:
    recommendation = recommendation_path(date_str)
    predictions = processed_path(f"predictions_{date_str}.csv")
    rec_rows = _row_count(recommendation)
    game_rows = _row_count(predictions)
    cards_ready = "ready" if game_rows else "missing"

    return {
        "title": date_str,
        "eyebrow": kind,
        "badge": f"{game_rows or rec_rows} rows",
        "meta": f"Games {game_rows} | Picks {rec_rows} | Cards {cards_ready}",
        "metrics": [
            {"label": "Games", "value": str(game_rows)},
            {"label": "Picks", "value": str(rec_rows)},
            {"label": "Cards ready", "value": "Yes" if game_rows else "No"},
            {"label": "Snapshot", "value": kind.replace(" snapshot", "")},
        ],
        "summary": "This archived NHL slate is backed by stored daily recommendation and prediction files, so historical dates can launch into the existing board family without relying on a live fetch.",
        "list_items": [
            f"Recommendation file: {recommendation.name}",
            f"Prediction file: {predictions.name}",
            "Archive cards link into the live-lens board for the same stored date.",
        ],
        "href": f"/nhl/live-lens?date={date_str}",
        "href_label": "Open live lens",
    }


def build_archive_page_context(selected_date: str | None) -> dict[str, Any]:
    dates = available_dates()
    requested_date = str(selected_date or default_date()).strip() or default_date()
    fallback = dates[-1] if dates else requested_date
    resolved_date = resolve_selected_value(requested_date, dates, fallback)
    kinds_by_date = {str(item.get("date") or ""): str(item.get("kind") or "Stored snapshot") for item in slate_summaries()}
    window_dates = windowed_discrete_dates(dates, resolved_date)
    rank_cards = [_archive_card(date_str, kinds_by_date.get(date_str, "Stored snapshot")) for date_str in window_dates]
    rank_cards = selected_first_rank_cards(rank_cards, resolved_date)

    recommendation = recommendation_path(resolved_date)
    predictions = processed_path(f"predictions_{resolved_date}.csv")
    rec_rows = _row_count(recommendation)
    game_rows = _row_count(predictions)
    using_sample_data = False

    context = build_discrete_date_archive_page_context(
        selected_date=requested_date,
        dates=dates,
        route_path="/nhl/archive",
        intro_title="NHL Daily Archive",
        intro_body="This archive board turns stored NHL snapshot dates into a daily archive lane, so past slates can reopen the real card, pick, and live-lens family from artifact-backed dates.",
        aria_label="NHL daily archive board",
        source_path=f"{recommendation} | {predictions}",
        source_title="NHL daily archive files" if rank_cards else "NHL archive unavailable",
        rank_cards=rank_cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Archive dates", "value": str(len(dates))},
            {"label": "Selected games", "value": str(game_rows)},
            {"label": "Selected picks", "value": str(rec_rows)},
            {"label": "Artifacts", "value": "2 files" if rank_cards else "No data"},
        ],
        module_links=build_module_links(requested_date, "Daily archive"),
        warning_panel={
            "eyebrow": "Historical lane",
            "title": "Archived NHL dates reopen the live board family",
            "body": "Use the daily archive when you want to start from dates that already have stored recommendation and prediction files, then drill into live lens or cards on that same slate.",
            "list_items": [
                *( [f"Requested date: {requested_date}", f"Showing stored slate: {resolved_date}"] if requested_date != resolved_date else [] ),
                "Each card summarizes one stored NHL snapshot date.",
                "Archive cards jump directly into the live-lens board for the same day.",
            ],
        },
        source_date_display=resolved_date,
    )
    context["available_dates"] = dates
    if not rank_cards:
        context["empty_state"] = {
            "eyebrow": "NHL daily archive",
            "title": "No stored NHL archive dates were available",
            "body": "The archive board only renders stored NHL snapshot dates, and none were available in the local mirror or sibling source repo.",
            "list_items": ["Mirror NHL processed snapshots before using the archive lane."],
        }
    return context


def build_archive_api_payload(selected_date: str | None) -> dict[str, Any]:
    context = build_archive_page_context(selected_date)
    payload = build_discrete_date_archive_api_payload(context)
    payload["available_dates"] = context.get("available_dates")
    return payload