from __future__ import annotations

from typing import Any


def build_matchup_features(game: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_id": str(game.get("gamePk") or game.get("game_id") or "").strip(),
        "matchup": str(game.get("matchup") or game.get("summary") or "").strip(),
        "home": str((game.get("home") or {}).get("abbr") or "").strip(),
        "away": str((game.get("away") or {}).get("abbr") or "").strip(),
    }