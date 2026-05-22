from __future__ import annotations

from typing import Any

from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import summary_path
from syndicate.features.ncaaf.sources import week_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


def _archive_card(summary: dict[str, Any]) -> dict[str, Any]:
    season = int(summary.get("season") or default_season())
    week = int(summary.get("week") or 0)
    count = int(summary.get("count") or 0)
    return {
        "title": f"{season} Week {week}",
        "eyebrow": "Weekly snapshot",
        "badge": f"{count} rows",
        "meta": "Historical recommendation summary",
        "metrics": [
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(week)},
            {"label": "Rows", "value": str(count)},
        ],
        "summary": "This archived NCAAF week is backed by the saved recommendation summary index, so historical weeks can reopen cards, picks, live lens, and betting-card routes from real artifacts while the source feed is offseason-empty.",
        "list_items": [
            f"Snapshot file: {summary_path(week).name}",
            "Archive cards jump directly into the betting-card board for the same stored week.",
        ],
        "href": f"/ncaaf/season/{season}/betting-card?week={week}",
        "href_label": "Open betting card",
    }


def build_archive_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    summaries = [item for item in week_summaries() if int(item.get("season") or season) == season and item.get("has_data")]
    weeks = [int(item["week"]) for item in summaries]
    resolved_week = resolve_selected_value(int(selected_week or default_week()), weeks, default_week()) if weeks else int(selected_week or default_week())
    cards = [_archive_card(item) for item in reversed(summaries)]
    cards.sort(key=lambda card: (0 if card.get("title") == f"{season} Week {resolved_week}" else 1, str(card.get("title") or "")))
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)

    context = build_rank_page_context(
        selected_date=f"{season}-01-{resolved_week:02d}",
        route_path="/ncaaf/archive",
        intro_title="NCAAF Daily Archive",
        intro_body="This archive board turns stored NCAAF recommendation summaries into a historical launch lane, so archived weeks can reopen the module family from real weekly artifacts.",
        aria_label="NCAAF daily archive",
        source_path=summary_path(resolved_week),
        source_title="NCAAF weekly archive summary" if cards else "NCAAF archive unavailable",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Weeks", "value": str(len(weeks))},
            {"label": "Selected week", "value": str(resolved_week)},
            {"label": "Season", "value": str(season)},
        ],
        module_links=build_module_links(resolved_week, "Daily archive", season=season),
        warning_panel={
            "eyebrow": "Historical mode",
            "title": "Archived NCAAF weeks reopen the stored board family",
            "body": "Use the daily archive when you want to start from saved weekly summaries, then drill into betting card, cards, picks, or live lens on that same stored week.",
            "list_items": [
                "Each card summarizes one stored recommendation snapshot week.",
                "Archive cards jump directly into the betting-card board for the same week.",
            ],
        },
        source_date_display=f"{season} Week {resolved_week}",
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/ncaaf/archive?week={prev_week}",
        next_href=f"/ncaaf/archive?week={next_week}",
        reset_href="/ncaaf/archive",
        submit_label="Apply",
        empty_state={
            "eyebrow": "NCAAF daily archive",
            "title": "No stored NCAAF archive weeks were available",
            "body": "The archive board only renders saved NCAAF weekly recommendation summaries, and none were available for the tracked season.",
            "list_items": ["Generate or sync weekly recommendation summaries to populate this archive lane."],
        } if not cards else None,
    )
    context["week"] = resolved_week
    context["available_weeks"] = weeks
    context["season"] = season
    return context


def build_archive_api_payload(selected_week: int) -> dict[str, Any]:
    context = build_archive_page_context(selected_week)
    payload = build_rank_api_payload(context)
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    payload["season"] = context["season"]
    return payload