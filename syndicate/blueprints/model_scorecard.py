"""Serves the daily model scorecard the `model-scorecard` cron publishes.

Lane `model-scorecard-cron` `[2026-09-17]`. Read-only: every route returns a file the cron
already wrote to this service's disk, so the web process computes nothing (the web/worker
split in CLAUDE.md). A missing file is a 404 that says what is missing, never an on-request
rebuild.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify

from syndicate.features.shared import skill_overlay

model_scorecard_bp = Blueprint("model_scorecard", __name__)

REPORT_DIR = "reports/model_scorecard"
LATEST = f"{REPORT_DIR}/model_scorecard_latest.json"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def _dated(day: str, suffix: str) -> str:
    # No ISO date in the published NAME: the workers' `pull_hot_artifacts(*<date>*)` would
    # otherwise copy every day's scorecard onto both worker disks on every cycle.
    return f"{REPORT_DIR}/model_scorecard_{day.replace('-', '')}.{suffix}"


def _read_json(relative: str) -> tuple[Any, int]:
    path = _data_root() / relative
    if not path.is_file():
        return {"ok": False, "error": "not_published", "path": relative}, 404
    try:
        return json.loads(path.read_text(encoding="utf-8")), 200
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"unreadable: {type(exc).__name__}", "path": relative}, 500


@model_scorecard_bp.get("/api/model-scorecard")
def model_scorecard_latest():
    payload, status = _read_json(LATEST)
    return jsonify(payload), status


@model_scorecard_bp.get("/api/model-scorecard/<day>")
def model_scorecard_day(day: str):
    if not _DAY.match(day):
        return jsonify({"ok": False, "error": "day must be YYYY-MM-DD"}), 400
    payload, status = _read_json(_dated(day, "json"))
    return jsonify(payload), status


@model_scorecard_bp.get("/api/model-scorecard/overlay")
def model_scorecard_overlay():
    """The overlay file web holds, and what THIS process's scorer is using right now."""
    payload, status = _read_json(skill_overlay.OVERLAY_PATH)
    summary: dict[str, Any] = {"path": skill_overlay.OVERLAY_PATH, "file_status": status,
                               "switch_enabled": skill_overlay.overlay_enabled(),
                               "scorer_in_this_process": skill_overlay.status()}
    if status == 200 and isinstance(payload, dict):
        table, reason = skill_overlay.validate(payload)
        summary.update({"generated_at": payload.get("generated_at"), "expires_at": payload.get("expires_at"),
                        "window": payload.get("window"), "buckets": sorted((payload.get("buckets") or {}).keys()),
                        "valid": table is not None, "validation": reason})
    return jsonify(summary), 200


@model_scorecard_bp.get("/model-scorecard")
def model_scorecard_page():
    payload, status = _read_json(LATEST)
    if status != 200 or not isinstance(payload, dict):
        return Response("No model scorecard has been published yet.\n", status=404, mimetype="text/plain")
    day = str(payload.get("today_central") or "")
    path = _data_root() / _dated(day, "md") if _DAY.match(day) else None
    if path is None or not path.is_file():
        return Response(json.dumps(payload, indent=1), mimetype="application/json")
    return Response(path.read_text(encoding="utf-8"), mimetype="text/markdown; charset=utf-8")
