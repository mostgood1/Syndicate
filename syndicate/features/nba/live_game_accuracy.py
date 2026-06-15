from __future__ import annotations

from functools import lru_cache
from typing import Any

from syndicate.features.nba.sources import artifact_processed_root
from syndicate.features.shared.live_lens_local import build_empty_live_accuracy_payload
from syndicate.features.shared.live_lens_local import build_local_live_accuracy_payload


def _artifact_root():
    return artifact_processed_root()


@lru_cache(maxsize=256)
def build_live_game_accuracy_payload(query_string: str) -> dict[str, Any] | None:
    local_payload = build_local_live_accuracy_payload(query_string, _artifact_root(), mode="game")
    if isinstance(local_payload, dict):
        return local_payload
    return build_empty_live_accuracy_payload(query_string, mode="game")