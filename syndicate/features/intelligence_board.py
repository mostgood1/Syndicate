"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Builds intelligence board payloads for UI presentation and summaries.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import re

from typing import Any, Mapping


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_text(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            continue
        try:
            return float(text.replace("%", ""))
        except Exception:
            continue
    return None


def _movement_summary(item: Mapping[str, Any]) -> str:
    movement = item.get("movement") if isinstance(item.get("movement"), Mapping) else {}
    delta = _number(
        movement.get("delta") if isinstance(movement, Mapping) else None,
        movement.get("edge_delta") if isinstance(movement, Mapping) else None,
        item.get("line_movement_impact"),
        item.get("ev_delta"),
        item.get("ev_change"),
    )
    trend = _safe_text(
        movement.get("trend") if isinstance(movement, Mapping) else None,
        movement.get("recent_movement_trend") if isinstance(movement, Mapping) else None,
        item.get("movement_label"),
        default="flat",
    ).lower()
    if delta is not None and delta != 0:
        prefix = "+" if delta > 0 else ""
        return f"{prefix}{delta:.1f} ({trend})"
    if trend:
        return trend
    return "flat"


def _is_time_like_status(status: str) -> bool:
    if not status:
        return False
    lowered = status.lower()
    return bool(
        re.search(r"\b\d{1,2}:\d{2}\s?(?:am|pm)\b", lowered)
        or re.search(r"\b(?:ct|et|pt|mt|st)\b", lowered)
    )


def _is_pregame_status(status: str) -> bool:
    lowered = status.lower()
    return bool(
        lowered
        and (
            _is_time_like_status(lowered)
            or any(token in lowered for token in ("pre-game", "pregame", "scheduled", "preview", "warmup", "not started", "lineups"))
        )
    )


def _is_live_status(status: str) -> bool:
    lowered = status.lower()
    return bool(
        lowered
        and any(token in lowered for token in ("live", "in progress", "top of", "bottom of", "inning", "quarter", "period", "half"))
    )


def _recommendation_lane(item: Mapping[str, Any]) -> str:
    status = _safe_text(
        item.get("status_display"),
        item.get("status_context"),
        item.get("game_state", {}).get("detailed") if isinstance(item.get("game_state"), Mapping) else None,
        item.get("game_state", {}).get("abstract") if isinstance(item.get("game_state"), Mapping) else None,
        default="",
    ).lower()
    settlement = item.get("settlement") if isinstance(item.get("settlement"), Mapping) else {}
    settlement_status = _safe_text(
        settlement.get("status") if isinstance(settlement, Mapping) else None,
        settlement.get("status_label") if isinstance(settlement, Mapping) else None,
        item.get("settlement_status"),
        item.get("settlement_state"),
        item.get("settlement_label"),
        default="",
    ).lower()
    settlement_result = _safe_text(
        settlement.get("result") if isinstance(settlement, Mapping) else None,
        item.get("settlement_result"),
        item.get("result"),
        default="",
    ).lower()
    if any(token in status for token in ("final", "completed", "settled", "resolved", "graded")):
        return "archived"
    if settlement_status in {"final", "completed", "settled", "resolved", "graded"}:
        return "archived"
    if settlement_result in {"won", "lost", "push", "graded", "final", "completed", "settled", "resolved"}:
        return "archived"
    if _is_pregame_status(status):
        return "pregame"
    if _is_live_status(status) and (
        bool(item.get("is_live"))
        or _safe_text(item.get("live_projection"), default="") not in {"", "-"}
        or _safe_text(item.get("live_total"), default="") not in {"", "-"}
    ):
        return "live"
    if bool(item.get("is_live")) and not _is_pregame_status(status):
        return "live"
    return "pregame"


def _recommendation_card(item: Mapping[str, Any]) -> dict[str, Any]:
    card = _copy_mapping(item)
    lane = _recommendation_lane(card)
    line = _number(card.get("line"), card.get("line_open"), card.get("market_data", {}).get("current_line") if isinstance(card.get("market_data"), Mapping) else None)
    edge = _number(card.get("edge"), card.get("adjusted_edge"), card.get("expected_value"), card.get("ev_current"))
    provenance = card.get("provenance") if isinstance(card.get("provenance"), Mapping) else {}
    sport_context = card.get("sport_context") if isinstance(card.get("sport_context"), Mapping) else {}
    trace_path = _safe_text(
        provenance.get("source_path") if isinstance(provenance, Mapping) else None,
        provenance.get("source") if isinstance(provenance, Mapping) else None,
        card.get("source_path"),
        card.get("source"),
        card.get("surface_title"),
        default="",
    )
    if not trace_path:
        trace_path = "/".join(
            part
            for part in (
                _safe_text(card.get("sport_slug"), card.get("sport"), default="sport").lower(),
                _safe_text(card.get("surface_key"), default="board"),
                _safe_text(card.get("market_key"), card.get("market"), default="market").lower(),
                _safe_text(card.get("selection"), card.get("pick"), card.get("name"), card.get("player_name"), default="candidate"),
            )
            if part
        )
    trace = {
        "path": trace_path,
        "source": _safe_text(provenance.get("source") if isinstance(provenance, Mapping) else None, card.get("source"), card.get("surface_title"), default=""),
        "source_id": _safe_text(provenance.get("source_id") if isinstance(provenance, Mapping) else None, card.get("candidate_id"), card.get("recommendation_id"), card.get("prediction_id"), default=""),
        "selected_date": _safe_text(provenance.get("selected_date") if isinstance(provenance, Mapping) else None, card.get("selected_date"), card.get("date"), card.get("context_label"), default=""),
        "surface_key": _safe_text(card.get("surface_key"), default=""),
        "surface_title": _safe_text(card.get("surface_title"), default=""),
        "sport_slug": _safe_text(card.get("sport_slug"), card.get("sport"), default="").lower(),
        "selection": _safe_text(card.get("selection"), card.get("pick"), card.get("name"), card.get("player_name"), default=""),
        "market": _safe_text(card.get("market"), card.get("market_label"), card.get("market_key"), default=""),
        "matchup": _safe_text(sport_context.get("matchup") if isinstance(sport_context, Mapping) else None, card.get("matchup"), default=""),
    }
    trace = {key: value for key, value in trace.items() if value}
    card.update(
        {
            "lane": lane,
            "sport": _safe_text(card.get("sport"), card.get("sport_slug"), default="sport").lower(),
            "team": _safe_text(card.get("team"), card.get("team_name"), default="—"),
            "player": _safe_text(card.get("player_name"), card.get("name"), default="—"),
            "market": _safe_text(card.get("market"), card.get("market_label"), default="—"),
            "line": line,
            "movement": _movement_summary(card),
            "simulated_edge": edge,
            "trace": trace,
            "trace_path": trace.get("path"),
        }
    )
    return card


def _recommendation_sources(payload: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    current = _copy_mapping(payload)
    sources: list[Mapping[str, Any]] = []

    board = current.get("board") if isinstance(current.get("board"), Mapping) else None
    if isinstance(board, Mapping):
        top_overall = board.get("top_overall")
        if isinstance(top_overall, list):
            sources.extend(item for item in top_overall if isinstance(item, Mapping))
        if sources:
            return sources

    direct_recommendations = current.get("recommendations")
    if isinstance(direct_recommendations, list):
        sources.extend(item for item in direct_recommendations if isinstance(item, Mapping))
        if sources:
            return sources

    response = current.get("response") if isinstance(current.get("response"), Mapping) else None
    if isinstance(response, Mapping):
        response_recommendations = response.get("recommendations")
        if isinstance(response_recommendations, list):
            sources.extend(item for item in response_recommendations if isinstance(item, Mapping))

    analysis = current.get("analysis") if isinstance(current.get("analysis"), Mapping) else None
    if isinstance(analysis, Mapping):
        analysis_recommendations = analysis.get("recommendations")
        if isinstance(analysis_recommendations, list):
            sources.extend(item for item in analysis_recommendations if isinstance(item, Mapping))
        top_live_opportunities = analysis.get("top_live_opportunities")
        if isinstance(top_live_opportunities, list):
            sources.extend(item for item in top_live_opportunities if isinstance(item, Mapping))

    top_opportunities = current.get("top_opportunities")
    if isinstance(top_opportunities, list):
        sources.extend(item for item in top_opportunities if isinstance(item, Mapping))

    deduped: list[Mapping[str, Any]] = []
    seen_keys: set[str] = set()
    for item in sources:
        key = "|".join(
            part
            for part in (
                _safe_text(item.get("recommendation_id"), default=""),
                _safe_text(item.get("candidate_id"), default=""),
                _safe_text(item.get("prediction_id"), default=""),
                _safe_text(item.get("name"), item.get("player_name"), item.get("selection"), default=""),
                _safe_text(item.get("market"), item.get("market_label"), default=""),
            )
            if part
        )
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(item)
    return deduped


def build_intelligence_board_contract(response: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = _copy_mapping(response)
    recommendations = _recommendation_sources(payload)
    cards = [_recommendation_card(item) for item in recommendations if isinstance(item, Mapping)]
    lane_counts = {
        "live": sum(1 for card in cards if card.get("lane") == "live"),
        "pregame": sum(1 for card in cards if card.get("lane") == "pregame"),
        "archived": sum(1 for card in cards if card.get("lane") == "archived"),
    }
    active_lanes = [lane for lane in ("live", "pregame") if lane_counts.get(lane)]
    board_summary = {
        "headline": _safe_text(payload.get("headline"), payload.get("summary"), default="The Syndicate board"),
        "recommendation_count": len(cards),
        "live_count": lane_counts["live"],
        "pregame_count": lane_counts["pregame"],
        "archived_count": lane_counts["archived"],
        "active_lanes": active_lanes,
    }
    waterfall = [
        {"step": "source_response", "count": len(recommendations), "label": "Raw response recommendations"},
        {"step": "normalized_cards", "count": len(cards), "label": "Deduped board cards"},
        {"step": "live_lane", "count": lane_counts["live"], "label": "Live recommendations"},
        {"step": "pregame_lane", "count": lane_counts["pregame"], "label": "Pregame recommendations"},
        {"step": "archived_lane", "count": lane_counts["archived"], "label": "Archived recommendations"},
    ]
    return {
        "schema": "intelligence_board_v1",
        "card_fields": ["sport", "team", "player", "market", "line", "projected", "live_projection", "actual", "status_display", "movement", "simulated_edge", "trace_path", "game_pk"],
        "recommendation_count": len(cards),
        "lane_counts": lane_counts,
        "active_lanes": active_lanes,
        "board_summary": board_summary,
        "cards": cards,
        "waterfall": waterfall,
    }


__all__ = ["build_intelligence_board_contract"]