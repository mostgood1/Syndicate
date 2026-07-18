from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from typing import Any

from syndicate.features.mlb.sources import daily_ladders_path
from syndicate.features.mlb.sources import load_json_file


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return date.today()


def format_pct(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number * 100:.1f}%"


def format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _extract_prop_group(summary: dict[str, Any], side_key: str, prop_key: str) -> dict[str, Any]:
    groups = summary.get("groups") if isinstance(summary.get("groups"), dict) else {}
    side_group = groups.get(side_key) if isinstance(groups.get(side_key), dict) else {}
    return side_group.get(prop_key) if isinstance(side_group.get(prop_key), dict) else {}


def build_module_links(selected_date: str, active_label: str) -> list[dict[str, Any]]:
    links = [
        ("Cards", f"/mlb/cards?date={selected_date}"),
        ("Betting Card", f"/mlb/season/{selected_date[:4]}/betting-card?date={selected_date}"),
        ("Live Lens", f"/mlb/live-lens?date={selected_date}"),
        ("Market Accuracy", f"/mlb/market-accuracy?date={selected_date}"),
        ("Daily Archive", f"/mlb/archive?date={selected_date}"),
        ("Season Review", f"/mlb/season/{selected_date[:4]}?date={selected_date}"),
        ("Pitcher top props", f"/mlb/pitcher-top-props?date={selected_date}"),
        ("Hitter top props", f"/mlb/hitter-top-props?date={selected_date}"),
        ("Top props", f"/mlb/top-props?date={selected_date}"),
        ("HR targets", f"/mlb/hr-targets?date={selected_date}"),
        ("K ladder targets", f"/mlb/k-ladder-targets?date={selected_date}"),
        ("RFI targets", f"/mlb/rfi-targets?date={selected_date}"),
        ("Pitcher ladders", f"/mlb/pitcher-ladders?date={selected_date}"),
        ("Hitter ladders", f"/mlb/hitter-ladders?date={selected_date}"),
        ("Hub", "/mlb/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]


def pitcher_rows_from_summary(summary: dict[str, Any], *, limit: int = 12) -> tuple[list[dict[str, Any]], str]:
    prop_group = _extract_prop_group(summary, "pitcher", "strikeouts")
    rows = prop_group.get("rows") if isinstance(prop_group.get("rows"), list) else []
    prop_label = str(prop_group.get("propLabel") or "Strikeouts").strip() or "Strikeouts"
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        reasons = row.get("matchupReasons") if isinstance(row.get("matchupReasons"), list) else []
        matchup_summary = str(row.get("matchupSummary") or "").strip()
        fallback_summary = f"{row.get('pitcherName')} projects for {format_num(row.get('mean'))} {prop_label.lower()} against {row.get('opponent')}."
        out.append(
            {
                "title": str(row.get("pitcherName") or row.get("playerName") or "Unknown pitcher").strip() or "Unknown pitcher",
                "eyebrow": str(row.get("team") or "").strip() or "-",
                "badge": f"{format_num(row.get('marketLine'))} {prop_label[0]}" if row.get("marketLine") is not None else prop_label,
                "meta": str(row.get("matchup") or "").strip() or "-",
                "metrics": [
                    {"label": "Mean", "value": format_num(row.get("mean"))},
                    {"label": "Over", "value": format_pct(row.get("overLineProb"))},
                    {"label": "Mode", "value": format_num(row.get("mode"))},
                    {"label": "Sim count", "value": str(row.get("simCount") or "-")},
                ],
                "summary": matchup_summary or fallback_summary,
                "list_items": reasons[:4] if reasons else [
                    f"Market line: {format_num(row.get('marketLine'))}",
                    f"Over probability: {format_pct(row.get('overLineProb'))}",
                    f"Most likely outcome: {format_num(row.get('mode'))}",
                ],
            }
        )
    return out, prop_label


def hitter_rows_from_summary(summary: dict[str, Any], *, limit: int = 12) -> tuple[list[dict[str, Any]], str]:
    prop_group = _extract_prop_group(summary, "hitter", "hits")
    rows = prop_group.get("rows") if isinstance(prop_group.get("rows"), list) else []
    prop_label = str(prop_group.get("propLabel") or "Hits").strip() or "Hits"
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        reasons = row.get("matchupReasons") if isinstance(row.get("matchupReasons"), list) else []
        out.append(
            {
                "title": str(row.get("hitterName") or row.get("playerName") or "Unknown hitter").strip() or "Unknown hitter",
                "eyebrow": str(row.get("team") or "").strip() or "-",
                "badge": f"{format_num(row.get('marketLine'))} {prop_label}",
                "meta": str(row.get("matchup") or "").strip() or "-",
                "metrics": [
                    {"label": "Mean", "value": format_num(row.get("mean"))},
                    {"label": "Over", "value": format_pct(row.get("overLineProb"))},
                    {"label": "PA mean", "value": format_num(row.get("paMean"))},
                    {"label": "Order", "value": str(row.get("lineupOrder") or "-")},
                ],
                "summary": str(row.get("matchupSummary") or f"{row.get('hitterName')} projects for {format_num(row.get('mean'))} {prop_label.lower()} against {row.get('opponent')}.").strip(),
                "list_items": reasons[:4] if reasons else [
                    f"Market line: {format_num(row.get('marketLine'))}",
                    f"Over probability: {format_pct(row.get('overLineProb'))}",
                    f"Mode outcome: {format_num(row.get('mode'))}",
                ],
            }
        )
    return out, prop_label


def build_ladders_page_context(
    selected_date: str,
    *,
    active_label: str,
    route_path: str,
    source_title: str,
    intro_title: str,
    intro_body: str,
    aria_label: str,
    row_builder,
) -> dict[str, Any]:
    parsed_date = parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    ladders_path = daily_ladders_path(selected_date)
    summary = load_json_file(ladders_path)
    rows, prop_label = row_builder(summary) if summary else ([], "-")
    using_sample_data = False

    return {
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": build_module_links(selected_date, active_label),
        "rows": rows,
        "rank_cards": rows,
        "source_path": str(ladders_path),
        "using_sample_data": using_sample_data,
        "source_title": source_title if rows else f"{active_label} unavailable",
        "header_stats": [
            {"label": "Rows", "value": str(len(rows))},
            {"label": "Prop", "value": prop_label},
        ],
        "route_path": route_path,
        "intro_title": intro_title,
        "intro_body": intro_body,
        "aria_label": aria_label,
        "empty_state": {
            "eyebrow": active_label,
            "title": f"No stored {active_label.lower()} were available for this date",
            "body": "This board only renders saved daily ladders artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored MLB date from the date control."],
        } if not rows else None,
    }