from __future__ import annotations

import fnmatch
import os
import threading
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import url_for

from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared.artifact_publisher import relative_to_data_root
from syndicate.features.shared.ops_refresh import build_refresh_plan
from syndicate.features.shared.ops_refresh import _assert_no_active_refresh_run
from syndicate.features.shared.ops_refresh import cancel_latest_refresh_run
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import load_latest_refresh_log
from syndicate.features.shared.ops_refresh import load_latest_refresh_status
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.timezone import normalize_timestamped_payload


ops_bp = Blueprint("ops", __name__)
_OPS_JOBS_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ops_jobs_path() -> Path:
    return reports_root() / "ops_jobs.json"


def _read_ops_jobs() -> dict[str, Any]:
    payload = read_json_file(_ops_jobs_path())
    return payload if isinstance(payload, dict) else {}


def _write_ops_jobs(jobs: dict[str, Any]) -> None:
    write_json_file(_ops_jobs_path(), jobs)


def _store_ops_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with _OPS_JOBS_LOCK:
        jobs = _read_ops_jobs()
        current = jobs.get(job_id)
        job = dict(current) if isinstance(current, dict) else {}
        job.update(updates)
        jobs[job_id] = job
        _write_ops_jobs(jobs)
        return job


def _job_current_step(payload: dict[str, Any]) -> str:
    sports_text = str(payload.get("sports") or "").strip().lower()
    if not sports_text or sports_text == "all":
        return "odds_refresh"
    first_sport = sports_text.replace("|", ",").split(",")[0].strip()
    return f"{first_sport}_refresh" if first_sport else "odds_refresh"


