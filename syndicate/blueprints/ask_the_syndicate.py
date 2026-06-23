from __future__ import annotations

from typing import Any
import hashlib
import json
import os
import re
import threading

from flask import Blueprint
from flask import jsonify
from flask import request

from router.query_router import QueryRouter as IntelligenceQueryRouter
from pipeline.intelligence_state import read_latest_intelligence_board_snapshot_response
from pipeline.intelligence_state import read_latest_intelligence_state_response
from syndicate.blueprints.ask_the_syndicate_adapter import build_syndicate_query_response
from syndicate.blueprints.ask_the_syndicate_router import SyndicateQueryRouter
from syndicate.blueprints.ask_the_syndicate_router import RouteDecision
from syndicate.features.intelligence_board import build_intelligence_board_contract


ask_the_syndicate_bp = Blueprint("ask_the_syndicate", __name__)
_QUERY_ROUTER = SyndicateQueryRouter()
_INTELLIGENCE_ROUTER = IntelligenceQueryRouter()
_REFRESH_QUEUE_LOCK = threading.Lock()
_REFRESH_QUEUE_DEDUPE_SECONDS = 15.0
_REFRESH_QUEUE_STATE: dict[str, float] = {}

_SPORT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "mlb",
        (
            "baseball",
            "mlb",
            "strikeout",
            "strikeouts",
            "k's",
            "k's?",
            "home run",
            "home runs",
            "hr",
            "hits",
            "hit prop",
            "rbi",
            "total bases",
            "pitcher",
            "bullpen",
            "innings",
            "ohtani",
            "cubs",
            "yankees",
            "dodgers",
        ),
    ),
    (
        "nba",
        (
            "points",
            "rebounds",
            "assists",
            "pra",
            "basketball",
            "nba",
            "wnba",
        ),
    ),
    (
        "nhl",
        (
            "shots",
            "saves",
            "goals",
            "assists",
            "hockey",
            "nhl",
        ),
    ),
    (
        "nfl",
        (
            "passing",
            "rushing",
            "receiving",
            "touchdowns",
            "tds",
            "football",
            "nfl",
        ),
    ),
)


