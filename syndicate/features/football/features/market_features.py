from __future__ import annotations

from typing import Any


def build_market_features(game: dict[str, Any]) -> dict[str, Any]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    return {
        "moneyline": {
            "home": betting.get("home_ml"),
            "away": betting.get("away_ml"),
        },
        "spread": {
            "home": betting.get("home_spread"),
            "away": betting.get("away_spread"),
        },
        "total": {
            "line": betting.get("total"),
        },
        "props": dict(game.get("props") or {}),
    }