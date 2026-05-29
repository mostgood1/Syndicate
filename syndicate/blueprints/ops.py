from __future__ import annotations

import os
import subprocess
from typing import Any
from pathlib import Path

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import url_for

from syndicate.features.shared.ops_refresh import build_refresh_plan
from syndicate.features.shared.ops_refresh import cancel_latest_refresh_run
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import load_latest_refresh_log
from syndicate.features.shared.ops_refresh import load_latest_refresh_status


ops_bp = Blueprint("ops", __name__)


def _git_value(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None


def _build_version_payload() -> dict[str, Any]:
    repo_root = Path(current_app.root_path).resolve().parent
    env_commit = str(
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip()
    env_branch = str(
        os.environ.get("RENDER_GIT_BRANCH")
        or os.environ.get("GIT_BRANCH")
        or ""
    ).strip()

    git_commit = _git_value(repo_root, "rev-parse", "HEAD")
    git_branch = _git_value(repo_root, "rev-parse", "--abbrev-ref", "HEAD")

    commit = env_commit or git_commit
    branch = env_branch or git_branch
    commit_source = "env" if env_commit else "git" if git_commit else "unknown"
    branch_source = "env" if env_branch else "git" if git_branch else "unknown"

    return {
        "service": "syndicate",
        "commit": commit,
        "commit_source": commit_source,
        "branch": branch,
        "branch_source": branch_source,
        "render_service_name": str(os.environ.get("RENDER_SERVICE_NAME") or "").strip() or None,
        "render_instance_id": str(os.environ.get("RENDER_INSTANCE_ID") or "").strip() or None,
        "render_external_url": str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip() or None,
        "syndicate_data_root": str(current_app.config.get("SYNDICATE_DATA_ROOT") or os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or None,
        "syndicate_reports_root": str(current_app.config.get("SYNDICATE_REPORTS_ROOT") or os.environ.get("SYNDICATE_REPORTS_ROOT") or "").strip() or None,
    }


def _configured_admin_token() -> str:
    configured = current_app.config.get("ADMIN_TOKEN")
    if configured:
        return str(configured).strip()
    return str(os.environ.get("ADMIN_TOKEN") or os.environ.get("SYNDICATE_ADMIN_TOKEN") or "").strip()


def _request_admin_token() -> str:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return str(request.headers.get("X-Admin-Token") or request.args.get("admin_token") or "").strip()


def _coerce_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    return int(str(value).strip())


def _request_data() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


def _payload_value(payload: dict[str, Any], key: str, default: str | None = None) -> str | None:
    if key not in payload:
        return default
    value = payload.get(key)
    if value is None:
        return default
    return str(value)


@ops_bp.before_request
def _require_admin_token() -> Any:
    configured = _configured_admin_token()
    if not configured:
        return jsonify({"ok": False, "error": "ADMIN_TOKEN not configured."}), 503
    if _request_admin_token() != configured:
        return jsonify({"ok": False, "error": "Unauthorized."}), 401
    return None


@ops_bp.get("/api/ops/odds-refresh/status")
def api_ops_odds_refresh_status() -> Any:
    return jsonify({"ok": True, "status": load_latest_refresh_status()})


@ops_bp.get("/api/ops/version")
def api_ops_version() -> Any:
    return jsonify({"ok": True, "version": _build_version_payload()})


@ops_bp.get("/api/ops/odds-refresh/plan")
def api_ops_odds_refresh_plan() -> Any:
    try:
        payload = build_refresh_plan(
            date=request.args.get("date"),
            sports=request.args.get("sports"),
            phase=request.args.get("phase"),
            execution_mode=request.args.get("execution_mode"),
            regions=request.args.get("regions"),
            bookmakers=request.args.get("bookmakers"),
            markets=request.args.get("markets"),
            season=_coerce_int(request.args.get("season")),
            week=_coerce_int(request.args.get("week")),
            skip_mirror=_coerce_bool(request.args.get("skip_mirror")),
            mirror_only=_coerce_bool(request.args.get("mirror_only")),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "plan": payload})


@ops_bp.post("/api/ops/odds-refresh/run")
def api_ops_odds_refresh_run() -> Any:
    payload = _request_data()
    try:
        result = launch_refresh_run(
            date=_payload_value(payload, "date"),
            sports=_payload_value(payload, "sports"),
            phase=_payload_value(payload, "phase"),
            execution_mode=_payload_value(payload, "execution_mode"),
            regions=_payload_value(payload, "regions"),
            bookmakers=_payload_value(payload, "bookmakers"),
            markets=_payload_value(payload, "markets"),
            season=_coerce_int(_payload_value(payload, "season")),
            week=_coerce_int(_payload_value(payload, "week")),
            skip_mirror=_coerce_bool(_payload_value(payload, "skip_mirror")),
            mirror_only=_coerce_bool(_payload_value(payload, "mirror_only")),
            dry_run=_coerce_bool(_payload_value(payload, "dry_run")),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "launch": result}), 202


@ops_bp.post("/api/ops/odds-refresh/cancel")
def api_ops_odds_refresh_cancel() -> Any:
    try:
        result = cancel_latest_refresh_run()
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": bool(result.get("ok")), "cancel": result}), 200 if result.get("ok") else 409


@ops_bp.get("/api/ops/odds-refresh/logs")
def api_ops_odds_refresh_logs() -> Any:
    stream = request.args.get("stream") or "stderr"
    raw = _coerce_bool(request.args.get("raw"))
    try:
        payload = load_latest_refresh_log(stream=stream)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    if raw:
        return Response(payload.get("content") or "", mimetype="text/plain")
    return jsonify({"ok": True, "log": payload})


@ops_bp.get("/ops/odds-refresh")
def page_ops_odds_refresh() -> Any:
    plan_error: str | None = None
    plan_payload: dict[str, Any] | None = None
    status_payload = load_latest_refresh_status()
    try:
        plan_payload = build_refresh_plan(
            date=request.args.get("date"),
            sports=request.args.get("sports"),
            phase=request.args.get("phase"),
            execution_mode=request.args.get("execution_mode"),
            regions=request.args.get("regions"),
            bookmakers=request.args.get("bookmakers"),
            markets=request.args.get("markets"),
            season=_coerce_int(request.args.get("season")),
            week=_coerce_int(request.args.get("week")),
            skip_mirror=_coerce_bool(request.args.get("skip_mirror")),
            mirror_only=_coerce_bool(request.args.get("mirror_only")),
        )
    except ValueError as exc:
        plan_error = str(exc)
    except Exception as exc:
        plan_error = f"{type(exc).__name__}: {exc}"

    form_state = {
        "date": str(request.args.get("date") or "").strip(),
        "sports": str(request.args.get("sports") or "all").strip() or "all",
        "phase": str(request.args.get("phase") or "all").strip() or "all",
        "execution_mode": str(request.args.get("execution_mode") or "source").strip() or "source",
        "regions": str(request.args.get("regions") or "us").strip() or "us",
        "bookmakers": str(request.args.get("bookmakers") or "").strip(),
        "markets": str(request.args.get("markets") or "").strip(),
        "season": str(request.args.get("season") or "").strip(),
        "week": str(request.args.get("week") or "").strip(),
        "skip_mirror": _coerce_bool(request.args.get("skip_mirror")),
        "mirror_only": _coerce_bool(request.args.get("mirror_only")),
    }
    return render_template(
        "shared/ops_odds_refresh.html",
        page_title_text="Ops Odds Refresh",
        page_body_class="ops-page",
        page_shell_class="ops-shell",
        status_payload=status_payload,
        plan_payload=plan_payload,
        plan_error=plan_error,
        launch_notice={
            "started": _coerce_bool(request.args.get("launched")),
            "pid": str(request.args.get("pid") or "").strip(),
            "run_stamp": str(request.args.get("run_stamp") or "").strip(),
            "dry_run": _coerce_bool(request.args.get("dry_run")),
            "canceled": _coerce_bool(request.args.get("canceled")),
        },
        form_state=form_state,
    )


@ops_bp.post("/ops/odds-refresh/run")
def page_ops_odds_refresh_run() -> Any:
    payload = request.form
    result = launch_refresh_run(
        date=_payload_value(payload, "date"),
        sports=_payload_value(payload, "sports"),
        phase=_payload_value(payload, "phase"),
        execution_mode=_payload_value(payload, "execution_mode"),
        regions=_payload_value(payload, "regions"),
        bookmakers=_payload_value(payload, "bookmakers"),
        markets=_payload_value(payload, "markets"),
        season=_coerce_int(_payload_value(payload, "season")),
        week=_coerce_int(_payload_value(payload, "week")),
        skip_mirror=_coerce_bool(_payload_value(payload, "skip_mirror")),
        mirror_only=_coerce_bool(_payload_value(payload, "mirror_only")),
        dry_run=_coerce_bool(_payload_value(payload, "dry_run")),
    )
    args = {
        "date": result["date"],
        "sports": _payload_value(payload, "sports", "all") or "all",
        "phase": _payload_value(payload, "phase", "all") or "all",
        "execution_mode": _payload_value(payload, "execution_mode", "source") or "source",
        "regions": _payload_value(payload, "regions", "us") or "us",
        "launched": "1",
        "pid": str(result["pid"]),
        "run_stamp": result["run_stamp"],
    }
    for key in ("bookmakers", "markets", "season", "week"):
        value = _payload_value(payload, key)
        if value:
            args[key] = value
    if _coerce_bool(_payload_value(payload, "skip_mirror")):
        args["skip_mirror"] = "1"
    if _coerce_bool(_payload_value(payload, "mirror_only")):
        args["mirror_only"] = "1"
    if _coerce_bool(_payload_value(payload, "dry_run")):
        args["dry_run"] = "1"
    admin_token = _request_admin_token()
    if admin_token:
        args["admin_token"] = admin_token
    return redirect(url_for("ops.page_ops_odds_refresh", **args))


@ops_bp.post("/ops/odds-refresh/cancel")
def page_ops_odds_refresh_cancel() -> Any:
    result = cancel_latest_refresh_run()
    args = {"canceled": "1"}
    admin_token = _request_admin_token()
    if admin_token:
        args["admin_token"] = admin_token
    if not result.get("ok"):
        args["cancel_error"] = "1"
    return redirect(url_for("ops.page_ops_odds_refresh", **args))