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
    selected_date = str(request.args.get("date") or "").strip()

    # ✅ lightweight payload (NOT full pipeline input)
    payload = {
        "date": selected_date,
        "question": "top edges today"
    }

    data = {
        "picks": [],
        "portfolio": {},
        "parlays": []
    }

    try:
        result = run_routed_intelligence_pipeline(payload)

        if hasattr(result, "to_dict"):
            raw = result.to_dict()
        elif isinstance(result, dict):
            raw = result
        else:
            raw = {}

        # ✅ CLEAN MAPPING (THIS IS KEY)
        data = {
            "picks": raw.get("recommendations", []) or raw.get("picks", []),
            "portfolio": raw.get("portfolio", {}),
            "parlays": raw.get("parlays", [])
        }

    except Exception as e:
        print("⚠️ intelligence error:", e)

    return render_template("intelligence.html", data=data)


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