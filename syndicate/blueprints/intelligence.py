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


# ✅ CLEAN REFRESH FUNCTION (NO FLASK IMPORTS HERE)
def refresh_intelligence():
    global LAST_RESULT

    print("🚀 RUNNING PIPELINE")

    try:
        result = run_routed_intelligence_pipeline({
            "question": DEFAULT_QUESTION
        })

        print("✅ PIPELINE COMPLETE")

        raw = result.to_dict() if hasattr(result, "to_dict") else (result or {})

        print("RAW PIPELINE OUTPUT:", raw)

        recs = raw.get("recommendations") or []

        if not recs:
            recs = [{
                "selection": "NO PICKS RETURNED",
                "edge": 0
            }]

        LAST_RESULT = {
            "recommendations": recs,
            "portfolio": raw.get("portfolio", {}),
            "parlays": raw.get("parlays", [])
        }

        print("✅ CACHE UPDATED:", LAST_RESULT)

    except Exception as e:
        print("❌ PIPELINE ERROR:", e)

        LAST_RESULT = {
            "recommendations": [{
                "selection": str(e),
                "edge": 0
            }],
            "portfolio": {},
            "parlays": []
        }


# ✅ UI PAGE
@intelligence_bp.get("/intelligence")
def intelligence_home():
    return render_template("intelligence.html")


# ✅ STATUS PAGE
@intelligence_bp.get("/intelligence/status")
def intelligence_status_page():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    status_report = build_intelligence_status(selected_date=selected_date)
    return render_template("intelligence_status.html", status_report=status_report)


# ✅ STATUS API
@intelligence_bp.get("/api/intelligence/status")
def intelligence_status_api():
    payload = build_intelligence_status()
    return jsonify({"ok": True, **payload})


# ✅ DATA API (FAST — SERVES CACHE ONLY)
@intelligence_bp.post("/api/intelligence/query")
def intelligence_query_api():
    print("✅ SERVING LAST RESULT")
    return jsonify({
        "ok": True,
        "response": LAST_RESULT
    })


# ✅ TEMP TRIGGER ROUTE (RUN PIPELINE SAFELY)
@intelligence_bp.get("/intelligence/run")
def run_intelligence():
    refresh_intelligence()
    return {"ok": True}