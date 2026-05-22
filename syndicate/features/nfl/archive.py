from __future__ import annotations

from typing import Any

from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import recommendation_path
from syndicate.features.nfl.sources import tracked_week
from syndicate.features.nfl.sources import week_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context


def _resolved_week(selected_week: int, *, season: int) -> int:
    return resolve_selected_value(int(selected_week or default_week(season)), available_weeks(season), default_week(season))


def _archive_card(summary: dict[str, Any]) -> dict[str, Any]:
    season = int(summary.get("season") or latest_season())
    week = int(summary.get("week") or 0)
    count = int(summary.get("count") or 0)
    publish_count = int(summary.get("publish_count") or 0)
    has_full = bool(summary.get("has_full"))
    has_publish = bool(summary.get("has_publish"))
    return {
        "title": f"{season} Week {week}",
        "eyebrow": "Weekly snapshot",
        "badge": f"{count or publish_count} rows",
        "meta": f"Full {'yes' if has_full else 'no'} | Publish {'yes' if has_publish else 'no'}",
        "metrics": [
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(week)},
            {"label": "Rows", "value": str(count or publish_count)},
            {"label": "Publish", "value": "Yes" if has_publish else "No"},
        ],
        "summary": "This archived NFL week is backed by the stored weekly recommendation snapshot lane, so historical weeks can reopen the cards, picks, betting-card, and live-lens family without a live fetch.",
        "list_items": [
            f"Snapshot file: {recommendation_path(week, season=season).name}",
            "Archive cards jump directly into the betting-card board for the same stored week.",
        ],
        "href": f"/nfl/season/{season}/betting-card?week={week}",
        "href_label": "Open betting card",
    }


def build_archive_page_context(selected_week: int, *, season: int | None = None) -> dict[str, Any]:
    resolved_season = int(season or latest_season())
    summaries = [item for item in week_summaries() if int(item.get("season") or 0) == resolved_season]
    weeks = [int(item["week"]) for item in summaries]
    requested_week = int(selected_week or default_week(resolved_season))
    resolved_week = _resolved_week(requested_week, season=resolved_season) if weeks else requested_week
    cards = [_archive_card(item) for item in reversed(summaries)]
    cards.sort(key=lambda card: (0 if card.get("title") == f"{resolved_season} Week {resolved_week}" else 1, str(card.get("title") or "")))
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    tracked = tracked_week()

    context = build_rank_page_context(
        selected_date=f"{resolved_season}-01-{resolved_week:02d}",
        route_path="/nfl/archive",
        intro_title="NFL Daily Archive",
        intro_body="This archive board turns stored NFL weekly recommendation snapshots into a historical launch lane, so archived weeks can reopen the existing module family from real artifacts.",
        aria_label="NFL daily archive",
        source_path=recommendation_path(resolved_week, season=resolved_season),
        source_title="NFL weekly archive snapshot" if cards else "NFL archive unavailable",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Weeks", "value": str(len(weeks))},
            {"label": "Selected week", "value": str(resolved_week)},
            {"label": "Season", "value": str(resolved_season)},
            {"label": "Tracked week", "value": f"{tracked['season']} Week {tracked['week']}" if tracked else "-"},
        ],
        module_links=build_module_links(resolved_week, "Daily archive", season=resolved_season),
        warning_panel={
            "eyebrow": "Weekly snapshots",
            "title": "Archived NFL weeks reopen the stored board family",
            "body": "Use the daily archive when you want to start from stored weekly snapshots, then drill into betting card, cards, picks, or live lens on that same week.",
            "list_items": [
                "Each card summarizes one stored weekly recommendation snapshot.",
                "Archive cards jump directly into the betting-card board for the same week.",
            ],
        },
        source_date_display=f"{resolved_season} Week {resolved_week}",
        control_label="Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        prev_href=f"/nfl/archive?season={resolved_season}&week={prev_week}",
        next_href=f"/nfl/archive?season={resolved_season}&week={next_week}",
        reset_href=f"/nfl/archive?season={resolved_season}",
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
        submit_label="Apply",
        empty_state={
            "eyebrow": "NFL daily archive",
            "title": "No stored NFL archive weeks were available",
            "body": "The archive board only renders saved NFL weekly recommendation snapshots, and none were available for the requested season.",
            "list_items": ["Generate or sync weekly recommendation snapshots to populate this archive lane."],
        } if not cards else None,
    )
    context["season"] = resolved_season
    context["week"] = resolved_week
    context["available_weeks"] = weeks
    return context


def build_archive_api_payload(selected_week: int, *, season: int | None = None) -> dict[str, Any]:
    context = build_archive_page_context(selected_week, season=season)
    payload = build_rank_api_payload(context)
    payload["season"] = context["season"]
    payload["week"] = context["week"]
    payload["available_weeks"] = context["available_weeks"]
    return payload