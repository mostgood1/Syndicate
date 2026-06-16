from __future__ import annotations

from typing import Any

from pipeline.intelligence_pipeline import run_intelligence_pipeline
from router.query_router import QueryRouter


_QUERY_ROUTER = QueryRouter()


def route_intelligence_request(request_or_payload: Any) -> dict[str, Any]:
    return _QUERY_ROUTER.route_request(request_or_payload)


def run_routed_intelligence_pipeline(request_or_payload: Any):
    routed_request = route_intelligence_request(request_or_payload)
    from pipeline.intelligence_state import acquire_intelligence_execution_guard
    from pipeline.intelligence_state import get_latest_intelligence_cached_response
    from pipeline.intelligence_state import release_intelligence_execution_guard

    if not acquire_intelligence_execution_guard():
        cached_response = get_latest_intelligence_cached_response(routed_request)
        if cached_response is not None:
            return cached_response
    try:
        return run_intelligence_pipeline(routed_request)
    finally:
        release_intelligence_execution_guard()
