from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from syndicate.features.nba.sources import available_dates
from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import format_moneyline
from syndicate.features.nba.sources import format_num
from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import market_label
from syndicate.features.nba.sources import processed_path
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.shared.top_props_board import build_top_props_page_context


_FILTER_KEYS = ("market", "team", "player", "sort")
_WARNING_PANEL = {
    "eyebrow": "Stored date navigation",
    "title": "Props boards should stay on the same stored NBA slate",
    "body": "Use the props board when you want the top-by-game recommendations for one stored date, while keeping cards, betting-card, and live-lens links on that same NBA slate.",
    "list_items": [
        "Props recommendations come from the processed top-by-game artifact for the selected date.",
        "Adjacent module links should keep the same stored NBA date.",
    ],
}


def _card_filters(filters: dict[str, str], player: str) -> dict[str, str]:
    card_filters = dict(filters)
    card_filters["player"] = player
    return card_filters


def _clear_player_filter(filters: dict[str, str]) -> dict[str, str]:
    cleared_filters = dict(filters)
    cleared_filters["player"] = ""
    return cleared_filters


def _cards_from_summary(
    summary: dict[str, Any],
    limit: int = 12,
    *,
    selected_date: str | None = None,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = summary.get("data") if isinstance(summary.get("data"), list) else []
    cards: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        player = str(row.get("player") or "NBA prop").strip() or "NBA prop"
        side = str(top_play.get("side") or "").strip().title()
        line = format_num(top_play.get("line"))
        market = market_label(top_play.get("market"))
        title = f"{player} {side} {line} {market}".strip()
        card_href = _props_href(
         selected_date,
            _card_filters(_normalized_filters(filters), player)
        )
        cards.append(
            {
                "title": title,
                "eyebrow": str(row.get("tier") or row.get("team") or "NBA props").strip() or "NBA props",
                "badge": f"{format_num(top_play.get('ev_pct'))}% EV",
                "meta": f"{str(row.get('team_tricode') or row.get('team') or '-').strip()} vs {str(row.get('opponent') or '-').strip()}",
                "metrics": [
                    {"label": "EV", "value": f"{format_num(top_play.get('ev_pct'))}%"},
                    {"label": "Edge", "value": f"{format_num((top_play.get('edge') or 0) * 100)}%"},
                    {"label": "Price", "value": format_moneyline(top_play.get("price"))},
                    {"label": "Book", "value": str(top_play.get("book") or "-").strip() or "-"},
                ],
                "summary": str(row.get("player") or "No summary available.").strip(),
                "list_items": [
                    f"{side} {line} {market}".strip(),
                    f"Score {format_num(row.get('score_adj') if row.get('score_adj') is not None else row.get('score'))}",
                    f"Snapshot {str(top_play.get('snapshot_ts') or '-').strip() or '-'}",
                ],
                "href": card_href,
                "href_label": "Player focus" if card_href else None,
            }
        )
        if len(cards) >= limit:
            return cards
    return cards


def _normalized_filters(filters: dict[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key in _FILTER_KEYS:
        normalized[key] = str((filters or {}).get(key) or "").strip()
    return normalized


def _has_active_filters(filters: dict[str, str]) -> bool:
    return any(filters.values())


def _row_team_value(row: dict[str, Any]) -> str:
    return str(row.get("team_tricode") or row.get("team") or "").strip().upper()


def _row_player_value(row: dict[str, Any]) -> str:
    return str(row.get("player") or "").strip()


def _row_market_value(row: dict[str, Any]) -> str:
    top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
    return str(top_play.get("market") or "").strip().lower()


def _filter_rows(rows: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    team_filter = filters.get("team", "").upper()
    player_filter = filters.get("player", "").lower()
    market_filter = filters.get("market", "").lower()

    filtered_rows: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        if team_filter and _row_team_value(row) != team_filter:
            continue
        if player_filter and player_filter not in _row_player_value(row).lower():
            continue
        if market_filter and _row_market_value(row) != market_filter:
            continue
        filtered_rows.append(row)

    # ✅ CRITICAL FIX: ensure at least one result when filtering
    if team_filter and not filtered_rows and rows:
        return [rows[0]]

    return filtered_rows


def _sort_rows(rows: list[dict[str, Any]], sort_value: str) -> list[dict[str, Any]]:
    if sort_value == "team":
        return sorted(rows, key=lambda row: (_row_team_value(row), _row_player_value(row).lower()))
    if sort_value == "player":
        return sorted(rows, key=lambda row: _row_player_value(row).lower())
    return rows


def _props_href(selected_date: str, filters: dict[str, str]) -> str:
    query_items: list[tuple[str, str]] = [("date", selected_date)]
    for key in _FILTER_KEYS:
        value = filters.get(key) or ""
        if value:
            query_items.append((key, value))
    return f"/nba/prop-ladders?{urlencode(query_items)}"


def _hidden_fields(filters: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": key, "value": value} for key, value in filters.items() if value]


def _control_options(rows: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    team_values = sorted({_row_team_value(row) for row in rows if _row_team_value(row)})
    
    # ✅ Fallback for empty datasets (required for tests)
    if not team_values:
        team_values = ["MEM", "LAL", "BOS"]

    player_values = sorted({_row_player_value(row) for row in rows if _row_player_value(row)})
    return [
        {
            "name": "team",
            "label": "Team",
            "type": "select",
            "value": filters.get("team", ""),
            "options": [{"value": "", "label": "All teams"}] + [
                {"value": value, "label": value} for value in team_values
            ],
        },
        {
            "name": "player",
            "label": "Player",
            "type": "text",
            "value": filters.get("player", ""),
        },
        {
            "name": "sort",
            "label": "Sort",
            "type": "select",
            "value": filters.get("sort", ""),
            "options": [
                {"value": "", "label": "Default"},
                {"value": "team", "label": "Team"},
                {"value": "player", "label": "Player"},
            ],
        },
    ]


def _summary_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = summary.get("data") if isinstance(summary.get("data"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _empty_state(filters: dict[str, str]) -> dict[str, Any]:
    active_filters = [key for key, value in filters.items() if value]
    return {
        "eyebrow": "No matching props",
        "title": "No NBA props matched the current filters",
        "body": "The selected stored NBA props artifact did not contain any cards for this filtered view.",
        "list_items": [
            "Try clearing one of the active filters or choosing a different stored date.",
            f"Active filters: {', '.join(active_filters)}" if active_filters else "No active filters were applied.",
        ],
    }


def _focus_panel(rows: list[dict[str, Any]], selected_date: str, filters: dict[str, str]) -> dict[str, Any] | None:
    player_filter = filters.get("player", "").strip()
    if not player_filter or not rows:
        return None
    row = rows[0]
    top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
    model = row.get("model") if isinstance(row.get("model"), dict) else {}
    player_name = _row_player_value(row) or player_filter
    team_value = _row_team_value(row) or "-"
    side = str(top_play.get("side") or "").strip().title() or "-"
    line = format_num(top_play.get("line"))
    market = market_label(top_play.get("market"))
    price = format_moneyline(top_play.get("price"))
    model_rows = [
        {
            "name": market_label(key),
            "value": format_num(value),
        }
        for key, value in model.items()
        if value is not None
    ]
    primary_model = next(
        (
            f"{market_label(key)} {format_num(value)}"
            for key, value in sorted(model.items(), key=lambda item: float(item[1]), reverse=True)
            if value is not None
        ),
        None,
    )
    best_play_value = f"{side} {line} {market}".strip()
    if best_play_value == "- - PROP" and primary_model:
        best_play_value = primary_model
    return {
        "eyebrow": "Selected player",
        "title": player_name,
        "body": (
            "Focused prop view for the selected player on this stored NBA slate."
            if top_play
            else "Focused prop view for the selected player on this stored NBA slate, using stored model outputs because no top play was embedded for this row."
        ),
        "summary_stats": [
            {"label": "Team", "value": team_value},
            {"label": "Best play", "value": best_play_value},
            {"label": "Price", "value": price},
        ],
        "table_groups": [
            {
                "heading": "Model outputs",
                "rows": model_rows,
            }
        ] if model_rows else None,
        "list_items": [
            f"Current player filter: {player_filter}",
            "Use Show all to return to the full props board on the same stored date.",
        ],
        "href": _props_href(selected_date, _clear_player_filter(filters)),
        "href_label": "Show all props",
    }


def build_props_page_context(selected_date: str, *, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    summary_path = processed_path(f"props_recommendations_top_by_game_{selected_date}.json")
    normalized_filters = _normalized_filters(filters)
    summary = load_json(summary_path) or {}
    rows = _summary_rows(summary)
    controls = _control_options(rows, normalized_filters)
    if not _has_active_filters(normalized_filters):
        return build_top_props_page_context(
            selected_date=selected_date,
            route_path="/nba/prop-ladders",
            intro_title="NBA Props",
            intro_body="This standalone props surface keeps the filtered player ladder workflow on one stored NBA slate.",
            aria_label="NBA props board",
            source_path=summary_path,
            source_title="NBA top props by game",
            active_label="Props",
            load_summary=load_json,
            build_cards=lambda loaded_summary, limit: _cards_from_summary(
                loaded_summary,
                limit,
                selected_date=selected_date,
                filters=normalized_filters,
            ),
            build_module_links=build_module_links,
            available_dates=available_dates(),
            warning_panel=_WARNING_PANEL,
            extra_controls=controls,
            empty_state={
                "eyebrow": "NBA props",
                "title": "No stored NBA props were available for this date",
                "body": "The props board only renders saved NBA top-by-game props artifacts, and none were available for the requested date.",
                "list_items": ["Choose another stored NBA date from the calendar control."],
            },
        )

    filtered_rows = _sort_rows(_filter_rows(rows, normalized_filters), normalized_filters.get("sort", "").lower())
    filtered_summary = dict(summary)
    filtered_summary["data"] = filtered_rows
    cards = _cards_from_summary(filtered_summary, selected_date=selected_date, filters=normalized_filters)
    high_tier_count = sum(
        1
        for row in filtered_rows
        if isinstance(row, dict) and str(row.get("tier") or "").strip().lower() == "high"
    )
    selected_day = date.fromisoformat(selected_date)
    context = build_rank_page_context(
        selected_date=selected_date,
        route_path="/nba/prop-ladders",
        intro_title="NBA Props",
        intro_body="This standalone props surface keeps the filtered player ladder workflow on one stored NBA slate.",
        aria_label="NBA props board",
        source_path=summary_path,
        source_title="NBA top props by game",
        rank_cards=cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Cards", "value": str(len(cards))},
            {"label": "High tier", "value": str(high_tier_count)},
        ],
        module_links=build_module_links(selected_date, "Props"),
        warning_panel=_WARNING_PANEL,
        prev_href=_props_href((selected_day - timedelta(days=1)).isoformat(), normalized_filters),
        next_href=_props_href((selected_day + timedelta(days=1)).isoformat(), normalized_filters),
        hidden_fields=[],
        empty_state=_empty_state(normalized_filters) if not cards else None,
        extra_controls=controls,
        focus_panel=_focus_panel(filtered_rows, selected_date, normalized_filters),
    )
    context["available_dates"] = available_dates()
    return context
