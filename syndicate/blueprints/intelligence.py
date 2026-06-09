from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from pipeline.formatter import format_intelligence_query_error
from pipeline.formatter import format_intelligence_query_response
from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.shared.timezone import central_today_iso


intelligence_bp = Blueprint("syndicate_intelligence", __name__)

_DEFAULT_INTELLIGENCE_QUESTION = "What are the best live bets on the board right now?"


def _optional_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _optional_int(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except Exception:
        return None


def _intelligence_page_payload(selected_date: str) -> dict[str, object]:
    question = str(request.args.get("question") or _DEFAULT_INTELLIGENCE_QUESTION).strip()
    payload: dict[str, object] = {
        "question": question,
        "date": selected_date,
        "mode": str(request.args.get("mode") or "").strip(),
        "sport": str(request.args.get("sport") or "").strip(),
        "timing": str(request.args.get("timing") or "").strip(),
        "limit": _optional_int(request.args.get("limit")),
        "include_props": _optional_bool(request.args.get("include_props")),
        "include_games": _optional_bool(request.args.get("include_games")),
        "force_refresh": _optional_bool(request.args.get("force_refresh")) if request.args.get("force_refresh") is not None else True,
    }
    return payload


@intelligence_bp.get("/intelligence")
def intelligence_home():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    payload = _intelligence_page_payload(selected_date)
    initial_response: dict[str, object] = {}
    try:
        pipeline_result = run_routed_intelligence_pipeline(payload)
        if hasattr(pipeline_result, "to_dict"):
            initial_response = pipeline_result.to_dict()
        elif isinstance(pipeline_result, dict):
            initial_response = dict(pipeline_result)
    except Exception:
        initial_response = {}
    return render_template(
        "intelligence.html",
        selected_date=selected_date,
        initial_question=str(payload.get("question") or _DEFAULT_INTELLIGENCE_QUESTION),
        initial_response=initial_response,
        default_questions=[
            "What are the best live bets on the board right now?",
            "What are the best home run matchups today and why? Build a top 10 table and chart.",
            "Build me a two-leg parlay from the strongest pregame edges.",
            "Give me the top cross-sport value plays using model edge and confidence.",
        ],
        show_app_header=True,
        page_body_class="syndicate-intelligence-page",
        page_shell_class="syndicate-intelligence-shell",
    )


@intelligence_bp.get("/intelligence/status")
def intelligence_status_page():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    status_report = build_intelligence_status(selected_date=selected_date)
    return render_template(
        "intelligence_status.html",
        selected_date=selected_date,
        status_report=status_report,
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
    try:
        pipeline_result = run_routed_intelligence_pipeline(request)
    except ValueError as exc:
        return jsonify(format_intelligence_query_error(error=str(exc))), 400
    question = str((pipeline_result.pipeline_request or {}).get("question") or "").strip()
    if not question:
        return jsonify(format_intelligence_query_error(error="question is required")), 400
    return jsonify(format_intelligence_query_response(question=question, result=pipeline_result))