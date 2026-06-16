from __future__ import annotations

from typing import Any
import calendar
import hashlib
import json
import os
import re
import threading
import time

from flask import Blueprint
from flask import jsonify
from flask import request

from router.query_router import QueryRouter as IntelligenceQueryRouter
from pipeline.intelligence_state import queue_intelligence_state_refresh
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


def _refresh_queue_key(shaped_payload: dict[str, Any]) -> str:
    queue_payload = {
        key: shaped_payload.get(key)
        for key in (
            "question",
            "original_question",
            "query_type",
            "sport",
            "sport_slug",
            "mode",
            "selected_date",
            "date",
            "limit",
            "include_props",
            "include_games",
            "timing",
        )
    }
    canonical = json.dumps(queue_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _latest_state_is_fresh(latest_state: dict[str, Any] | None) -> bool:
    if not isinstance(latest_state, dict):
        return False
    latest_updated_at = str(latest_state.get("latestComputedAt") or latest_state.get("last_updated") or "").strip()
    if not latest_updated_at:
        return False
    try:
        computed_at = time.strptime(latest_updated_at, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return False
    computed_epoch = calendar.timegm(computed_at)
    return (time.time() - computed_epoch) <= _REFRESH_QUEUE_DEDUPE_SECONDS


def _build_fast_state_result(shaped_payload: dict[str, Any]) -> dict[str, Any] | None:
    latest_state = read_latest_intelligence_state_response(shaped_payload)
    if not isinstance(latest_state, dict):
        return None

    analysis = latest_state.get("analysis") if isinstance(latest_state.get("analysis"), dict) else latest_state.get("response")
    if not isinstance(analysis, dict):
        analysis = {}

    recommendations = analysis.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        recommendations = latest_state.get("top_opportunities") if isinstance(latest_state.get("top_opportunities"), list) else []
    if recommendations:
        analysis.setdefault("recommendations", [dict(item) for item in recommendations if isinstance(item, dict)])

    by_sport = latest_state.get("by_sport") if isinstance(latest_state.get("by_sport"), dict) else {}
    candidate_pool = latest_state.get("candidate_pool") if isinstance(latest_state.get("candidate_pool"), dict) else {}
    analysis_views = analysis.get("analysis_views") if isinstance(analysis.get("analysis_views"), dict) else {}
    parsed_request = analysis.get("parsed_request") if isinstance(analysis.get("parsed_request"), dict) else {}

    merged_parsed_request = dict(parsed_request)
    for key in (
        "question",
        "query_type",
        "sport",
        "sport_slug",
        "market",
        "candidate_type",
        "selection",
        "matchup",
        "player_name",
        "name",
        "preview_subject",
        "player_subject",
        "selected_date",
        "date",
    ):
        value = shaped_payload.get(key)
        if value not in (None, ""):
            merged_parsed_request[key] = value

    analysis.update(
        {
            "query_type": shaped_payload.get("query_type") or analysis.get("query_type") or analysis.get("intent") or "explanation",
            "parsed_request": merged_parsed_request,
            "analysis_views": analysis_views,
        }
    )

    board_contract_source = dict(latest_state)
    board_contract_source.setdefault("analysis", analysis)
    board_contract_source.setdefault("response", analysis)
    board_contract = build_intelligence_board_contract(board_contract_source)

    question = str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip()
    routing_context = {
        "question": question,
        "query_type": analysis.get("query_type"),
        "mode": shaped_payload.get("mode"),
        "selected_date": shaped_payload.get("selected_date") or shaped_payload.get("date"),
        "preview_subject": shaped_payload.get("preview_subject"),
        "player_subject": shaped_payload.get("player_subject"),
        "sport": shaped_payload.get("sport") or shaped_payload.get("sport_slug"),
        "limit": shaped_payload.get("limit"),
        "include_props": shaped_payload.get("include_props"),
        "include_games": shaped_payload.get("include_games"),
    }
    detected_sports = _detect_sports(question)
    context_awareness = {
        "is_vague": not bool(routing_context.get("sport")) and not bool(detected_sports),
        "confidence": "low" if not bool(routing_context.get("sport")) and not bool(detected_sports) else "medium",
        "detected_sports": detected_sports,
        "multi_sport": len(detected_sports) > 1,
        "assumptions": ["Used the latest intelligence state response and preserved the route metadata."] if latest_state else [],
        "clarifying_questions": [],
        "reasoning": "The response was served from the latest state snapshot, so the API preserved the route and context fields for consistency.",
        "recommendation_count": len(analysis.get("recommendations") or []),
        "reasoning_step_count": len(analysis.get("reasoning_steps") or []),
    }

    return {
        "ok": True,
        "top_opportunities": latest_state.get("top_opportunities") if isinstance(latest_state.get("top_opportunities"), list) else list(analysis.get("recommendations") or []),
        "by_sport": by_sport,
        "analysis": analysis,
        "candidate_pool": candidate_pool,
        "response": analysis,
        "board_contract": board_contract,
        "routing_context": routing_context,
        "context_awareness": context_awareness,
        "served_from": "latest_state",
        "served_from_state_cache": False,
        "state_cache_latest_key": latest_state.get("latestKey") if isinstance(latest_state.get("latestKey"), str) else None,
        "state_cache_latest_computed_at": latest_state.get("latestComputedAt") if isinstance(latest_state.get("latestComputedAt"), str) else None,
    }


def _maybe_queue_exact_refresh(shaped_payload: dict[str, Any]) -> None:
    latest_state = read_latest_intelligence_state_response(shaped_payload)
    if _latest_state_is_fresh(latest_state):
        return

    queue_key = _refresh_queue_key(shaped_payload)
    current_time = time.time()
    with _REFRESH_QUEUE_LOCK:
        last_queued_at = _REFRESH_QUEUE_STATE.get(queue_key)
        if last_queued_at is not None and (current_time - last_queued_at) < _REFRESH_QUEUE_DEDUPE_SECONDS:
            return
        _REFRESH_QUEUE_STATE[queue_key] = current_time
        stale_keys = [key for key, queued_at in _REFRESH_QUEUE_STATE.items() if (current_time - queued_at) >= _REFRESH_QUEUE_DEDUPE_SECONDS]
        for stale_key in stale_keys:
            _REFRESH_QUEUE_STATE.pop(stale_key, None)

    try:
        queue_intelligence_state_refresh(shaped_payload)
    except Exception:
        with _REFRESH_QUEUE_LOCK:
            _REFRESH_QUEUE_STATE.pop(queue_key, None)


def _build_placeholder_response(shaped_payload: dict[str, Any], decision: RouteDecision, *, reason: str) -> dict[str, Any]:
    empty_result: dict[str, Any] = {
        "query_type": decision.intent,
        "parsed_request": {
            "question": str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip(),
        },
        "analysis_views": {},
        "recommendations": [],
        "top_opportunities": [],
        "board_notes": [],
        "reasoning_steps": [],
        "summary": None,
        "pipeline_context": {"routing_context": {"question": str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip()}},
        "structured_response": {"context_awareness": {"reasoning": reason}},
    }
    return build_syndicate_query_response(
        question=str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip(),
        context=_coerce_context(shaped_payload),
        decision=decision,
        result=empty_result,
    )


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
    cached_result = read_latest_intelligence_state_response(pipeline_payload)
    if isinstance(cached_result, dict):
        return build_syndicate_query_response(
            question=str(payload.get("original_question") or payload.get("question") or "").strip(),
            context=_coerce_context(payload),
            decision=decision,
            result=cached_result,
        )

    _maybe_queue_exact_refresh(pipeline_payload)
    result = _build_placeholder_response(payload, decision, reason="queued_refresh")
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
    fast_state_response = _build_fast_state_result(shaped_payload)
    if fast_state_response is not None:
        _maybe_queue_exact_refresh(shaped_payload)
        return _with_cors_headers(jsonify(fast_state_response))

    _maybe_queue_exact_refresh(shaped_payload)
    fast_state_response = _build_fast_state_result(shaped_payload)
    if fast_state_response is not None:
        return _with_cors_headers(jsonify(fast_state_response))

    handler = {
        "handle_bet_analysis": handle_bet_analysis,
        "handle_matchup_analysis": handle_matchup_analysis,
        "handle_market_summary": handle_market_summary,
    }[decision.handler_name]
    response = handler(shaped_payload)
    return _with_cors_headers(jsonify(response))