def _start_refresh_job(payload: dict[str, Any], *, mode: str = "fast") -> tuple[str, dict[str, Any]]:
    _assert_no_active_refresh_run()
    job_id = uuid.uuid4().hex
    launch_payload = dict(payload)
    launch_payload["mode"] = str(mode or "fast")
    initial_job = {
        "status": "running",
        "start_time": _utc_now(),
        "current_step": _job_current_step(launch_payload),
    }
    _store_ops_job(job_id, initial_job)
    try:
        result = launch_refresh_run(
            date=_payload_value(launch_payload, "date"),
            sports=_payload_value(launch_payload, "sports"),
            phase=_payload_value(launch_payload, "phase"),
            execution_mode=_payload_value(launch_payload, "execution_mode"),
            regions=_payload_value(launch_payload, "regions"),
            bookmakers=_payload_value(launch_payload, "bookmakers"),
            markets=_payload_value(launch_payload, "markets"),
            season=_coerce_int(_payload_value(launch_payload, "season")),
            week=_coerce_int(_payload_value(launch_payload, "week")),
            skip_mirror=_coerce_bool(_payload_value(launch_payload, "skip_mirror")),
            mirror_only=_coerce_bool(_payload_value(launch_payload, "mirror_only")),
            dry_run=_coerce_bool(_payload_value(launch_payload, "dry_run")),
            mode=str(_payload_value(launch_payload, "mode", "fast") or "fast"),
            force_refresh=_coerce_bool(_payload_value(launch_payload, "force_refresh")),
            launch_mode=_payload_value(launch_payload, "launch_mode"),
        )
    except Exception as exc:
        return job_id, _store_ops_job(
            job_id,
            {
                "status": "failed",
                "end_time": _utc_now(),
                "current_step": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    pid_raw = result.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    state = str(result.get("state") or "").strip().lower()
    updates: dict[str, Any] = {"launch_result": result, "pid": pid, "current_step": initial_job["current_step"]}
    if state == "pending_external":
        updates["status"] = "running"
        updates["current_step"] = "pending_external"
    elif pid is None:
        updates["status"] = "done" if bool(result.get("ok")) else "failed"
        updates["end_time"] = _utc_now()
        updates["current_step"] = updates["status"]
    else:
        updates["status"] = "running"
    return job_id, _store_ops_job(job_id, updates)


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
    header_or_query = str(request.headers.get("X-Admin-Token") or request.args.get("admin_token") or "").strip()
    if header_or_query:
        return header_or_query
    return str(request.form.get("admin_token") or "").strip()


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
    return jsonify({"ok": True, "status": normalize_timestamped_payload(load_latest_refresh_status())})


@ops_bp.get("/api/ops/version")
def api_ops_version() -> Any:
    return jsonify({"ok": True, "version": _build_version_payload()})


@ops_bp.post("/api/ops/bootstrap/run")
def api_ops_bootstrap_run() -> Any:
    try:
        # Import and run the bootstrap script to copy repo data into the mounted data root
        try:
            from scripts.bootstrap_data_root import main as _bootstrap_main  # type: ignore
        except Exception as exc:
            return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500
        exit_code = _bootstrap_main()
        if exit_code == 0:
            return jsonify({"ok": True, "message": "bootstrap completed"}), 200
        return jsonify({"ok": False, "error": f"bootstrap returned exit code {exit_code}"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@ops_bp.post("/api/ops/artifacts/publish")
def api_ops_artifacts_publish() -> Any:
    payload = _request_data()
    relative_path = str(payload.get("relative_path") or "").strip().replace("\\", "/")
    content = payload.get("content")
    if not relative_path or content is None:
        return jsonify({"ok": False, "error": "relative_path and content are required."}), 400
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        return jsonify({"ok": False, "error": "invalid relative_path."}), 400
    if not is_hot_artifact_relative_path(relative_path):
        return jsonify({"ok": False, "error": "relative_path is not an allowed hot artifact."}), 403

    target_path = data_root() / Path(relative_path)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        temp_path.write_text(str(content), encoding="utf-8")
        os.replace(temp_path, target_path)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return jsonify({"ok": True, "relative_path": relative_path, "bytes": target_path.stat().st_size}), 200


@ops_bp.get("/api/ops/artifacts/export")
def api_ops_artifacts_export() -> Any:
    # Phase 4 of migrating off the daily-update GHA cron: read-only
    # counterpart to /api/ops/artifacts/publish above. The GHA runner has no
    # filesystem access to any Render disk, so this lets the reduced
    # backup-only workflow pull the current hot-artifact set back down over
    # HTTP and git-commit it as a cold-start safety net, instead of
    # regenerating everything by re-running the full pipeline. Scoped to the
    # exact same allowlist as the publish endpoint -- never returns
    # bulk/historical data.
    #
    # Optional filters (both stay allowlist-scoped):
    #   ?path=<relative_path>     exact single artifact
    #   ?pattern=<fnmatchglob>    subset of the hot-artifact set
    # Exporting everything at once can exceed Render's proxy timeout (502),
    # so callers debugging a single artifact should always pass ?path=.
    root = data_root()
    exact_path = str(request.args.get("path") or "").strip().replace("\\", "/")
    if exact_path:
        if exact_path.startswith("/") or ".." in exact_path.split("/"):
            return jsonify({"ok": False, "error": "invalid path."}), 400
        if not is_hot_artifact_relative_path(exact_path):
            return jsonify({"ok": False, "error": "path is not an allowed hot artifact."}), 403
        target = root / Path(exact_path)
        if not target.is_file():
            return jsonify({"ok": True, "count": 0, "artifacts": {}})
        try:
            return jsonify({"ok": True, "count": 1, "artifacts": {exact_path: target.read_text(encoding="utf-8")}})
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    subset_pattern = str(request.args.get("pattern") or "").strip().replace("\\", "/")
    artifacts: dict[str, str] = {}
    for pattern in HOT_ARTIFACT_PATTERNS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            relative_path = relative_to_data_root(path)
            if not relative_path or not is_hot_artifact_relative_path(relative_path):
                continue
            if subset_pattern and not fnmatch.fnmatch(relative_path, subset_pattern):
                continue
            try:
                artifacts[relative_path] = path.read_text(encoding="utf-8")
            except Exception:
                continue
    return jsonify({"ok": True, "count": len(artifacts), "artifacts": artifacts})


@ops_bp.get("/api/ops/live-refresh/state")
def api_ops_live_refresh_state() -> Any:
    # Read-only view of the live-refresh loop's shared state (tick meta, gate
    # checks). Written by the live-odds-worker through the Redis-backed
    # refresh-state store, so the web service can serve it without sharing a
    # disk -- this is the only way to see WHY the worker's MLB daily-sim /
    # look-ahead gates did or didn't fire on a given tick.
    from syndicate.features.shared.refresh_state_store import read_json_file as _state_read_json
    from syndicate.features.shared.refresh_state_store import reports_root as _state_reports_root

    base = _state_reports_root() / "live_refresh_loop"
    state = {
        "latest_tick": _state_read_json(base / "latest_live_refresh_tick.json"),
        "loop_status": _state_read_json(base / "live_refresh_loop_status.json"),
        "last_mlb_sim_check": _state_read_json(base / "last_mlb_sim_check.json"),
        "last_look_ahead_check": _state_read_json(base / "last_look_ahead_check.json"),
    }
    run_stamp = str(request.args.get("sim_run") or "").strip()
    sim_date = str(request.args.get("sim_date") or "").strip()
    if run_stamp and sim_date:
        sim_base = base / "mlb_sim_runs"
        state["sim_run_status"] = _state_read_json(sim_base / f"{sim_date}_{run_stamp}_status.json")
    return jsonify({"ok": True, "state": normalize_timestamped_payload(state)})


@ops_bp.get("/api/ops/mlb/sims-list")
def api_ops_mlb_sims_list() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.mlb import sources as mlb_sources
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # Build candidate roots similar to sources.daily_sim_artifact_path
    repo_root = Path(current_app.root_path).resolve().parent
    roots: list[Path] = []
    env_value = str(os.environ.get("SYNDICATE_MLB_SOURCE_ROOT") or "").strip()
    if env_value:
        roots.append(Path(env_value))
    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if data_root:
        roots.append(Path(data_root).resolve() / "mlb_source")
    roots.append(repo_root / "data" / "mlb_source")

    results = []
    rel = Path("data", "daily", "sims", date)
    for root in roots:
        try:
            cand = root
            # check both root and root/source_artifacts
            for probe in (cand, cand / "source_artifacts"):
                if not probe.exists() or not probe.is_dir():
                    continue
                sims_dir = (probe / rel)
                if not sims_dir.exists() or not sims_dir.is_dir():
                    continue
                files = [p.name for p in sorted(sims_dir.glob("*.json")) if p.is_file()]
                results.append({"root": str(probe), "count": len(files), "files": files[:200]})
        except Exception:
            continue

    return jsonify({"ok": True, "date": date, "results": results})


def _inspect_artifact_path(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(path), "exists": path.exists() and path.is_file()}
    if not entry["exists"]:
        return entry
    try:
        entry["size_bytes"] = path.stat().st_size
        if path.suffix == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                line_count = sum(1 for _ in handle)
            entry["data_rows"] = max(0, line_count - 1)
        elif path.suffix == ".json":
            import json as _json

            payload = _json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                data_value = payload.get("data") if payload.get("data") is not None else payload.get("per_game")
                entry["data_rows"] = len(data_value) if isinstance(data_value, list) else None
                entry["top_level_keys"] = sorted(payload.keys())[:20]
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


@ops_bp.post("/api/ops/live-refresh-loop/reset-lineup-gate")
def api_ops_reset_lineup_gate() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    # Clears the shared (keyvalue-backed) "last lineup/injury check" state that
    # gates when live-odds-worker's background loop is allowed to force a
    # smart-sim recompute (see _should_force_sim_rerun in live_refresh_loop.py).
    # An empty stored fingerprint set unconditionally reads as "changed" on the
    # next tick, so this forces that loop to recompute+republish on its next
    # cycle without waiting for an actual roster/injury change to be detected.
    path = reports_root() / "live_refresh_loop" / "last_lineup_check.json"
    write_json_file(path, {})
    return jsonify({"ok": True, "path": str(path)})


@ops_bp.get("/api/ops/wnba/artifact-counts")
def api_ops_wnba_artifact_counts() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.shared.source_roots import preferred_artifact_roots
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # processed_root() unconditionally prefers a "source_artifacts" candidate
    # root whether or not that location actually has anything written to it,
    # so report every candidate root's status rather than just the first one
    # -- that mismatch is exactly what made this endpoint necessary.
    candidate_roots = [
        candidate / "data" / "processed"
        for candidate in preferred_artifact_roots(__file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source")
    ]
    file_names = [
        f"game_cards_{date}.csv",
        f"props_edges_{date}.csv",
        f"props_predictions_{date}.csv",
        f"props_recommendations_{date}.csv",
        f"props_recommendations_top_by_game_{date}.json",
        f"recommendations_slate_{date}.json",
    ]
    results: dict[str, Any] = {}
    for file_name in file_names:
        results[file_name] = [
            {"root": str(root), "is_processed_root_default": root == wnba_processed_root(), **_inspect_artifact_path(root / file_name)}
            for root in candidate_roots
        ]

    return jsonify(
        {
            "ok": True,
            "date": date,
            "processed_root": str(wnba_processed_root()),
            "candidate_roots": [str(root) for root in candidate_roots],
            "results": results,
        }
    )


@ops_bp.get("/api/ops/wnba/status-trace")
def api_ops_wnba_status_trace() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.wnba import cards as wnba_cards
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    def _summarize_games(games: Any) -> Any:
        if not isinstance(games, list):
            return games
        out = []
        for game in games:
            if not isinstance(game, dict):
                continue
            out.append(
                {
                    "event_id": game.get("event_id"),
                    "away_tri": game.get("away_tri"),
                    "home_tri": game.get("home_tri"),
                    "status": game.get("status"),
                    "detail": game.get("detail"),
                    "live_state": game.get("live_state"),
                }
            )
        return out

    trace: dict[str, Any] = {"ok": True, "date": date}
    try:
        trace["render_web_dyno"] = wnba_cards._render_web_dyno()
    except Exception as exc:
        trace["render_web_dyno_error"] = f"{type(exc).__name__}: {exc}"
    try:
        trace["local_live_state_payload"] = wnba_cards._local_live_state_payload(date)
    except Exception as exc:
        trace["local_live_state_payload_error"] = f"{type(exc).__name__}: {exc}"
    try:
        live_games, live_source_path = wnba_cards._games_from_live_state_fallback(date)
        trace["games_from_live_state_fallback"] = {"source_path": live_source_path, "games": _summarize_games(live_games)}
    except Exception as exc:
        trace["games_from_live_state_fallback_error"] = f"{type(exc).__name__}: {exc}"
    try:
        artifact_games, cards_path, _recs_path = wnba_cards._games_from_artifacts(date)
        trace["games_from_artifacts"] = {"source_path": str(cards_path), "games": _summarize_games(artifact_games)}
    except Exception as exc:
        trace["games_from_artifacts_error"] = f"{type(exc).__name__}: {exc}"
    try:
        cards_context = wnba_cards.build_cards_page_context(date, allow_stored_date_fallback=False)
        trace["build_cards_page_context_games"] = _summarize_games(cards_context.get("games"))
        trace["build_cards_page_context_source_path"] = cards_context.get("source_path")
    except Exception as exc:
        trace["build_cards_page_context_error"] = f"{type(exc).__name__}: {exc}"
    try:
        source_payload = wnba_cards.build_source_cards_payload(date, allow_stored_date_fallback=False)
        trace["build_source_cards_payload_games"] = _summarize_games(source_payload.get("games"))
    except Exception as exc:
        trace["build_source_cards_payload_error"] = f"{type(exc).__name__}: {exc}"

    return jsonify(trace)


@ops_bp.get("/api/ops/mlb/live-check")
def api_ops_mlb_live_check() -> Any:
    # Protected endpoint: requires admin token
    date = str(request.args.get("date") or "").strip()
    game_pk_raw = request.args.get("game_pk") or request.args.get("gamePk") or request.args.get("game")
    try:
        game_pk = int(str(game_pk_raw)) if game_pk_raw is not None else None
    except Exception:
        game_pk = None
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        repo_root = Path(current_app.root_path).resolve().parent
        data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data")
        # live_lens report path candidates
        live_lens_candidates = []
        for base in (data_root / "mlb_source", repo_root / "data" / "mlb_source"):
            live_path = base / "source_artifacts" / "data" / "live_lens" / f"live_lens_report_{date.replace('-', '_')}.json"
            live_lens_candidates.append(str(live_path))
        # raw feed candidates
        raw_candidates = []
        season = date.split("-", 1)[0] if date else None
        if season and game_pk:
            for base in (data_root / "mlb_source", repo_root / "data" / "mlb_source"):
                raw_dir = base / "source_artifacts" / "data" / "raw" / "statsapi" / season / date
                for suffix in (".json.gz", ".json"):
                    raw_candidates.append(str(raw_dir / f"{int(game_pk)}{suffix}"))

        # check existence and sizes
        live_results = []
        for path in live_lens_candidates:
            p = Path(path)
            live_results.append({"path": path, "exists": p.exists() and p.is_file(), "size": p.stat().st_size if p.exists() and p.is_file() else None})

        raw_results = []
        for path in raw_candidates:
            p = Path(path)
            raw_results.append({"path": path, "exists": p.exists() and p.is_file(), "size": p.stat().st_size if p.exists() and p.is_file() else None})

        return jsonify({"ok": True, "date": date, "game_pk": game_pk, "live_lens": live_results, "raw_feed": raw_results})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


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
            force_refresh=_coerce_bool(request.args.get("force_refresh")),
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
        job_id, job = _start_refresh_job(payload, mode="fast")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "status": "started", "job_id": job_id, "job": normalize_timestamped_payload(job)}), 202


@ops_bp.post("/api/ops/full-refresh/run")
def api_ops_full_refresh_run() -> Any:
    payload = _request_data()
    try:
        job_id, job = _start_refresh_job(payload, mode="full")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "status": "started", "job_id": job_id, "job": job}), 202


@ops_bp.post("/api/ops/odds-refresh/cancel")
def api_ops_odds_refresh_cancel() -> Any:
    try:
        result = cancel_latest_refresh_run()
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": bool(result.get("ok")), "cancel": normalize_timestamped_payload(result)}), 200 if result.get("ok") else 409


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
    status_payload: dict[str, Any] = {
        "refresh_status": {
            "manifest_path": "",
            "manifest_exists": False,
            "manifest": {},
            "artifacts": {},
            "mirror_manifests": [],
            "runtime": {"state": "unknown", "detail": "Refresh status is unavailable."},
            "history": [],
        },
        "daily_update": {
            "manifest_path": "",
            "manifest_exists": False,
            "manifest": {},
            "runtime": {"state": "unknown", "detail": "Daily update status is unavailable."},
            "checkpoint_path": "",
            "checkpoint_exists": False,
            "checkpoint": {},
            "run_state_path": "",
            "run_state_exists": False,
            "run_state": {},
            "trace_path": "",
            "trace_exists": False,
            "trace": {},
        },
    }
    try:
        loaded_status = load_latest_refresh_status()
        if isinstance(loaded_status, dict):
            status_payload = loaded_status
    except Exception as exc:
        plan_error = f"{type(exc).__name__}: {exc}"
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
            force_refresh=_coerce_bool(request.args.get("force_refresh")),
        )
    except ValueError as exc:
        plan_error = str(exc)
    except Exception as exc:
        plan_error = plan_error or f"{type(exc).__name__}: {exc}"

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
        "force_refresh": _coerce_bool(request.args.get("force_refresh")),
        "mode": str(request.args.get("mode") or "fast").strip().lower() or "fast",
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
            mode=str(_payload_value(payload, "mode", "fast") or "fast"),
            force_refresh=_coerce_bool(_payload_value(payload, "force_refresh")),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    args = {
        "launched": "1",
        "pid": str(result.get("pid") or "").strip(),
        "run_stamp": str(result.get("run_stamp") or "").strip(),
        "dry_run": "1" if _coerce_bool(_payload_value(payload, "dry_run")) else "0",
    }
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