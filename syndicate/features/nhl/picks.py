from __future__ import annotations

import csv
from typing import Any

from syndicate.features.nhl.sources import available_dates
from syndicate.features.nhl.sources import build_module_links
from syndicate.features.nhl.sources import default_date
from syndicate.features.nhl.sources import format_pct
from syndicate.features.nhl.sources import format_price
from syndicate.features.nhl.sources import market_label
from syndicate.features.nhl.sources import recommendation_path
from syndicate.features.nhl.sources import slate_summaries
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.rank_board import build_rank_page_context


def _read_rows(date_str: str) -> list[dict[str, Any]]:
    path = recommendation_path(date_str)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _resolved_date(selected_date: str | None) -> str:
    return resolve_selected_value(str(selected_date or default_date()), available_dates(), default_date())


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _float(row: dict[str, Any], key: str) -> float:
        try:
            return float(row.get(key) or 0.0)
        except Exception:
            return 0.0

    return sorted(rows, key=lambda row: (_float(row, "ev"), _float(row, "prob")), reverse=True)


def _build_cards(rows: list[dict[str, Any]], source_path: str, *, limit: int = 12) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    source_kind = "Sim snapshot" if "recommendations_sim_" in source_path else "Direct snapshot"
    for row in _sorted_rows(rows)[:limit]:
        home_team = str(row.get("home") or "Home").strip()
        away_team = str(row.get("away") or "Away").strip()
        market = market_label(row.get("market"))
        side = str(row.get("side") or "Recommended side").strip()
        totals_line = str(row.get("totals_line") or "-").strip() or "-"
        cards.append(
            {
                "title": side,
                "eyebrow": market,
                "badge": f"{format_pct(row.get('ev'))} EV",
                "meta": f"{away_team} at {home_team}",
                "metrics": [
                    {"label": "Win prob", "value": format_pct(row.get("prob"))},
                    {"label": "Price", "value": format_price(row.get("price"))},
                    {"label": "Confidence", "value": format_pct(row.get("conf"))},
                    {"label": "Total", "value": totals_line},
                ],
                "summary": (
                    f"The stored {market.lower()} snapshot prefers {side} for {away_team} at {home_team} "
                    f"based on the highest expected value rows available for the selected slate."
                ),
                "list_items": [
                    f"Market: {market}",
                    f"Home: {home_team}",
                    f"Away: {away_team}",
                    f"Source type: {source_kind}",
                ],
            }
        )
    return cards


def build_picks_page_context(selected_date: str | None) -> dict[str, Any]:
    requested_date = str(selected_date or default_date()).strip() or default_date()
    resolved_date = _resolved_date(selected_date)
    source_path = recommendation_path(resolved_date)
    rows = _read_rows(resolved_date)
    cards = _build_cards(rows, source_path.name)
    using_sample_data = False

    dates = available_dates()
    prev_date, next_date = neighboring_values(dates, requested_date, fallback=resolved_date)
    latest_date = dates[-1] if dates else resolved_date
    latest_kind = next((item["kind"] for item in reversed(slate_summaries()) if item["date"] == resolved_date), "Sim snapshot")
    warning_items = [f"Latest detected slate: {latest_date}"]
    if requested_date != resolved_date:
        warning_items.insert(0, f"Requested date: {requested_date}")
        warning_items.insert(1, f"Showing stored slate: {resolved_date}")
    summary_stats = [
        {"label": "Top cards", "value": str(len(cards))},
        {"label": "Rows", "value": str(len(rows) or 0)},
        {"label": "Slates", "value": str(len(dates) or 0)},
    ]

    return {
        **build_rank_page_context(
            selected_date=requested_date,
            route_path="/nhl/picks",
            intro_title="NHL Picks",
            intro_body="This page turns stored NHL recommendation snapshots into a standalone picks surface, so the top plays stay readable without falling back to the shared ranked-board shell.",
            aria_label="NHL picks board",
            source_path=source_path,
            source_title="NHL recommendation snapshot" if cards else "NHL picks unavailable",
            rank_cards=cards,
            using_sample_data=using_sample_data,
            header_stats=[
                {"label": "Cards", "value": str(len(cards))},
                {"label": "Rows", "value": str(len(rows) or "-")},
                {"label": "Slates", "value": str(len(dates) or "-")},
            ],
            module_links=build_module_links(requested_date, "Picks"),
            source_date_display=resolved_date,
            prev_href=f"/nhl/picks?date={prev_date}",
            next_href=f"/nhl/picks?date={next_date}",
            warning_panel={
                "eyebrow": latest_kind,
                "title": "NHL starts from persisted recommendation snapshots",
                "body": "The source repo already stores ranked daily recommendation CSVs, so Syndicate can lift the first NHL board directly from artifact-backed outputs before tackling the fuller source app UI.",
                "list_items": ["Date navigation follows the slates that actually have stored recommendation files.", *warning_items],
            },
            summary_panel={"summary_stats": summary_stats},
            reset_href="/nhl/picks",
            empty_state={
                "eyebrow": "NHL picks",
                "title": "No stored NHL picks were available for this date",
                "body": "The picks board only renders saved NHL recommendation snapshots, and none were available for the requested date.",
                "list_items": ["Choose another stored NHL date from the calendar control."],
            } if not cards else None,
        ),
        "available_dates": dates,
    }


def build_betting_card_page_context(season: int, selected_date: str | None) -> dict[str, Any]:
    context = dict(build_picks_page_context(selected_date))
    requested_date = str(context.get("date") or selected_date or default_date())
    resolved_date = str(context.get("source_date_display") or requested_date)
    resolved_season = int(season)
    dates = available_dates()
    prev_date, next_date = neighboring_values(dates, requested_date, fallback=resolved_date)
    context["route_path"] = f"/nhl/season/{resolved_season}/betting-card"
    context["intro_title"] = f"NHL {resolved_season} Betting Card"
    context["intro_body"] = "This historical NHL betting-card view reuses the stored recommendation snapshot lane under an MLB-shaped season betting-card route family."
    context["source_title"] = "NHL season betting-card snapshot" if context.get("rank_cards") else "NHL betting card unavailable"
    context["source_date_display"] = resolved_date
    context["module_links"] = build_module_links(requested_date, "Betting Card", season=resolved_season)
    context["prev_href"] = f"/nhl/season/{resolved_season}/betting-card?date={prev_date}"
    context["next_href"] = f"/nhl/season/{resolved_season}/betting-card?date={next_date}"
    context["reset_href"] = f"/nhl/season/{resolved_season}/betting-card"
    context["warning_panel"] = {
        "eyebrow": "Stored snapshots",
        "title": "NHL betting card currently reuses persisted recommendation files",
        "body": "This route gives NHL an MLB-shaped betting-card family without inventing new season-specific data plumbing before fuller season surfaces are ready.",
        "list_items": [
            "Date navigation follows the stored recommendation snapshots already present in the source repo.",
            *( [f"Showing stored slate: {resolved_date}"] if requested_date != resolved_date else [] ),
            "The ranked cards on this page are the same recommendation artifacts surfaced on the picks board.",
        ],
    }
    return context