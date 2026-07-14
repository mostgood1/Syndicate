from __future__ import annotations

from typing import Any


def build_pace_features(game: dict[str, Any]) -> dict[str, Any]:
    pace = game.get("pace_features") if isinstance(game.get("pace_features"), dict) else {}
    return {
        "pace": pace.get("pace"),
        "possessions": pace.get("possessions"),
        "drives": pace.get("drives"),
    }