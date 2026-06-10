from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import rank_global_recommendations
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.shared.timezone import central_today_iso

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
    "parlays": []
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


def _store_response_cache_state(state: dict[str, object]) -> None:
    try:
        _QUERY_RESPONSE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _QUERY_RESPONSE_CACHE_PATH.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _warm_intelligence_query_cache(app, payload: dict[str, object]) -> None:
    try:
        with app.app_context():
            with app.test_request_context("/api/intelligence/query", method="POST", json=payload):
                intelligence_query_api()
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
    bankroll = user_profile.get("bankroll")

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

def refresh_intelligence():
    global LAST_RESULT

    print("🚀 RUNNING PIPELINES (PREGAME + LIVE)")

    try:
        from pipeline.intelligence_pipeline import run_intelligence_pipeline

        # 🔹 PREGAME
        print("🔹 RUNNING PREGAME PIPELINE")
        pregame_result = run_intelligence_pipeline({
            "question": "best pregame betting edges",
            "mode": "recommendation",
            "timing": "pregame",
            "include_games": True,
            "include_props": True,
            "limit": 10
        })

        # 🔹 LIVE
        print("🔹 RUNNING LIVE PIPELINE")
        live_result = run_intelligence_pipeline({
            "question": "best live betting edges",
            "mode": "recommendation",
            "timing": "live",
            "include_games": True,
            "include_props": True,
            "limit": 10
        })

        # ✅ Normalize
        pregame_raw = pregame_result.to_dict() if hasattr(pregame_result, "to_dict") else (pregame_result or {})
        live_raw = live_result.to_dict() if hasattr(live_result, "to_dict") else (live_result or {})

        print("✅ PIPELINE COMPLETE")

        print("PREGAME OUTPUT:", pregame_raw)
        print("LIVE OUTPUT:", live_raw)

        # ✅ Extraction helper
        def extract_recs(raw, tag):
            recs = raw.get("recommendations") or []

            # Try structured_response
            if not recs:
                structured = raw.get("structured_response") or {}
                recs = structured.get("recommendations") or []

            # Try parlays → legs
            if not recs:
                for p in raw.get("parlays", []):
                    for leg in p.get("legs", []):
                        matchup = leg.get("matchup")
                        pick = leg.get("pick")

                        if matchup and pick:
                            try:
                                recs.append({
                                    "selection": f"{matchup} — {pick}",
                                    "edge": float(leg.get("edge") or 0),
                                    "confidence": float(leg.get("confidence") or 0),
                                    "recommended_bet_size": 0.02,
                                    "tag": tag
                                })
                            except Exception as e:
                                print("⚠️ extraction error:", e)

            # Add tag if not present
            for r in recs:
                r["tag"] = r.get("tag") or tag

            return recs

        # ✅ Extract both
        pregame_recs = extract_recs(pregame_raw, "PREGAME")
        live_recs = extract_recs(live_raw, "LIVE")

        # ✅ Combine
        combined = pregame_recs + live_recs

        # ✅ Final fallback
        if not combined:
            combined = [{
                "selection": "No edges detected (pregame or live)",
                "edge": 0,
                "confidence": 0,
                "recommended_bet_size": 0
            }]

        # ✅ Cache
        LAST_RESULT = {
            "recommendations": combined,
            "portfolio": pregame_raw.get("portfolio") or live_raw.get("portfolio") or {},
            "parlays": (pregame_raw.get("parlays") or []) + (live_raw.get("parlays") or [])
        }

        print("✅ CACHE UPDATED:", LAST_RESULT)

    except Exception as e:
        print("❌ PIPELINE ERROR:", e)

        LAST_RESULT = {
            "recommendations": [{
                "selection": f"PIPELINE ERROR: {str(e)[:100]}",
                "edge": 0
            }],
            "portfolio": {},
            "parlays": []
        }

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
    return render_template("intelligence.html")

