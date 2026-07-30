"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Cross-sport "opportunity board": surfaces the intelligence-evaluation
  ledger's hit-rate/ROI/CLV performance analytics (previously computed but
  never displayed anywhere) as a page + JSON API.

Constraints:
- State-driven execution
- Avoid redundant computation
- Read-only: this blueprint never writes to the evaluation ledger.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template, request

from syndicate.features.shared.intelligence_evaluation import build_recommendation_performance_analytics_for_window
from syndicate.features.shared.timezone import central_today_iso


opportunity_board_bp = Blueprint("syndicate_opportunity_board", __name__)

_DEFAULT_WINDOW_DAYS = 30


def _iso_or_none(value: str | None) -> str | None:
    text = str(value or "").strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            date.fromisoformat(text)
        except Exception:
            return None
        return text
    return None


def _default_window() -> tuple[str, str]:
    until = central_today_iso()
    since = (date.fromisoformat(until) - timedelta(days=_DEFAULT_WINDOW_DAYS - 1)).isoformat()
    return since, until


def _resolve_window() -> tuple[str, str]:
    default_since, default_until = _default_window()
    since = _iso_or_none(request.args.get("since")) or default_since
    until = _iso_or_none(request.args.get("until")) or default_until
    return since, until


@opportunity_board_bp.get("/intelligence/opportunity-board")
def opportunity_board():
    since, until = _resolve_window()
    sport = str(request.args.get("sport") or "").strip().lower() or None
    context = {
        "api_path": "/intelligence/api/opportunity-board",
        "since": since,
        "until": until,
        "sport": sport or "",
        "back_href": "/",
        "back_label": "Home",
        "self_href": "/intelligence/opportunity-board",
    }
    return render_template("intelligence/opportunity_board.html", **context)


@opportunity_board_bp.get("/intelligence/api/opportunity-board")
def api_opportunity_board():
    since, until = _resolve_window()
    sport = str(request.args.get("sport") or "").strip().lower() or None
    payload = build_recommendation_performance_analytics_for_window(since=since, until=until, sport=sport)
    return jsonify({"ok": True, "window": {"since": since, "until": until, "sport": sport}, **payload})
