"""Serves the daily cheat sheets `scripts/build_cheat_sheets.py` writes (lane `cheat-sheets`, user 2026-10-14).

Read-only, like `model_scorecard.py`: every route returns what the generator already wrote to
`<data root>/cheatsheets/<sport>/<date>.json`. The evidence behind a sheet costs 1-12 s per player on the
fleet, so it is never built on a request (the web/worker split in CLAUDE.md); a missing sheet is a 404 that
names what is missing, or an empty page, never an on-request rebuild.

    /cheatsheets                      the branded page, newest sheet per sport (?date=YYYY-MM-DD for one day)
    /api/cheatsheets                  which sports and dates exist
    /api/cheatsheets/<sport>/<date>   one sheet as written
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, render_template_string, request

from syndicate.features.shared import cheat_sheets as cs

cheat_sheets_bp = Blueprint("cheat_sheets", __name__)

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SPORT = re.compile(r"^[a-z]{2,8}$")
TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "cheat_sheets.html"
LOGO_SRC = "/static/brand/syndicate_roi_badge.webp"


def _sheet_dir() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root()) / "cheatsheets"


def _dates(sport: str) -> list[str]:
    folder = _sheet_dir() / sport
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.json") if _DAY.match(p.stem))


def _read(sport: str, day: str) -> dict[str, Any] | None:
    try:
        doc = json.loads((_sheet_dir() / sport / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("sport") == sport else None


def _sports() -> list[str]:
    root = _sheet_dir()
    if not root.is_dir():
        return []
    return [p.name for p in sorted(root.iterdir()) if p.is_dir() and _SPORT.match(p.name)]


@cheat_sheets_bp.get("/api/cheatsheets")
def cheat_sheets_index():
    return jsonify({"ok": True, "sports": {s: _dates(s)[-14:] for s in _sports()}}), 200


@cheat_sheets_bp.get("/api/cheatsheets/<sport>/<day>")
def cheat_sheet_one(sport: str, day: str):
    if not _SPORT.match(sport) or not _DAY.match(day):
        return jsonify({"ok": False, "error": "sport must be a slug and day YYYY-MM-DD"}), 400
    doc = _read(sport, day)
    if doc is None:
        return jsonify({"ok": False, "error": "not_published", "path": f"cheatsheets/{sport}/{day}.json"}), 404
    return jsonify(doc), 200


@cheat_sheets_bp.get("/cheatsheets")
def cheat_sheets_page():
    day = str(request.args.get("date") or "").strip()
    if day and not _DAY.match(day):
        return jsonify({"ok": False, "error": "date must be YYYY-MM-DD"}), 400
    sheets = []
    for sport in _sports():
        dates = _dates(sport)
        pick = day if day else (dates[-1] if dates else None)
        doc = _read(sport, pick) if pick and pick in dates else None
        if doc:
            sheets.append(doc)
    try:
        template = TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"ok": False, "error": "template missing"}), 500
    page = cs.render_page(template, sheets, logo_src=LOGO_SRC)
    # The site menu, the same header every standalone page includes. The page template itself stays plain HTML so
    # `scripts/render_cheat_sheets.py` can render the identical page without Flask (the published artifact).
    page = page.replace("<!--__SITE_HEAD__-->", render_template_string(_SITE_HEAD), 1)
    page = page.replace("<!--__SITE_HEADER__-->", render_template_string(_SITE_HEADER, active_sport_slug="cheatsheets"), 1)
    return Response(page, mimetype="text/html")


_SITE_HEAD = """<link rel="icon" href="{{ url_for('static', filename='shared/favicon-32.png') }}" sizes="32x32" type="image/png">
<link rel="stylesheet" href="{{ url_for('static', filename='shared/standalone_shell.css') }}">"""
_SITE_HEADER = "{% include 'shared/_standalone_app_header.html' %}"
