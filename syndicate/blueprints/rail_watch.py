"""Rail Watch: serve the Layer 2 Games Rail monitor page (user 2026-11-20: "make this dashboard self contained so it
doesnt use up ccredits", then "Page on the fleet app").

The page is rendered OFF the request path by the Windows task `SyndicateRailWatch`
(`scripts/rail_monitor/railwatch_tick.py`, every 20 min), which writes one self-contained HTML file onto the data
root. Web only reads that file: no computation, no fleet calls, no fallback build when it is missing (a 404 page
says so instead).
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response

rail_watch_bp = Blueprint("rail_watch", __name__)

_MISSING = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Rail Watch</title></head>"
            "<body style=\"font-family:system-ui,sans-serif;padding:24px\"><h1>Rail Watch</h1>"
            "<p>The page has not been rendered yet. It is written every 20 minutes (10 AM to 2 AM CST) by the "
            "SyndicateRailWatch task.</p></body></html>")


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def _page_path() -> Path:
    return _data_root() / "reports" / "rail_watch" / "index.html"


@rail_watch_bp.get("/rail-watch")
def rail_watch_page():
    try:
        page = _page_path().read_text(encoding="utf-8")
    except OSError:
        return Response(_MISSING, status=404, mimetype="text/html")
    response = Response(page, mimetype="text/html")
    response.headers["Cache-Control"] = "no-store"
    return response
