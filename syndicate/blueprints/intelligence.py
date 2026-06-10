from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import rank_global_recommendations
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.shared.timezone import central_today_iso

intelligence_bp = Blueprint("syndicate_intelligence", __name__)

DEFAULT_QUESTION = "top edges today"

# ✅ GLOBAL CACHE
LAST_RESULT = {
    "recommendations": [],
    "portfolio": {},
    "parlays": []
}

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
    top_opportunities = rank_global_recommendations(
        collect_all_recommendations(force_refresh=True),
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
    LAST_RESULT = dict(response)
    return jsonify(response)

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
