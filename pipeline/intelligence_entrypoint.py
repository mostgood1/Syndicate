from __future__ import annotations

from typing import Any

from pipeline.intelligence_pipeline import run_intelligence_pipeline
from router.query_router import QueryRouter


_QUERY_ROUTER = QueryRouter()


def route_intelligence_request(request_or_payload: Any) -> dict[str, Any]:
    return _QUERY_ROUTER.route_request(request_or_payload)


def run_routed_intelligence_pipeline(request_or_payload: Any):
    return run_intelligence_pipeline(route_intelligence_request(request_or_payload))
