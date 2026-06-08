from __future__ import annotations

from typing import Any

from pipeline.intelligence_models import IntelligenceResult


def format_intelligence_query_response(*, question: str, result: IntelligenceResult) -> dict[str, Any]:
    return {
        "ok": True,
        "query": str(question or "").strip(),
        "response": result.to_dict(),
    }


def format_intelligence_query_error(*, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": str(error or "").strip() or "Unknown error",
    }
