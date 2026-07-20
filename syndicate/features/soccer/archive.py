from __future__ import annotations

from typing import Any

from syndicate.features.soccer.sources import available_dates
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import recommendations_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_api_payload
from syndicate.features.shared.date_archive import build_discrete_date_archive_page_context
from syndicate.features.shared.date_archive import selected_first_rank_cards
from syndicate.features.shared.date_archive import windowed_discrete_dates
from syndicate.features.shared.discrete_nav import resolve_selected_value


def _archive_card(league: str, date_str: str) -> dict[str, Any]:
    payload = recommendations_payload(league, date_str) or {}
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    league_label = league_display_name(league)
    return {
        "title": date_str,
        "eyebrow": f"{league_label} slate",
        "badge": f"{len(matches)} matches",
        "meta": f"{league_label} SoccerSim artifact",
        "metrics": [
            {"label": "Matches", "value": str(len(matches))},
            {"label": "Player props", "value": str(len(payload.get("player_props") or []))},
            {"label": "League", "value": league_label},
        ],
        "summary": f"This archive date is sourced directly from the stored {league_label} SoccerSim recommendations artifact.",
        "list_items": [
            f"Matches simulated: {len(matches)}",
            f"Archive date: {date_str}",
        ],
        "href": f"/soccer/{league}/cards?date={date_str}",
        "href_label": "Open cards board",
    }


def build_archive_page_context(league: str, selected_date: str) -> dict[str, Any]:
    league = normalize_league(league)
    league_label = league_display_name(league)
    dates = available_dates(league)
    fallback = dates[-1] if dates else selected_date
    resolved_date = resolve_selected_value(selected_date or fallback, dates, fallback)
    window_dates = windowed_discrete_dates(dates, resolved_date)
    cards = [_archive_card(league, date_str) for date_str in window_dates]
    cards = selected_first_rank_cards(cards, resolved_date)

    selected_payload = recommendations_payload(league, resolved_date) or {}
    selected_matches = selected_payload.get("matches") if isinstance(selected_payload.get("matches"), list) else []

    context = build_discrete_date_archive_page_context(
        selected_date=resolved_date,
        dates=dates,
        route_path=f"/soccer/{league}/archive",
        intro_title=f"{league_label} Daily Archive",
        intro_body=f"This archive board lists stored {league_label} SoccerSim dates and links each one back into the cards board for matchup-level detail.",
        aria_label=f"{league_label} daily archive",
        source_path=f"data/soccer_source/{league}/api/recommendations/",
        source_title=f"{league_label} SoccerSim archive" if cards else f"{league_label} archive unavailable",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Archive dates", "value": str(len(dates))},
            {"label": "Selected matches", "value": str(len(selected_matches))},
            {"label": "League", "value": league_label},
        ],
        module_links=build_module_links(league, resolved_date, "Daily archive"),
        warning_panel={
            "eyebrow": "Archive lane",
            "title": "Daily archive dates drill back into cards",
            "body": "Use this archive to browse stored SoccerSim dates, then jump into the cards board for matchup-level detail.",
            "list_items": [
                "Each card summarizes one stored date from the SoccerSim recommendations artifact.",
                f"Run scripts/build_soccer_artifacts.py --league {league} to add more dates.",
            ],
        },
        source_date_display=resolved_date,
    )
    if not cards:
        context["empty_state"] = {
            "eyebrow": f"{league_label} daily archive",
            "title": "No stored SoccerSim dates were available",
            "body": "The daily archive only renders stored SoccerSim artifact dates, and none were available for the selected window.",
            "list_items": [f"Run scripts/build_soccer_artifacts.py --league {league} to populate this archive lane."],
        }
    return context


def build_archive_api_payload(league: str, selected_date: str) -> dict[str, Any]:
    context = build_archive_page_context(league, selected_date)
    return build_discrete_date_archive_api_payload(context)
