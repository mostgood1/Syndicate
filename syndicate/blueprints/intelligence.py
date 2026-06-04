from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.shared.timezone import central_today_iso


intelligence_bp = Blueprint("syndicate_intelligence", __name__)


@intelligence_bp.get("/intelligence")
def intelligence_home():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    status_report = build_intelligence_status(selected_date=selected_date)
    return render_template(
        "intelligence.html",
        selected_date=selected_date,
        status_report=status_report,
        default_questions=[
            "What are the best live bets on the board right now?",
            "Build me a two-leg parlay from the strongest pregame edges.",
            "Give me the top cross-sport value plays using model edge and confidence.",
        ],
        show_app_header=True,
        page_body_class="syndicate-intelligence-page",
        page_shell_class="syndicate-intelligence-shell",
    )


@intelligence_bp.get("/api/intelligence/status")
def intelligence_status_api():
    selected_date = str(request.args.get("date") or "").strip() or None
    payload = build_intelligence_status(selected_date=selected_date, force_refresh=bool(request.args.get("refresh")))
    return jsonify({"ok": True, **payload})


@intelligence_bp.post("/api/intelligence/query")
def intelligence_query_api():
    payload = request.get_json(silent=True) if request.is_json else None
    payload = payload if isinstance(payload, dict) else {}
    question = str(payload.get("question") or request.form.get("question") or "").strip()
    selected_date = str(payload.get("date") or request.form.get("date") or "").strip() or None
    mode = str(payload.get("mode") or request.form.get("mode") or "").strip() or None
    sport = str(payload.get("sport") or request.form.get("sport") or "").strip() or None
    limit_value = payload.get("limit") or request.form.get("limit")

    if not question:
        return jsonify({"ok": False, "error": "question is required"}), 400

    result = run_intelligence_query(
        question,
        selected_date=selected_date,
        mode=mode,
        sport=sport,
        limit=int(limit_value) if str(limit_value or "").strip() else None,
        force_refresh=True,
    )
    return jsonify({"ok": True, "query": question, "response": result})