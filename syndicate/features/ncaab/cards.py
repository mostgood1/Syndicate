from __future__ import annotations

from typing import Any

from syndicate.features.ncaab.sources import build_module_links
from syndicate.features.ncaab.sources import default_date
from syndicate.features.ncaab.sources import mirrored_available_dates
from syndicate.features.ncaab.sources import mirrored_recommendations_payload
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _format_num(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _format_signed_price(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _row_rank(row: dict[str, Any]) -> tuple[float, float]:
    return (
        _safe_float(row.get("recommendation_priority_score")) or 0.0,
        _safe_float(row.get("abs_edge")) or _safe_float(row.get("edge")) or 0.0,
    )


def _group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_game: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        by_game.setdefault(game_id, []).append(row)

    games: list[dict[str, Any]] = []
    type_order = {"OU": 0, "ATS": 1, "ML": 2}
    for game_id, items in by_game.items():
        best_by_code: dict[str, dict[str, Any]] = {}
        for item in sorted(items, key=_row_rank, reverse=True):
            code = str(item.get("rec_code") or item.get("code") or "Other").upper()
            if code not in best_by_code:
                best_by_code[code] = item
        ordered = sorted(best_by_code.values(), key=lambda row: type_order.get(str(row.get("rec_code") or row.get("code") or "Other").upper(), 9))
        if not ordered:
            continue
        rep = max(best_by_code.values(), key=_row_rank)
        away_team = str(rep.get("away_team") or "Away").strip() or "Away"
        home_team = str(rep.get("home_team") or "Home").strip() or "Home"
        away_logo = str(rep.get("away_logo") or "").strip()
        home_logo = str(rep.get("home_logo") or "").strip()
        top_bet = str(rep.get("bet_label") or rep.get("pick") or "Recommendation").strip() or "Recommendation"
        summary = str(rep.get("basketball_summary") or rep.get("summary") or "").strip() or f"{top_bet} is the top source recommendation for this matchup."
        games.append(
            {
                "gamePk": game_id,
                "card_variant": "shared_default",
                "away": {"abbr": away_team[:3].upper(), "name": away_team, "logo": away_logo},
                "home": {"abbr": home_team[:3].upper(), "name": home_team, "logo": home_logo},
                "status": str(rep.get("display_date") or rep.get("date") or "TBD"),
                "detail": str(rep.get("display_time_str") or rep.get("start_time_display") or "TBD"),
                "summary": summary,
                "href": f"/ncaab/game/{game_id}?date={str(rep.get('display_date') or rep.get('date') or '').strip() or 'TBD'}",
                "href_label": "Open game card",
                "metrics": [
                    {"label": "Top bet", "value": top_bet},
                    {"label": "Price", "value": _format_signed_price(rep.get("price") or rep.get("line_value"))},
                    {"label": "Edge", "value": _format_num(abs(_safe_float(rep.get("abs_edge")) or abs(_safe_float(rep.get("edge")) or 0.0)))},
                    {"label": "Confidence", "value": _format_pct(rep.get("confidence"))},
                    {"label": "Priority", "value": _format_num(rep.get("recommendation_priority_score"))},
                ],
                "panels": [
                    {
                        "eyebrow": "Top source card",
                        "title": str(rep.get("book") or "Source book").strip() or "Source book",
                        "body": "The first NCAAB Syndicate board lifts the grouped recommendations workflow from the source app into the shared game-board shell.",
                        "items": [
                            f"Bet: {top_bet}",
                            f"Market: {str(rep.get('market') or rep.get('rec_type') or 'market').strip()}",
                            f"Price: {_format_signed_price(rep.get('price') or rep.get('line_value'))}",
                        ],
                    },
                    {
                        "eyebrow": "Matchup lens",
                        "title": f"Confidence {_format_pct(rep.get('confidence'))} | Priority {_format_num(rep.get('recommendation_priority_score'))}",
                        "body": summary,
                        "items": [
                            *(str(reason).strip() for reason in (rep.get("basketball_reasons") or [])[:3] if str(reason).strip()),
                            f"Pred margin: {_format_num(rep.get('pred_margin'))}",
                        ],
                    },
                    {
                        "eyebrow": "Game context",
                        "title": str(rep.get("display_date") or rep.get("date") or "TBD"),
                        "body": f"{away_team} at {home_team} on {str(rep.get('display_time_str') or rep.get('start_time_display') or 'TBD').strip() or 'TBD' }.",
                        "items": [
                            f"Source game id: {game_id}",
                            f"Selection: {str(rep.get('selection') or rep.get('pick') or top_bet).strip()}",
                        ],
                    },
                ],
            }
        )
    return games


def build_cards_page_context(selected_date: str) -> dict[str, Any]:
    resolved_date = str(selected_date or default_date()).strip() or default_date()
    season = int(resolved_date[:4]) if len(resolved_date) >= 4 and resolved_date[:4].isdigit() else 2025
    payload = mirrored_recommendations_payload(resolved_date) or {}
    rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    games = _group_rows(rows)
    using_sample_data = False

    dates = mirrored_available_dates()
    prev_date, next_date = neighboring_values(dates, resolved_date, fallback=resolved_date)
    source_path = f"data/ncaab_source/api/recommendations/recommendations_{resolved_date}.json"
    return apply_game_board_contract(
        {
            "date": resolved_date,
            "requested_date": selected_date or resolved_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "control_action": "/ncaab/cards",
            "controls_prev_href": f"/ncaab/cards?date={prev_date}",
            "controls_next_href": f"/ncaab/cards?date={next_date}",
            "control_value": resolved_date,
            "module_links": build_module_links(resolved_date, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["detail"],
                }
                for game in games
            ],
            "source_path": source_path,
            "source_title": "NCAAB mirrored cards" if games else "NCAAB cards unavailable",
            "empty_state": {
                "eyebrow": "NCAAB cards",
                "title": "No game cards were available for this date",
                "body": "The cards board only renders mirrored NCAAB recommendation groups, and none were available for the requested date.",
                "list_items": [
                    f"Requested date: {selected_date or resolved_date}",
                    "Choose another mirrored NCAAB date from the date control or refresh the source mirror.",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/ncaab/cards",
            "intro_title": "NCAAB Cards",
            "intro_body": "NCAAB cards now render directly from mirrored recommendation groups, keeping the shared board contract without runtime source-app fallback.",
            "cards_control_links": [
                {"label": "Betting Card", "href": f"/ncaab/season/{season}/betting-card?date={resolved_date}"},
                {"label": "Live Lens", "href": f"/ncaab/live-lens?date={resolved_date}"},
                {"label": "Season Review", "href": f"/ncaab/season/{season}?date={resolved_date}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Rows", "value": str(len(rows) or "-")},
                {"label": "Dates", "value": str(len(dates) or "-")},
                {"label": "Source", "value": "Mirror" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "NCAAB",
        },
        sport="ncaab",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=False,
    )