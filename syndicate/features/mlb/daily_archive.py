from __future__ import annotations

from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import season_frontend_day_path
from syndicate.features.shared.date_archive import build_discrete_date_archive_api_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_page_context
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates
from syndicate.features.shared.discrete_nav import resolve_selected_value


def _fmt_yes_no(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def _archive_card(date_str: str) -> dict[str, Any]:
    season = int(str(date_str or "")[:4] or 0)
    summary_payload = load_json_file(daily_artifact_path(date_str)) or {}
    season_payload = load_json_file(season_frontend_day_path(season, date_str)) or {}

    outputs = summary_payload.get("outputs") if isinstance(summary_payload.get("outputs"), list) else []
    games = season_payload.get("games") if isinstance(season_payload.get("games"), list) else []
    betting = season_payload.get("betting") if isinstance(season_payload.get("betting"), dict) else {}
    selected_counts = betting.get("selected_counts") if isinstance(betting.get("selected_counts"), dict) else {}
    combined_picks = int(selected_counts.get("combined") or 0)
    ml_picks = int(selected_counts.get("ml") or 0)
    pitcher_prop_picks = int(selected_counts.get("pitcher_props") or 0)
    hitter_prop_picks = int(selected_counts.get("hitter_props") or 0)
    game_count = len(games) or len(outputs)
    cards_available = bool(season_payload.get("cards_available"))

    return {
        "title": date_str,
        "eyebrow": f"Season {season} archive",
        "badge": f"{game_count} games",
        "meta": f"Official picks {combined_picks} | Cards {'ready' if cards_available else 'missing'}",
        "metrics": [
            {"label": "Games", "value": str(game_count)},
            {"label": "Official picks", "value": str(combined_picks)},
            {"label": "ML picks", "value": str(ml_picks)},
            {"label": "Cards ready", "value": _fmt_yes_no(cards_available)},
        ],
        "summary": "This archived MLB date is backed by stored daily summary and season-day artifacts, so you can jump into the season-review board without depending on a live source fetch.",
        "list_items": [
            f"Pitcher prop picks: {pitcher_prop_picks}",
            f"Hitter prop picks: {hitter_prop_picks}",
            f"Season-day games stored: {len(games)}",
        ],
        "href": f"/mlb/season/{season}?date={date_str}",
        "href_label": "Open season review",
    }


def build_daily_archive_page_context(selected_date: str) -> dict[str, Any]:
    dates = available_daily_summary_dates()
    fallback = dates[-1] if dates else selected_date
    resolved_date = resolve_selected_value(selected_date or fallback, dates, fallback)
    window_dates = windowed_discrete_dates(dates, resolved_date)
    cards = [_archive_card(date_str) for date_str in window_dates]
    cards = selected_first_rank_cards(cards, resolved_date)

    season = int(str(resolved_date or "")[:4] or 0)
    selected_season_payload = load_json_file(season_frontend_day_path(season, resolved_date)) or {}
    selected_summary_payload = load_json_file(daily_artifact_path(resolved_date)) or {}
    selected_games = selected_season_payload.get("games") if isinstance(selected_season_payload.get("games"), list) else []
    selected_outputs = selected_summary_payload.get("outputs") if isinstance(selected_summary_payload.get("outputs"), list) else []
    selected_counts = (((selected_season_payload.get("betting") or {}).get("selected_counts")) if isinstance(selected_season_payload.get("betting"), dict) else {}) or {}

    using_sample_data = False

    context = build_discrete_date_archive_page_context(
        selected_date=resolved_date,
        dates=dates,
        route_path="/mlb/archive",
        intro_title="MLB Daily Archive",
        intro_body="This archive board turns stored MLB day artifacts into a historical launch lane for season review, so archived dates stay one click away from the live module family.",
        aria_label="MLB daily archive",
        source_path=f"{daily_artifact_path(resolved_date)} | {season_frontend_day_path(season, resolved_date)}",
        source_title="MLB archived day artifacts" if cards else "MLB daily archive unavailable",
        rank_cards=cards,
        using_sample_data=using_sample_data,
        header_stats=[
            {"label": "Archive dates", "value": str(len(dates))},
            {"label": "Selected games", "value": str(len(selected_games) or len(selected_outputs))},
            {"label": "Official picks", "value": str(int(selected_counts.get("combined") or 0))},
            {"label": "Cards ready", "value": _fmt_yes_no(selected_season_payload.get("cards_available"))},
        ],
        module_links=build_module_links(resolved_date, "Daily archive"),
        warning_panel={
            "eyebrow": "Historical lane",
            "title": "Archived dates drill into season review",
            "body": "Use the daily archive when you want to start from stored artifact dates, then open season review for the per-game board on that same day.",
            "list_items": [
                "Each card summarizes one stored MLB day artifact date.",
                "Archive cards link into the existing season-review board for the same date.",
            ],
        },
        source_date_display=resolved_date,
    )
    if not cards:
        context["empty_state"] = {
            "eyebrow": "MLB daily archive",
            "title": "No stored MLB archive dates were available",
            "body": "The daily archive only renders stored MLB day artifacts, and none were available for the requested date set.",
            "list_items": ["Refresh or mirror MLB day artifacts to populate this archive lane."],
        }
    return context


def build_daily_archive_api_payload(selected_date: str) -> dict[str, Any]:
    context = build_daily_archive_page_context(selected_date)
    return build_discrete_date_archive_api_payload(context)