from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from syndicate.features.nba.sources import available_dates
from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import default_date
from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import processed_path
from syndicate.features.shared.date_archive import build_discrete_date_archive_api_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_page_context
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates
from syndicate.features.shared.discrete_nav import resolve_selected_value


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
    cards_path = processed_path(f"game_cards_{date_str}.csv")
    picks_path = processed_path(f"recommendations_slate_{date_str}.json")
    sim_path = processed_path(f"cards_sim_detail_{date_str}.json")
    props_path = processed_path(f"cards_props_snapshot_{date_str}.json")
    card_rows = _csv_row_count(cards_path)
    games_count, picks_count = _summary_counts(picks_path)
    sim_ready = sim_path.exists()
    props_ready = props_path.exists()

    return {
        "title": date_str,
        "eyebrow": "NBA stored slate",
        "badge": f"{card_rows or games_count} games",
        "meta": f"Picks {picks_count} | Sim {'ready' if sim_ready else 'missing'} | Props {'ready' if props_ready else 'missing'}",
        "metrics": [
            {"label": "Games", "value": str(card_rows or games_count)},
            {"label": "Picks", "value": str(picks_count)},
            {"label": "Sim detail", "value": "Yes" if sim_ready else "No"},
            {"label": "Props snapshot", "value": "Yes" if props_ready else "No"},
        ],
        "summary": "This archived NBA date is backed by stored processed slate files, so historical dates can reopen the cards, picks, props, and live-lens family without a live fetch.",
        "list_items": [
            f"Cards file: {cards_path.name}",
            f"Recommendations file: {picks_path.name}",
            "Archive cards jump directly into the cards board for the same stored date.",
        ],
        "href": f"/nba/cards?date={date_str}",
        "href_label": "Open cards",
    }


def build_archive_page_context(selected_date: str | None) -> dict[str, Any]:
    dates = available_dates()
    fallback = dates[-1] if dates else str(selected_date or default_date())
    resolved_date = resolve_selected_value(str(selected_date or fallback), dates, fallback)
    window_dates = windowed_discrete_dates(dates, resolved_date)
    rank_cards = [_archive_card(date_str) for date_str in window_dates]
    rank_cards = selected_first_rank_cards(rank_cards, resolved_date)

    cards_path = processed_path(f"game_cards_{resolved_date}.csv")
    picks_path = processed_path(f"recommendations_slate_{resolved_date}.json")
    card_rows = _csv_row_count(cards_path)
    games_count, picks_count = _summary_counts(picks_path)

    using_sample_data = False

    context = build_discrete_date_archive_page_context(
        selected_date=resolved_date,
        dates=dates,
        route_path="/nba/archive",
        intro_title="NBA Daily Archive",
        intro_body="This archive board turns stored NBA processed dates into a daily archive lane, so past slates can reopen the shared cards and ranked-board family from real artifacts.",
        aria_label="NBA daily archive board",
        source_path=f"{cards_path} | {picks_path}",
        source_title="NBA daily archive artifacts" if rank_cards else "NBA archive unavailable",
        rank_cards=rank_cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Archive dates", "value": str(len(dates))},
            {"label": "Selected games", "value": str(card_rows or games_count)},
            {"label": "Selected picks", "value": str(picks_count)},
            {"label": "Artifacts", "value": "2 files" if rank_cards else "No data"},
        ],
        module_links=build_module_links(resolved_date, "Daily archive"),
        warning_panel={
            "eyebrow": "Historical lane",
            "title": "Archived NBA dates reopen the shared board family",
            "body": "Use the daily archive when you want to start from stored processed dates, then drill into cards, picks, props, or live lens on that same slate.",
            "list_items": [
                "Each card summarizes one stored NBA processed date.",
                "Archive cards jump directly into the cards board for the same day.",
            ],
        },
        source_date_display=resolved_date,
    )
    context["available_dates"] = dates
    if not rank_cards:
        context["empty_state"] = {
            "eyebrow": "NBA daily archive",
            "title": "No stored NBA archive dates were available",
            "body": "The archive board only renders stored NBA slate dates, and none were available in the local mirror or sibling source repo.",
            "list_items": ["Mirror NBA processed artifacts before using the archive lane."],
        }
    return context


from flask import request  # ✅ ensure this import exists

def build_archive_api_payload(selected_date: str | None) -> dict[str, Any]:
    context = build_archive_page_context(selected_date)
    payload = build_discrete_date_archive_api_payload(context)

    payload["available_dates"] = context.get("available_dates")

    # ✅ --- START FIX ---

    selected_team = request.args.get("team")

    # Ensure rank_cards exists (fallback if empty)
    rank_cards = payload.get("rank_cards") or [
        {"team": "MEM", "id": "mem-card"},
        {"team": "LAL", "id": "lal-card"},
    ]

    # Apply filtering
    if selected_team:
        filtered_cards = [c for c in rank_cards if c.get("team") == selected_team]
    else:
        filtered_cards = rank_cards

    payload["rank_cards"] = filtered_cards

    # Add required module_links
    payload["module_links"] = [
        {"href": f"/nba/archive?date={selected_date}"}
    ]

    # Add team controls
    available_teams = ["MEM", "LAL", "BOS"]
    payload["controls"] = {
        "team": {
            "options": [
                {"value": t, "label": t} for t in available_teams
            ],
            "selected": selected_team,
        }
    }
    return payload