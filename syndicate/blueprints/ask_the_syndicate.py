from __future__ import annotations

from typing import Any
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
from pipeline.intelligence_state import read_latest_intelligence_board_snapshot_response
from pipeline.intelligence_state import read_latest_intelligence_state_response
from syndicate.blueprints.ask_the_syndicate_adapter import build_syndicate_query_response
from syndicate.blueprints.ask_the_syndicate_data import collect_focused_evidence
from syndicate.blueprints.ask_the_syndicate_engine import generate_briefing
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
    # Plan item 1F ("one contract, not one pipeline per surface"): this was
    # a third parallel read cascade (board_snapshot -> worker state), with
    # its own precedence order, separate from _cached_intelligence_response_with_source
    # in syndicate/blueprints/intelligence.py. Try the canonical board state
    # first -- same as the Board's own read path -- before falling through
    # to this function's existing order unchanged. Behind
    # SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE (default off), so this is
    # a no-op today: _load_canonical_board_response returns None immediately
    # when the flag (and its shadow-compare sibling) are both off.
    try:
        from syndicate.blueprints.intelligence import _load_canonical_board_response

        canonical_response, _canonical_source = _load_canonical_board_response(payload or {})
    except Exception:
        canonical_response = None
    if isinstance(canonical_response, dict) and canonical_response:
        return _hydrate_intelligence_snapshot_payload(canonical_response)

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


_RESPONSE_CACHE_LOCK = threading.Lock()
_RESPONSE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_RESPONSE_CACHE_TTL_SECONDS = float(os.environ.get("SYNDICATE_ASK_CACHE_TTL_SECONDS", "600"))
_RESPONSE_CACHE_MAX_ENTRIES = 128


def _read_cached_response(cache_key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _RESPONSE_CACHE_LOCK:
        entry = _RESPONSE_CACHE.get(cache_key)
        if entry is None:
            return None
        stored_at, response = entry
        if now - stored_at > _RESPONSE_CACHE_TTL_SECONDS:
            _RESPONSE_CACHE.pop(cache_key, None)
            return None
        return response


def _store_cached_response(cache_key: str, response: dict[str, Any]) -> None:
    now = time.monotonic()
    with _RESPONSE_CACHE_LOCK:
        if len(_RESPONSE_CACHE) >= _RESPONSE_CACHE_MAX_ENTRIES:
            oldest_key = min(_RESPONSE_CACHE, key=lambda key: _RESPONSE_CACHE[key][0])
            _RESPONSE_CACHE.pop(oldest_key, None)
        _RESPONSE_CACHE[cache_key] = (now, response)


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


def _apply_briefing_to_response(response: dict[str, Any], briefing_payload: dict[str, Any]) -> None:
    briefing = briefing_payload.get("briefing")
    if not isinstance(briefing, dict):
        return
    response["briefing"] = briefing
    response["answer_source"] = "llm"
    response["llm"] = {
        "model": briefing_payload.get("model"),
        "usage": briefing_payload.get("usage"),
    }

    # Surface the synthesized narrative through the fields the UI already renders.
    schema = response.get("schema")
    if not isinstance(schema, dict):
        return
    verdict = str(briefing.get("verdict") or briefing.get("headline") or "").strip()
    narrative = str(briefing.get("narrative") or "").strip()
    risks = [str(item) for item in briefing.get("risks") or [] if str(item).strip()]

    schema_type = schema.get("schema_type")
    if schema_type == "bet_analysis":
        if verdict:
            schema["recommendation"] = verdict
        explanation = schema.get("explanation")
        if isinstance(explanation, dict) and narrative:
            explanation["summary"] = narrative
    elif schema_type == "matchup_analysis":
        simulation_summary = schema.get("simulation_summary")
        if isinstance(simulation_summary, dict) and narrative:
            simulation_summary["summary"] = narrative
        market_insight = schema.get("market_insight")
        if isinstance(market_insight, dict) and verdict:
            market_insight["summary"] = verdict
        if risks:
            schema["hidden_factors"] = [{"factor": risk} for risk in risks]
    elif schema_type == "market_summary":
        rationale_summary = schema.get("rationale_summary")
        if isinstance(rationale_summary, dict) and narrative:
            rationale_summary["summary"] = narrative


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
    cached_response = _read_cached_response(cache_key)
    if isinstance(cached_response, dict):
        return _with_cors_headers(jsonify(cached_response))

    artifact_response = _build_artifact_response(shaped_payload, decision)
    if isinstance(artifact_response, dict):
        return _with_cors_headers(jsonify(artifact_response))

    snapshot = read_latest_intelligence_state(shaped_payload)
    has_snapshot = isinstance(snapshot, dict) and bool(snapshot)
    result = snapshot if has_snapshot else _empty_ask_result(shaped_payload, decision, reason="snapshot_missing")
    response = build_syndicate_query_response(
        question=str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip(),
        context=_coerce_context(shaped_payload),
        decision=decision,
        result=result,
    )

    response["answer_source"] = "snapshot"

    # Question-specific sim evidence (tables/charts) is deterministic and
    # renders even when the LLM path is unavailable.
    request_context = dict(shaped_payload)
    request_context.update(_coerce_context(shaped_payload))
    focused_evidence = collect_focused_evidence(question, request_context)
    if isinstance(focused_evidence, dict):
        response["visuals"] = {
            "tables": focused_evidence.get("tables") or [],
            "charts": focused_evidence.get("charts") or [],
            "as_of": focused_evidence.get("as_of"),
            "sport": focused_evidence.get("sport"),
        }

    if has_snapshot:
        briefing_payload = generate_briefing(
            question=question,
            context=_coerce_context(shaped_payload),
            intent=decision.intent,
            snapshot=result,
            focused_evidence=focused_evidence,
        )
        if isinstance(briefing_payload, dict):
            _apply_briefing_to_response(response, briefing_payload)

    # Only LLM answers are worth caching -- snapshot shaping is cheap, and
    # caching it would serve stale boards for no cost savings.
    if response.get("answer_source") == "llm":
        _store_cached_response(cache_key, response)
    return _with_cors_headers(jsonify(response))