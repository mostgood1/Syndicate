from __future__ import annotations

from typing import Any

from pipeline.intelligence_models import IntelligenceResult


def format_intelligence_query_response(*, question: str, result: IntelligenceResult) -> dict[str, Any]:
    response = result.to_dict()
    structured_response = response.get("structured_response") if isinstance(response.get("structured_response"), dict) else {}
    payload = {
        "ok": True,
        "query": str(question or "").strip(),
        "response": response,
    }
    preview = structured_response.get("preview") if isinstance(structured_response, dict) else None
    if preview is not None:
        payload["preview"] = preview
    player_analysis = structured_response.get("player_analysis") if isinstance(structured_response, dict) else None
    if player_analysis is not None:
        payload["player_analysis"] = player_analysis
    return payload


def format_intelligence_query_error(*, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": str(error or "").strip() or "Unknown error",
    }
