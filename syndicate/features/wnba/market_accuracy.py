from __future__ import annotations

from functools import lru_cache
from typing import Any

from syndicate.features.shared.live_lens_local import build_local_market_accuracy_payload
from syndicate.features.shared.live_lens_local import build_empty_market_accuracy_payload
from syndicate.features.wnba.sources import processed_roots


def _artifact_root():
    # `#309`: every candidate root, resolved per requested file downstream --
    # not `processed_root()`, which picks one directory up front and picks the
    # wrong one in production.
    return processed_roots()


@lru_cache(maxsize=256)
def build_market_accuracy_payload(query_string: str) -> dict[str, Any] | None:
    local_payload = build_local_market_accuracy_payload(query_string, _artifact_root())
    if isinstance(local_payload, dict):
        return local_payload
    return build_empty_market_accuracy_payload(query_string)