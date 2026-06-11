from __future__ import annotations

from typing import Any
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict

from flask import Blueprint
from flask import jsonify
from flask import request

from router.query_router import QueryRouter as IntelligenceQueryRouter
from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from pipeline.intelligence_state import queue_intelligence_state_refresh
from pipeline.intelligence_state import read_latest_intelligence_state_response
from syndicate.blueprints.ask_the_syndicate_adapter import build_syndicate_query_response
from syndicate.blueprints.ask_the_syndicate_router import SyndicateQueryRouter
from syndicate.blueprints.ask_the_syndicate_router import RouteDecision
from syndicate.features.intelligence import run_intelligence_query


ask_the_syndicate_bp = Blueprint("ask_the_syndicate", __name__)
_QUERY_ROUTER = SyndicateQueryRouter()
_INTELLIGENCE_ROUTER = IntelligenceQueryRouter()
_QUERY_CACHE_LOCK = threading.Lock()
_QUERY_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_QUERY_CACHE_TTL_SECONDS = max(30, int(os.environ.get("SYNDICATE_ASK_QUERY_CACHE_TTL_SECONDS", "180")))
_QUERY_CACHE_MAX_ENTRIES = max(8, int(os.environ.get("SYNDICATE_ASK_QUERY_CACHE_MAX_ENTRIES", "64")))

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


def payload_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    return value


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
    elif query_type == "live_analysis":
        merged.setdefault("mode", "live")
        merged.setdefault("include_games", True)
    return merged


def _build_artifact_response(shaped_payload: dict[str, Any], decision: RouteDecision) -> dict[str, Any] | None:
    question = str(shaped_payload.get("question") or "").strip()
    try:
        result = run_intelligence_query(
            question,
            selected_date=str(shaped_payload.get("selected_date") or shaped_payload.get("date") or "").strip() or None,
            mode=str(shaped_payload.get("mode") or "").strip() or None,
            sport=str(shaped_payload.get("sport") or shaped_payload.get("sport_slug") or "").strip() or None,
            limit=shaped_payload.get("limit"),
            timing=str(shaped_payload.get("timing") or "").strip() or None,
            include_props=shaped_payload.get("include_props"),
            include_games=shaped_payload.get("include_games"),
            force_refresh=bool(shaped_payload.get("force_refresh")),
        )
    except Exception:
        return None

    return build_syndicate_query_response(
        question=str(shaped_payload.get("original_question") or question).strip(),
        context=_coerce_context(shaped_payload),
        decision=decision,
        result=result,
    )


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

    return {
        "ok": True,
        "top_opportunities": latest_state.get("top_opportunities") if isinstance(latest_state.get("top_opportunities"), list) else list(analysis.get("recommendations") or []),
        "by_sport": by_sport,
        "analysis": analysis,
        "candidate_pool": candidate_pool,
        "response": analysis,
        "served_from": "state_cache",
        "served_from_state_cache": True,
        "state_cache_latest_key": latest_state.get("latestKey") if isinstance(latest_state.get("latestKey"), str) else None,
        "state_cache_latest_computed_at": latest_state.get("latestComputedAt") if isinstance(latest_state.get("latestComputedAt"), str) else None,
    }


def _maybe_queue_exact_refresh(shaped_payload: dict[str, Any]) -> None:
    try:
        queue_intelligence_state_refresh(shaped_payload)
    except Exception:
        pass


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
    now = time.time()
    with _QUERY_CACHE_LOCK:
        cached = _QUERY_CACHE.get(cache_key)
        if cached is None:
          return None
        created_at, response = cached
        if now - created_at > _QUERY_CACHE_TTL_SECONDS:
            _QUERY_CACHE.pop(cache_key, None)
            return None
        _QUERY_CACHE.move_to_end(cache_key)
        cached_response = dict(response)
        cached_response["cached"] = True
        cached_response["cache_age_seconds"] = round(now - created_at, 3)
        return cached_response


def _store_cached_response(cache_key: str, response: dict[str, Any]) -> None:
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE[cache_key] = (time.time(), dict(response))
        _QUERY_CACHE.move_to_end(cache_key)
        while len(_QUERY_CACHE) > _QUERY_CACHE_MAX_ENTRIES:
            _QUERY_CACHE.popitem(last=False)


def _apply_intent_hints(pipeline_payload: dict[str, Any], intent: str) -> dict[str, Any]:
    enriched_payload = dict(pipeline_payload)
    if intent == "bet_analysis":
        enriched_payload.setdefault("mode", "pregame")
        enriched_payload.setdefault("include_props", True)
        enriched_payload.setdefault("include_games", True)
    elif intent == "matchup_analysis":
        enriched_payload.setdefault("mode", "comparison")
        enriched_payload.setdefault("include_games", True)
    elif intent == "market_summary":
        enriched_payload.setdefault("mode", "pregame")
    return enriched_payload


def _build_route_payload(payload: dict[str, Any], decision: RouteDecision) -> dict[str, Any]:
    pipeline_payload = _apply_intent_hints(payload, decision.intent)
    result = run_routed_intelligence_pipeline(pipeline_payload)
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


@ask_the_syndicate_bp.post("/api/syndicate/query")
def ask_the_syndicate_query_api():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Request body must be a JSON object."}), 400

    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "question is required."}), 400

    shaped_payload = _smart_route_payload(payload)
    decision = _QUERY_ROUTER.route(str(shaped_payload.get("question") or question))

    cache_key = _query_cache_key(question, payload, decision)
    cached_response = _read_cached_response(cache_key)
    if cached_response is not None:
        return jsonify(cached_response)

    artifact_response = _build_artifact_response(shaped_payload, decision)
    if artifact_response is not None:
        _store_cached_response(cache_key, artifact_response)
        _maybe_queue_exact_refresh(shaped_payload)
        return jsonify(artifact_response)

    fast_state_response = _build_fast_state_result(shaped_payload)
    if fast_state_response is not None:
        _store_cached_response(cache_key, fast_state_response)
        _maybe_queue_exact_refresh(shaped_payload)
        return jsonify(fast_state_response)

    handler = {
        "handle_bet_analysis": handle_bet_analysis,
        "handle_matchup_analysis": handle_matchup_analysis,
        "handle_market_summary": handle_market_summary,
    }[decision.handler_name]
    response = handler(shaped_payload)
    _store_cached_response(cache_key, response)
    return jsonify(response)