@intelligence_bp.post("/api/intelligence/query")
def intelligence_query_api():
    global LAST_RESULT
    print("✅ SERVING LAST RESULT")
    payload = request.get_json(silent=True) or {}
    force_refresh = bool(payload.get("force_refresh"))
    user_profile = _normalize_user_profile(payload)
    if not force_refresh and user_profile is None:
        cached_response = _load_response_cache_state()
        if cached_response is not None:
            LAST_RESULT = dict(cached_response.get("response") or {})
            return jsonify(cached_response)
        if isinstance(LAST_RESULT, dict) and any(LAST_RESULT.get(key) for key in ("recommendations", "portfolio", "parlays")):
            cached_recommendations = [dict(item) for item in (LAST_RESULT.get("recommendations") or []) if isinstance(item, dict)]
            cached_portfolio = dict(LAST_RESULT.get("portfolio") or {}) if isinstance(LAST_RESULT.get("portfolio"), dict) else {}
            cached_parlays = [dict(item) for item in (LAST_RESULT.get("parlays") or []) if isinstance(item, dict)]
            cached_by_sport: dict[str, list[dict[str, object]]] = {}
            for recommendation in cached_recommendations:
                sport_key = str(recommendation.get("sport") or recommendation.get("sport_slug") or "unknown").strip().lower() or "unknown"
                cached_by_sport.setdefault(sport_key, []).append(recommendation)
            cached_response = {
                "ok": True,
                "top_opportunities": cached_recommendations,
                "by_sport": cached_by_sport,
                "analysis": {
                    "recommendations": cached_recommendations,
                    "picks": cached_recommendations,
                    "portfolio": cached_portfolio,
                    "parlays": cached_parlays,
                    "top_live_opportunities": [recommendation for recommendation in cached_recommendations if bool(recommendation.get("is_live"))],
                },
                "response": {
                    "recommendations": cached_recommendations,
                    "picks": cached_recommendations,
                    "portfolio": cached_portfolio,
                    "parlays": cached_parlays,
                    "top_live_opportunities": [recommendation for recommendation in cached_recommendations if bool(recommendation.get("is_live"))],
                },
            }
            return jsonify(_versioned_query_response(cached_response))
        empty_response = {
            "ok": True,
            "top_opportunities": [],
            "by_sport": {},
            "analysis": {
                "recommendations": [],
                "picks": [],
                "portfolio": {},
                "parlays": [],
                "top_live_opportunities": [],
            },
            "response": {
                "recommendations": [],
                "picks": [],
                "portfolio": {},
                "parlays": [],
                "top_live_opportunities": [],
            },
        }
        return jsonify(_versioned_query_response(empty_response))

    top_opportunities = rank_global_recommendations(
        collect_all_recommendations(force_refresh=force_refresh),
        limit=int(payload.get("limit") or 10) if str(payload.get("limit") or "").strip() else 10,
    )
    by_sport: dict[str, list[dict[str, object]]] = {}
    for recommendation in top_opportunities:
        sport_key = str(recommendation.get("sport") or recommendation.get("sport_slug") or "unknown").strip().lower() or "unknown"
        by_sport.setdefault(sport_key, []).append(recommendation)

    analysis: dict[str, object] | None = None
    routed_metadata: dict[str, object] = {}
    question = str(payload.get("question") or "").strip()
    if question:
        try:
            routed_result = run_routed_intelligence_pipeline(payload)
            if hasattr(routed_result, "to_dict"):
                routed_result = routed_result.to_dict()
            if isinstance(routed_result, dict):
                routed_metadata = dict(routed_result)
        except Exception:
            routed_metadata = {}

        analysis = run_intelligence_query(
            question,
            selected_date=str(payload.get("date") or payload.get("selected_date") or "").strip() or None,
            mode=str(payload.get("mode") or "").strip() or None,
            sport=str(payload.get("sport") or "").strip() or None,
            limit=payload.get("limit"),
            timing=str(payload.get("timing") or "").strip() or None,
            include_props=payload.get("include_props"),
            include_games=payload.get("include_games"),
            force_refresh=bool(payload.get("force_refresh")),
        )
        selected_date = str(payload.get("date") or payload.get("selected_date") or "").strip()
        if selected_date:
            analysis["selected_date"] = selected_date
        analysis["question"] = question
        lowered_question = question.lower()
        if "parlay" in lowered_question:
            analysis["headline"] = "The Syndicate parlay builder"
        elif "live" in lowered_question:
            analysis["headline"] = "The Syndicate live board brief"
        elif "pregame" in lowered_question:
            analysis["headline"] = "The Syndicate pregame board brief"
        elif "comparison" in lowered_question and "vs" in lowered_question:
            analysis["headline"] = "The Syndicate comparison"
        else:
            analysis.setdefault("headline", "The Syndicate brief")
        for key in (
            "parsed_request",
            "readiness_gate",
            "analysis_views",
            "board_notes",
            "summary",
            "preferences",
            "evaluation_record",
            "structured_response",
            "local_only",
        ):
            value = routed_metadata.get(key)
            if value is not None and (key not in analysis or analysis.get(key) in (None, {}, [], "")):
                analysis[key] = value

    response = {
        "ok": True,
        "top_opportunities": top_opportunities,
        "by_sport": by_sport,
        "analysis": analysis,
    }
    if analysis is not None:
        response["response"] = analysis

    response = _apply_user_profile_to_response(response, user_profile)
    LAST_RESULT = dict(response)
    versioned_response = _versioned_query_response(response)
    if user_profile is None:
        _store_response_cache_state(versioned_response)
    return jsonify(versioned_response)


@intelligence_bp.post("/api/intelligence/query/warm")
def intelligence_query_warm_api():
    payload = request.get_json(silent=True) or {}
    from flask import current_app

    app = current_app._get_current_object()
    warm_payload = dict(payload)
    warm_payload["force_refresh"] = True
    thread = threading.Thread(target=_warm_intelligence_query_cache, args=(app, warm_payload), daemon=True)
    thread.start()
    return jsonify({"ok": True, "queued": True})

@intelligence_bp.get("/intelligence/run")
def run_intelligence():
    refresh_intelligence()
    return {"ok": True}


@intelligence_bp.get("/api/intelligence/status")
def intelligence_status_api():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    try:
        status = build_intelligence_status(selected_date=selected_date)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "selected_date": selected_date}), 500
    return jsonify({"ok": True, "status": status})
