from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import daily_top_props_path
from syndicate.features.mlb.sources import load_json_file


def _parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return date.today()


def _format_pct(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number * 100:.1f}%"


def _format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _format_odds(value: Any) -> str:
    try:
        number = int(float(value))
    except Exception:
        return "-"
    return f"+{number}" if number > 0 else str(number)


def _cards_from_group(summary: dict[str, Any], group_key: str, *, limit: int = 12) -> tuple[list[dict[str, Any]], str]:
    groups = summary.get("groups") if isinstance(summary.get("groups"), dict) else {}
    target_group = groups.get(group_key) if isinstance(groups.get(group_key), dict) else {}
    sections = target_group.get("sections") if isinstance(target_group.get("sections"), list) else []
    if not sections:
        fallback = "Pitcher" if group_key == "pitcher" else "Hitter"
        return [], fallback
    first_section = sections[0] if isinstance(sections[0], dict) else {}
    rows = first_section.get("rows") if isinstance(first_section.get("rows"), list) else []
    fallback = "Pitcher" if group_key == "pitcher" else "Hitter"
    section_label = str(first_section.get("label") or target_group.get("title") or fallback).strip() or fallback
    cards: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        player_name = str(row.get("playerName") or row.get("ownerName") or "Unknown player").strip() or "Unknown player"
        selection_label = str(row.get("selectionLabel") or row.get("selection") or "Play").strip() or "Play"
        target_label = str(row.get("targetLabel") or "").strip()
        cards.append(
            {
                "title": player_name,
                "eyebrow": str(row.get("team") or "").strip() or "Top prop",
                "badge": f"{selection_label} {target_label}".strip(),
                "meta": str(row.get("matchup") or "").strip() or "-",
                "metrics": [
                    {"label": "Sim prob", "value": _format_pct(row.get("simProb"))},
                    {"label": "Edge", "value": _format_pct(row.get("rawEdge"))},
                    {"label": "Odds", "value": _format_odds(row.get("odds"))},
                    {"label": "Mean", "value": _format_num(row.get("mean"))},
                ],
                "summary": f"{player_name} rates as a {selection_label.lower()} on {str(row.get('statLabel') or 'this market').strip().lower()} with {_format_pct(row.get('simProb'))} simulated hit probability.",
                "list_items": [
                    f"Market line: {_format_num(row.get('line'))}",
                    f"Market probability: {_format_pct(row.get('marketProb'))}",
                    f"Rank: {row.get('rank') or '-'}",
                ],
            }
        )
    return cards, section_label


def build_top_props_page_context(selected_date: str, *, group: str = "pitcher") -> dict[str, Any]:
    parsed_date = _parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    module_links = build_module_links(selected_date, "Top props")

    summary_path = daily_top_props_path(selected_date)
    summary = load_json_file(summary_path)
    group_key = "hitter" if str(group or "pitcher").strip().lower() == "hitter" else "pitcher"
    group_label = "Hitter" if group_key == "hitter" else "Pitcher"
    cards, section_label = _cards_from_group(summary, group_key) if summary else ([], group_label)
    using_sample_data = False

    return {
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": module_links,
        "rank_cards": cards,
        "source_path": str(summary_path),
        "using_sample_data": using_sample_data,
        "source_title": "MLB top props artifact" if cards else "MLB top props unavailable",
        "header_stats": [
            {"label": "Rows", "value": str(len(cards))},
            {"label": "Section", "value": section_label},
            {"label": "Group", "value": group_label},
        ],
        "route_path": "/mlb/hitter-top-props" if group_key == "hitter" else "/mlb/pitcher-top-props",
        "intro_title": f"MLB {group_label} Top Props",
        "intro_body": f"This module reuses the shared ranked-board layout for prebuilt {group_label.lower()} prop recommendations from the daily top props artifact.",
        "aria_label": f"{group_label} top props board",
        "empty_state": {
            "eyebrow": "MLB top props",
            "title": f"No stored MLB {group_label.lower()} top props were available for this date",
            "body": "The top-props board only renders saved daily top-props artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored MLB date from the date control."],
        } if not cards else None,
    }