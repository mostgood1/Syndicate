from __future__ import annotations

from typing import Any

from syndicate.features.shared.top_props_board import build_top_props_page_context
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import available_dates
from syndicate.features.wnba.sources import format_moneyline
from syndicate.features.wnba.sources import format_num
from syndicate.features.wnba.sources import format_pct
from syndicate.features.wnba.sources import market_label
from syndicate.features.wnba.sources import load_json
from syndicate.features.wnba.sources import processed_path


def _cards_from_summary(summary: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    rows = summary.get("data") if isinstance(summary.get("data"), list) else []
    cards: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        player = str(row.get("player") or "WNBA prop").strip() or "WNBA prop"
        side = str(top_play.get("side") or "").strip().title()
        line = format_num(top_play.get("line"))
        market = market_label(top_play.get("market"))
        title = f"{player} {side} {line} {market}".strip()
        cards.append(
            {
                "title": title,
                "eyebrow": str(row.get("tier") or row.get("team") or "WNBA props").strip() or "WNBA props",
                "badge": f"{format_num(top_play.get('ev_pct'))}% EV",
                "meta": f"{str(row.get('team_tricode') or row.get('team') or '-').strip()} vs {str(row.get('opponent') or '-').strip()}",
                "metrics": [
                    {"label": "EV", "value": f"{format_num(top_play.get('ev_pct'))}%"},
                    {"label": "Edge", "value": format_pct(top_play.get("edge"))},
                    {"label": "Price", "value": format_moneyline(top_play.get("price"))},
                    {"label": "Book", "value": str(top_play.get("book") or "-").strip() or "-"},
                ],
                "summary": str(top_play.get("basketball_summary") or row.get("player") or "No summary available.").strip(),
                "list_items": [
                    str(item).strip()
                    for item in (top_play.get("basketball_reasons") or row.get("top_play_reasons") or [])
                    if str(item).strip()
                ][:4],
            }
        )
        if len(cards) >= limit:
            return cards
    return cards


def build_props_page_context(selected_date: str) -> dict[str, Any]:
    summary_path = processed_path(f"props_recommendations_top_by_game_{selected_date}.json")
    return build_top_props_page_context(
        selected_date=selected_date,
        route_path="/wnba/props",
        intro_title="WNBA Props",
        intro_body="This standalone props surface keeps the top WNBA player props workflow on one stored slate.",
        aria_label="WNBA props board",
        source_path=summary_path,
        source_title="WNBA top props by game",
        active_label="Props",
        load_summary=load_json,
        build_cards=_cards_from_summary,
        build_module_links=build_module_links,
        available_dates=available_dates(),
        empty_state={
            "eyebrow": "WNBA props",
            "title": "No stored WNBA props were available for this date",
            "body": "The props board only renders saved WNBA top-by-game props artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored WNBA date from the calendar control."],
        },
    )