def _coerce_context(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context")
    return dict(context) if isinstance(context, dict) else {}


def _infer_sport(question: str, context: dict[str, Any]) -> str | None:
    explicit = str(context.get("sport_slug") or context.get("sport") or payload_value(context, "sport") or "").strip().lower()
    if explicit:
        return explicit
    normalized_question = f" {str(question or '').lower()} "
    for sport, keywords in _SPORT_HINTS:
        for keyword in keywords:
            pattern = rf"\b{re.escape(keyword.lower())}\b"
            if re.search(pattern, normalized_question):
                return sport
    return None


def _detect_sports(question: str) -> list[str]:
    normalized_question = str(question or "").strip().lower()
    detected: list[str] = []
    for sport, keywords in _SPORT_HINTS:
        if any(re.search(rf"\b{re.escape(keyword.lower())}\b", normalized_question) for keyword in keywords):
            if sport not in detected:
                detected.append(sport)
    return detected


def payload_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    return value


def _with_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, Origin, X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Vary"] = "Origin"
    return response


def _smart_route_payload(payload: dict[str, Any]) -> dict[str, Any]:
    intelligence_payload = _INTELLIGENCE_ROUTER.route_payload(payload)
    question = str(intelligence_payload.get("question") or payload.get("question") or "").strip()
    context = _coerce_context(payload)
    merged = dict(intelligence_payload)
    merged.update({key: value for key, value in context.items() if value is not None})
    merged["question"] = question
    merged["original_question"] = str(payload.get("question") or "").strip()
    sport = _infer_sport(question, merged)
    if sport:
        merged["sport"] = sport
        merged["sport_slug"] = sport
    query_type = str(merged.get("query_type") or "").strip()
    if query_type in {"game_preview", "player_analysis"}:
        merged.setdefault("mode", "pregame")
        merged.setdefault("include_games", True)
        merged.setdefault("include_props", True)
    elif query_type == "comparison":
        merged.setdefault("mode", "comparison")
        merged.setdefault("include_games", True)
        merged.setdefault("include_props", True)
    elif query_type == "live_analysis":
        merged.setdefault("mode", "live")
        merged.setdefault("include_games", True)
    return merged


def _build_artifact_response(shaped_payload: dict[str, Any], decision: RouteDecision) -> dict[str, Any] | None:
    return None


def _empty_ask_result(shaped_payload: dict[str, Any], decision: RouteDecision, *, reason: str) -> dict[str, Any]:
    question = str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip()
    return {
        "query_type": decision.intent,
        "summary": "No saved intelligence snapshot is available yet.",
        "parsed_request": {
            "question": question,
        },
        "analysis_views": {},
        "recommendations": [],
        "top_opportunities": [],
        "board_notes": ["Ask is serving the latest intelligence snapshot only."],
        "reasoning_steps": [],
        "pipeline_context": {"routing_context": {"question": question}},
        "structured_response": {"context_awareness": {"reasoning": reason}},
        "analysis_brief": {
            "kind": "bundle",
            "title": "Snapshot unavailable",
            "summary": "No saved intelligence snapshot is available yet.",
        },
        "supporting_evidence": {
            "kind": "bundle",
            "title": "Snapshot unavailable",
            "summary": "The Ask endpoint only serves persisted intelligence snapshots.",
        },
    }


def _hydrate_intelligence_snapshot_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(snapshot or {})
    nested = current.get("response") if isinstance(current.get("response"), dict) else {}
    nested = dict(nested or {})

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        nested_top = nested.get("top_opportunities") if isinstance(nested.get("top_opportunities"), list) else []
        nested_recommendations = nested.get("recommendations") if isinstance(nested.get("recommendations"), list) else []
        if nested_top:
            current["top_opportunities"] = [dict(item) for item in nested_top if isinstance(item, dict)]
        elif nested_recommendations:
            current["top_opportunities"] = [dict(item) for item in nested_recommendations if isinstance(item, dict)]

    if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
        nested_recommendations = nested.get("recommendations") if isinstance(nested.get("recommendations"), list) else []
        if nested_recommendations:
            current["recommendations"] = [dict(item) for item in nested_recommendations if isinstance(item, dict)]

    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
            analysis_recommendations = analysis.get("recommendations") if isinstance(analysis.get("recommendations"), list) else []
            normalized_recommendations = [dict(item) for item in analysis_recommendations if isinstance(item, dict)]
            if normalized_recommendations:
                current["top_opportunities"] = normalized_recommendations
                if isinstance(nested, dict) and (not isinstance(nested.get("top_opportunities"), list) or not nested.get("top_opportunities")):
                    nested["top_opportunities"] = list(normalized_recommendations)
        if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
            analysis_recommendations = analysis.get("recommendations") if isinstance(analysis.get("recommendations"), list) else []
            if analysis_recommendations:
                current["recommendations"] = [dict(item) for item in analysis_recommendations if isinstance(item, dict)]

    return current


def read_latest_intelligence_state(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    board_snapshot = read_latest_intelligence_board_snapshot_response(payload or {}, force_refresh=False)
    if isinstance(board_snapshot, dict):
        return _hydrate_intelligence_snapshot_payload(board_snapshot)

    snapshot = read_latest_intelligence_state_response(payload or {}, force_refresh=False)
    if isinstance(snapshot, dict):
        return _hydrate_intelligence_snapshot_payload(snapshot)
    return {}


def _base_pipeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or "").strip()
    context = _coerce_context(payload)
    routed_payload = dict(context)
    routed_payload["question"] = question

    for key in ("selected_date", "date", "sport", "mode", "limit", "timing", "include_props", "include_games", "force_refresh"):
        if key in payload and payload.get(key) is not None:
            routed_payload[key] = payload.get(key)

    if context:
        routed_payload["context"] = context

    return routed_payload


def _query_cache_key(question: str, payload: dict[str, Any], decision: RouteDecision) -> str:
    cache_payload = _apply_intent_hints(_base_pipeline_payload(payload), decision.intent)
    cache_payload["question"] = question
    cache_payload["intent"] = decision.intent
    canonical = json.dumps(cache_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_cached_response(cache_key: str) -> dict[str, Any] | None:
    return None


def _store_cached_response(cache_key: str, response: dict[str, Any]) -> None:
    return None


def _apply_intent_hints(pipeline_payload: dict[str, Any], intent: str) -> dict[str, Any]:
    enriched_payload = dict(pipeline_payload)
    if intent == "bet_analysis":
        enriched_payload.setdefault("mode", "pregame")
        enriched_payload.setdefault("include_props", True)
        enriched_payload.setdefault("include_games", True)
    elif intent in {"matchup_analysis", "comparison"}:
        enriched_payload.setdefault("mode", "comparison")
        enriched_payload.setdefault("include_games", True)
        enriched_payload.setdefault("include_props", True)
    elif intent == "market_summary":
        enriched_payload.setdefault("mode", "pregame")
    return enriched_payload


def _build_route_payload(payload: dict[str, Any], decision: RouteDecision) -> dict[str, Any]:
    pipeline_payload = _apply_intent_hints(payload, decision.intent)
    cached_result = read_latest_intelligence_state(pipeline_payload)
    result = cached_result if isinstance(cached_result, dict) and cached_result else _empty_ask_result(payload, decision, reason="snapshot_missing")
    return build_syndicate_query_response(
        question=str(payload.get("original_question") or payload.get("question") or "").strip(),
        context=_coerce_context(payload),
        decision=decision,
        result=result,
    )


def handle_bet_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    decision = _QUERY_ROUTER.route(str(payload.get("question") or ""))
    return _build_route_payload(payload, decision)


def handle_matchup_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    decision = _QUERY_ROUTER.route(str(payload.get("question") or ""))
    return _build_route_payload(payload, decision)


def handle_market_summary(payload: dict[str, Any]) -> dict[str, Any]:
    decision = _QUERY_ROUTER.route(str(payload.get("question") or ""))
    return _build_route_payload(payload, decision)


@ask_the_syndicate_bp.route("/api/syndicate/query", methods=["POST", "OPTIONS"])
def ask_the_syndicate_query_api():
    if request.method == "OPTIONS":
        return _with_cors_headers(jsonify({"ok": True}))

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _with_cors_headers(jsonify({"ok": False, "error": "Request body must be a JSON object."})), 400

    question = str(payload.get("question") or "").strip()
    if not question:
        return _with_cors_headers(jsonify({"ok": False, "error": "question is required."})), 400

    shaped_payload = _smart_route_payload(payload)
    decision = _QUERY_ROUTER.route(str(shaped_payload.get("question") or question))

    cache_key = _query_cache_key(question, payload, decision)
    _read_cached_response(cache_key)

    artifact_response = _build_artifact_response(shaped_payload, decision)
    if isinstance(artifact_response, dict):
        return _with_cors_headers(jsonify(artifact_response))

    snapshot = read_latest_intelligence_state(shaped_payload)
    result = snapshot if isinstance(snapshot, dict) and snapshot else _empty_ask_result(shaped_payload, decision, reason="snapshot_missing")
    response = build_syndicate_query_response(
        question=str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip(),
        context=_coerce_context(shaped_payload),
        decision=decision,
        result=result,
    )
    return _with_cors_headers(jsonify(response))