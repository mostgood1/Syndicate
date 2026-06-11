from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from pipeline.intelligence_state import get_intelligence_state_response
from pipeline.intelligence_state import read_latest_intelligence_state_response
from pipeline.intelligence_state import queue_intelligence_state_refresh
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.intelligence import _market_focus_labels
from syndicate.features.intelligence import _parlay_request_summary
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import load_latest_refresh_status


intelligence_bp = Blueprint("syndicate_intelligence", __name__)

DEFAULT_QUESTION = "top edges today"
_QUERY_RESPONSE_VERSION_PATH = Path(__file__).resolve().parents[2] / "reports" / "intelligence" / "query_response_version.json"
_QUERY_RESPONSE_CACHE_PATH = Path(__file__).resolve().parents[2] / "reports" / "intelligence" / "query_response_cache.json"
_QUERY_RESPONSE_VERSION_LOCK = threading.Lock()
_QUERY_RESPONSE_VERSION_STATE: dict[str, object] | None = None

# ✅ GLOBAL CACHE
LAST_RESULT = {
    "recommendations": [],
    "portfolio": {},
    "parlays": [],
}


def _server_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _response_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_response_version_state() -> dict[str, object]:
    global _QUERY_RESPONSE_VERSION_STATE
    if _QUERY_RESPONSE_VERSION_STATE is not None:
        return dict(_QUERY_RESPONSE_VERSION_STATE)
    try:
        if _QUERY_RESPONSE_VERSION_PATH.exists():
            payload = json.loads(_QUERY_RESPONSE_VERSION_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                _QUERY_RESPONSE_VERSION_STATE = {
                    "version": int(payload.get("version") or 0),
                    "hash": str(payload.get("hash") or ""),
                }
            else:
                _QUERY_RESPONSE_VERSION_STATE = {"version": 0, "hash": ""}
        else:
            _QUERY_RESPONSE_VERSION_STATE = {"version": 0, "hash": ""}
    except Exception:
        _QUERY_RESPONSE_VERSION_STATE = {"version": 0, "hash": ""}
    return dict(_QUERY_RESPONSE_VERSION_STATE)


def _store_response_version_state(state: dict[str, object]) -> None:
    global _QUERY_RESPONSE_VERSION_STATE
    _QUERY_RESPONSE_VERSION_STATE = {"version": int(state.get("version") or 0), "hash": str(state.get("hash") or "")}
    try:
        _QUERY_RESPONSE_VERSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        _QUERY_RESPONSE_VERSION_PATH.write_text(json.dumps(_QUERY_RESPONSE_VERSION_STATE, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _versioned_query_response(response_payload: dict[str, object]) -> dict[str, object]:
    payload_for_hash = dict(response_payload)
    payload_hash = _response_hash(payload_for_hash)
    with _QUERY_RESPONSE_VERSION_LOCK:
        state = _load_response_version_state()
        version = int(state.get("version") or 0)
        if payload_hash != str(state.get("hash") or ""):
            version += 1
            _store_response_version_state({"version": version, "hash": payload_hash})
        else:
            version = int(state.get("version") or version)
    return {
        "version": version,
        "timestamp": _server_timestamp(),
        "response": response_payload,
    }


def _load_response_cache_state() -> dict[str, object] | None:
    try:
        if not _QUERY_RESPONSE_CACHE_PATH.exists():
            return None
        payload = json.loads(_QUERY_RESPONSE_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            return payload
    except Exception:
        return None
    return None


def _unwrap_response_payload(payload: dict[str, object] | None) -> dict[str, object]:
    current = dict(payload or {})
    while isinstance(current.get("response"), dict) and (
        "version" in current or "timestamp" in current
    ):
        current = dict(current.get("response") or {})
    return current


def _board_headline_for_question(question: str, response_payload: dict[str, object]) -> str | None:
    headline = str(response_payload.get("headline") or "").strip()
    if headline:
        return headline

    preferences: dict[str, object] = {}
    try:
        preferences = _query_preferences(question)
    except Exception:
        preferences = {}

    intent = str(preferences.get("intent") or response_payload.get("preferences", {}).get("intent") or "").strip().lower()
    if intent == "parlay":
        return "The Syndicate parlay builder"
    if intent == "live_bets":
        return "The Syndicate live board brief"
    if intent == "pregame_bets":
        return "The Syndicate pregame board brief"

    requested_markets = preferences.get("requested_markets") if isinstance(preferences.get("requested_markets"), list) else []
    if requested_markets:
        first_market = str(requested_markets[0] or "").strip().lower()
        if first_market:
            return f"The Syndicate {first_market} board"

    requested_subjects = preferences.get("requested_subjects") if isinstance(preferences.get("requested_subjects"), list) else []
    if bool(preferences.get("comparison_requested")) and len(requested_subjects) >= 2:
        first_subject = " ".join(part.capitalize() for part in str(requested_subjects[0]).split())
        second_subject = " ".join(part.capitalize() for part in str(requested_subjects[1]).split())
        if first_subject and second_subject:
            return f"The Syndicate comparison: {first_subject} vs {second_subject}"

    return "The Syndicate brief"


def _parsed_request_for_question(question: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        preferences = dict(_query_preferences(
            question,
            mode=payload.get("mode"),
            sport=payload.get("sport"),
            limit=payload.get("limit"),
            timing=payload.get("timing"),
            include_props=payload.get("include_props"),
            include_games=payload.get("include_games"),
        ))
        parsed_request = dict(_parlay_request_summary(preferences))
    except Exception:
        parsed_request = {}
    if question and not parsed_request.get("question"):
        parsed_request["question"] = question
    return parsed_request


def _is_board_response(payload: dict[str, object] | None) -> bool:
    current = dict(payload or {})
    if not current:
        return False
    if any(key in current for key in ("top_opportunities", "by_sport", "portfolio", "parlays")):
        return True
    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict) and any(key in analysis for key in ("recommendations", "picks", "top_live_opportunities", "parlays", "portfolio")):
        return True
    return False


def _cached_intelligence_response(payload: dict[str, object]) -> dict[str, object] | None:
    cached_response = read_latest_intelligence_state_response(payload)
    if _is_board_response(cached_response):
        return dict(cached_response or {})
    cached_response = _load_response_cache_state()
    if _is_board_response(cached_response):
        return dict(cached_response or {})
    return None


def _store_response_cache_state(state: dict[str, object]) -> None:
    try:
        _QUERY_RESPONSE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _QUERY_RESPONSE_CACHE_PATH.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _number_value(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _normalize_user_profile(payload: dict[str, object]) -> dict[str, object] | None:
    raw_profile = payload.get("user_profile")
    if not isinstance(raw_profile, dict):
        return None
    bankroll = _number_value(raw_profile.get("bankroll"))
    if bankroll is not None and bankroll <= 0.0:
        bankroll = None
    risk_tolerance = str(raw_profile.get("risk_tolerance") or "medium").strip().lower()
    if risk_tolerance not in {"low", "medium", "high"}:
        risk_tolerance = "medium"
    preferred_sports = []
    for sport in raw_profile.get("preferred_sports") or []:
        sport_key = str(sport).strip().lower()
        if sport_key:
            preferred_sports.append(sport_key)
    return {
        "bankroll": bankroll,
        "risk_tolerance": risk_tolerance,
        "preferred_sports": sorted(set(preferred_sports)),
    }


def _risk_multiplier(risk_tolerance: str) -> float:
    return {
        "low": 0.8,
        "medium": 1.0,
        "high": 1.2,
    }.get(risk_tolerance, 1.0)


def _candidate_sport_key(candidate: dict[str, object]) -> str:
    return str(candidate.get("sport") or candidate.get("sport_slug") or "unknown").strip().lower() or "unknown"


def _matches_preferred_sports(candidate: dict[str, object], preferred_sports: list[str]) -> bool:
    if not preferred_sports:
        return True
    return _candidate_sport_key(candidate) in set(preferred_sports)


def _adjust_pick_for_profile(candidate: dict[str, object], user_profile: dict[str, object]) -> dict[str, object]:
    adjusted = dict(candidate)
    bet_size = _number_value(adjusted.get("recommended_bet_size"))
    if bet_size is not None:
        bet_size *= _risk_multiplier(str(user_profile.get("risk_tolerance") or "medium"))
        bankroll = _number_value(user_profile.get("bankroll"))
        if bankroll is not None:
            bet_size *= bankroll
        adjusted["recommended_bet_size"] = round(bet_size, 4)
    return adjusted


def _adjust_portfolio_for_profile(portfolio: dict[str, object], user_profile: dict[str, object]) -> dict[str, object]:
    adjusted = dict(portfolio)
    total_exposure = _number_value(adjusted.get("total_exposure"))
    if total_exposure is not None:
        multiplier = _risk_multiplier(str(user_profile.get("risk_tolerance") or "medium"))
        bankroll = _number_value(user_profile.get("bankroll"))
        if bankroll is not None:
            total_exposure *= bankroll
        total_exposure *= multiplier
        adjusted["total_exposure"] = round(total_exposure, 4)
    adjusted["engine_risk_level"] = adjusted.get("risk_level")
    adjusted["risk_level"] = str(user_profile.get("risk_tolerance") or adjusted.get("risk_level") or "medium").strip().lower() or "medium"
    if user_profile.get("bankroll") is not None:
        adjusted["bankroll"] = _number_value(user_profile.get("bankroll"))
    return adjusted


def _filter_parlay_for_profile(parlay: dict[str, object], preferred_sports: list[str]) -> bool:
    if not preferred_sports:
        return True
    legs = parlay.get("legs") if isinstance(parlay.get("legs"), list) else []
    if not legs:
        return _matches_preferred_sports(parlay, preferred_sports)
    preferred = set(preferred_sports)
    return all(_candidate_sport_key(leg) in preferred for leg in legs if isinstance(leg, dict))


def _apply_user_profile_to_response(response_payload: dict[str, object], user_profile: dict[str, object] | None) -> dict[str, object]:
    if not user_profile:
        return response_payload

    preferred_sports = list(user_profile.get("preferred_sports") or [])

    top_opportunities = response_payload.get("top_opportunities") if isinstance(response_payload.get("top_opportunities"), list) else []
    if preferred_sports:
        response_payload["top_opportunities"] = [
            dict(item)
            for item in top_opportunities
            if isinstance(item, dict) and _matches_preferred_sports(item, preferred_sports)
        ]

        by_sport = response_payload.get("by_sport") if isinstance(response_payload.get("by_sport"), dict) else {}
        response_payload["by_sport"] = {
            str(key): [dict(item) for item in items if isinstance(item, dict) and _matches_preferred_sports(item, preferred_sports)]
            for key, items in by_sport.items()
            if str(key).strip().lower() in set(preferred_sports)
        }

    analysis = response_payload.get("analysis") if isinstance(response_payload.get("analysis"), dict) else None
    if analysis is None:
        return response_payload

    for key in ("recommendations", "picks", "top_live_opportunities"):
        items = analysis.get(key)
        if not isinstance(items, list):
            continue
        processed_items: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if preferred_sports and not _matches_preferred_sports(item, preferred_sports):
                continue
            if key in {"recommendations", "picks"}:
                item = _adjust_pick_for_profile(item, user_profile)
            processed_items.append(dict(item))
        analysis[key] = processed_items

    parlay_items = analysis.get("parlays")
    if isinstance(parlay_items, list):
        analysis["parlays"] = [
            dict(item)
            for item in parlay_items
            if isinstance(item, dict) and _filter_parlay_for_profile(item, preferred_sports)
        ]

    portfolio = analysis.get("portfolio") if isinstance(analysis.get("portfolio"), dict) else None
    if portfolio is not None:
        analysis["portfolio"] = _adjust_portfolio_for_profile(portfolio, user_profile)

    response_payload["analysis"] = analysis
    if "response" in response_payload:
        response_payload["response"] = analysis
    return response_payload


def _intelligence_page_payload(selected_date: str) -> dict[str, object]:
    return {
        "question": DEFAULT_QUESTION,
        "date": selected_date,
        "mode": "live",
        "sport": "all",
        "timing": "",
        "limit": 5,
        "include_props": True,
        "include_games": True,
        "force_refresh": True,
    }


@intelligence_bp.get("/intelligence")
def intelligence_home():
    payload = _intelligence_page_payload(central_today_iso())
    initial_response: dict[str, Any] = {}
    try:
        cached_response = _cached_intelligence_response(payload)
        if cached_response is not None:
            initial_response = dict(cached_response)
        queue_intelligence_state_refresh(dict(payload))
    except Exception:
        initial_response = {}
    return render_template("intelligence.html", initial_intelligence_response=initial_response)


@intelligence_bp.post("/api/intelligence/query")
def intelligence_query_api():
    global LAST_RESULT
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "question is required."}), 400
    user_profile = _normalize_user_profile(payload)
    want_refresh = bool(payload.get("force_refresh")) or bool(payload.get("background"))

    response_payload: dict[str, object] | None = None
    try:
        selected_date = str(payload.get("date") or payload.get("selected_date") or "").strip() or None
        cache_payload = dict(payload)
        if selected_date:
            cache_payload["date"] = selected_date
        cached_response = _cached_intelligence_response(cache_payload)
        if question == DEFAULT_QUESTION and cached_response is not None:
            response_payload = dict(cached_response)
            if want_refresh:
                queue_intelligence_state_refresh(dict(payload))
        else:
            board_result = run_intelligence_query(
                question,
                selected_date=selected_date,
                mode=str(payload.get("mode") or "").strip() or None,
                sport=str(payload.get("sport") or "").strip() or None,
                limit=payload.get("limit"),
                timing=str(payload.get("timing") or "").strip() or None,
                include_props=payload.get("include_props"),
                include_games=payload.get("include_games"),
                force_refresh=bool(payload.get("force_refresh")) if payload.get("force_refresh") is not None else False,
            )
            if isinstance(board_result, dict):
                response_payload = dict(board_result)
    except Exception:
        response_payload = None

    if not isinstance(response_payload, dict) or not response_payload:
        if question == DEFAULT_QUESTION:
            if want_refresh and not bool(payload.get("background")):
                queue_intelligence_state_refresh(dict(payload))
            cached_response = _cached_intelligence_response(dict(payload))
            if cached_response is None:
                cached_response = {
                    "ok": True,
                    "top_opportunities": [],
                    "by_sport": {},
                    "analysis": None,
                }
            response_payload = _unwrap_response_payload(cached_response)
        elif want_refresh and not bool(payload.get("background")):
            queue_intelligence_state_refresh(dict(payload))
            cached_response = get_intelligence_state_response(payload, refresh=False, wait=False)
        else:
            cached_response = get_intelligence_state_response(payload, refresh=False, wait=False)
            if cached_response is None:
                cached_response = _load_response_cache_state()
        if not _is_board_response(cached_response):
            cached_response = _load_response_cache_state()
        if not _is_board_response(cached_response) or cached_response.get("ok") is False:
            queue_intelligence_state_refresh(dict(payload))
            cached_response = {
                "ok": True,
                "top_opportunities": [],
                "by_sport": {},
                "analysis": None,
            }
        if cached_response is None:
            cached_response = {
                "ok": True,
                "top_opportunities": [],
                "by_sport": {},
                "analysis": None,
            }
        response_payload = _unwrap_response_payload(cached_response)

    board_headline = _board_headline_for_question(question, response_payload)
    parsed_request = _parsed_request_for_question(question, payload)
    if board_headline:
        response_payload = dict(response_payload)
        response_payload["headline"] = board_headline
        if parsed_request:
            response_payload["parsed_request"] = dict(parsed_request)
        nested_response = response_payload.get("response")
        if isinstance(nested_response, dict):
            nested_response = dict(nested_response)
            nested_response.setdefault("headline", board_headline)
            if parsed_request:
                nested_response["parsed_request"] = dict(parsed_request)
            response_payload["response"] = nested_response
    if "response" not in response_payload:
        response_payload["response"] = dict(response_payload)

    response = _apply_user_profile_to_response(dict(response_payload), user_profile)
    response = dict(response)
    if "response" not in response:
        response["response"] = dict(response)
    LAST_RESULT = dict(response.get("response") or response.get("analysis") or {})
    versioned_response = _versioned_query_response(response)
    if user_profile is None:
        _store_response_cache_state(versioned_response)
    return jsonify(versioned_response)


@intelligence_bp.post("/api/intelligence/query/warm")
def intelligence_query_warm_api():
    payload = request.get_json(silent=True) or {}
    queue_intelligence_state_refresh(dict(payload))
    return jsonify({"ok": True, "queued": True})


@intelligence_bp.get("/intelligence/run")
def run_intelligence():
    selected_date = central_today_iso()
    launch_result: dict[str, Any] | None = None
    launched = False
    try:
        launch_result = launch_refresh_run(date=selected_date, mode="fast")
        launched = True
    except Exception:
        launch_result = load_latest_refresh_status()
    queue_intelligence_state_refresh(_intelligence_page_payload(selected_date))
    return jsonify({"ok": True, "selected_date": selected_date, "launched": launched, "refresh": launch_result, "queued": True})


@intelligence_bp.get("/api/intelligence/status")
def intelligence_status_api():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    try:
        status = build_intelligence_status(selected_date=selected_date)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "selected_date": selected_date}), 500
    response_payload = {"ok": True, "status": status}
    if isinstance(status, dict):
        response_payload.update(status)
    return jsonify(response_payload)