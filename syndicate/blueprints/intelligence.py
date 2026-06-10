from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
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
    print("✅ SERVING LAST RESULT")
    return jsonify({
        "ok": True,
        "response": LAST_RESULT
    })

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
