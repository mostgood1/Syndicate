"""Bettor-facing summary for a sport hub page: today's slate size, whether
anything is live right now, and the top N edges. Added 2026-08-03 (Phase 3)
to replace the hubs' developer-facing "migration status" framing.

Reads the same cached, worker-refreshed board state
read_combined_intelligence_response already serves to the /intelligence
board (pipeline/intelligence_state.py) -- it NEVER calls _build_candidate_pool
or any other compute path, only what the background loop has already built.
That function's own docstring documents the hard invariant: calling the
compute path synchronously per request is what caused a production OOM kill
once already. A hub route calling this is exactly as cheap as the board
itself, just sliced to one sport.
"""

from __future__ import annotations

from typing import Any

from pipeline.intelligence_state import read_combined_intelligence_response
from syndicate.features.shared.timezone import central_today_iso

_PLACEHOLDER_TEXT = {"", "-", "—", "n/a", "unknown"}


def _edge_value(item: dict[str, Any]) -> float:
    for key in ("edge", "adjusted_edge", "expected_value", "ev_current"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0


def _display_title(item: dict[str, Any]) -> str:
    for key in ("display_name", "player_name", "name", "pick", "selection"):
        text = str(item.get(key) or "").strip()
        if text and text.lower() not in _PLACEHOLDER_TEXT:
            return text
    market = str(item.get("market") or item.get("market_label") or "").strip()
    return market or "Untitled pick"


def build_hub_bettor_summary(sport_slug: str, *, today_value: str | None = None, top_n: int = 3) -> dict[str, Any]:
    """Cheap, read-only summary: {slate_count, live_now, top_edges, ok}."""
    today = today_value or central_today_iso()
    try:
        response = read_combined_intelligence_response(dates=[today], sport=sport_slug, limit=None)
    except Exception:
        return {"slate_count": 0, "live_now": False, "top_edges": [], "ok": False}

    items = [item for item in (response.get("top_opportunities") or []) if isinstance(item, dict)]
    slate_count = len(items)
    live_now = any(bool(item.get("is_live")) for item in items)

    ranked = sorted(items, key=_edge_value, reverse=True)
    top_edges = [
        {
            "title": _display_title(item),
            "market": str(item.get("market") or item.get("market_label") or "").strip(),
            "edge": _edge_value(item),
            "is_live": bool(item.get("is_live")),
        }
        for item in ranked[:top_n]
    ]
    return {"slate_count": slate_count, "live_now": live_now, "top_edges": top_edges, "ok": True}
