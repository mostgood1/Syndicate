from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.refresh_state_store import list_refresh_status_manifest_paths
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import path_exists
from syndicate.features.shared.refresh_state_store import path_size
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import read_text_file
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from


REPO_ROOT = repo_root_from(__file__)
REPORTS_ROOT = REPO_ROOT / "reports"


def _today_date() -> str:
    return central_today_iso()


def _reports_root() -> Path:
    return reports_root()


def _data_root() -> Path:
    return data_root()


def _load_mirror_manifest_summaries_from_current_data_root() -> list[dict[str, Any]]:
    root = _data_root()
    if not root.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for source_dir in sorted((path for path in root.iterdir() if path.is_dir() and path.name.endswith("_source")), key=lambda item: item.name):
        manifest_path = source_dir / "manifests" / "mirror_refresh_latest.json"
        manifest = read_json_file(manifest_path)
        slug = source_dir.name[: -len("_source")]
        artifact_groups = manifest.get("artifactGroups") if isinstance(manifest, dict) else None
        summaries.append(
            {
                "sport": slug,
                "path": str(manifest_path),
                "exists": manifest_path.exists(),
                "manifest": manifest,
                "date": (manifest or {}).get("date"),
                "copied_artifact_count": (manifest or {}).get("copiedArtifactCount"),
                "artifact_groups": artifact_groups if isinstance(artifact_groups, dict) else {},
            }
        )
    return summaries


def _pid_is_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    else:
        stat_path = Path("/proc") / str(pid) / "stat"
        if stat_path.exists():
            try:
                parts = stat_path.read_text(encoding="utf-8", errors="ignore").split()
                if len(parts) >= 3 and str(parts[2]).strip().upper() == "Z":
                    return False
            except OSError:
                pass
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _elapsed_seconds(*, started_at: Any, finished_at: Any = None) -> int | None:
    started = _parse_utc_timestamp(started_at)
    if started is None:
        return None
    finished = _parse_utc_timestamp(finished_at) or datetime.now(timezone.utc)
    elapsed = int((finished - started).total_seconds())
    return elapsed if elapsed >= 0 else 0


def _runtime_budget_seconds(env_name: str, default_seconds: int | None = 14400) -> int | None:
    raw = str(os.environ.get(env_name) or "").strip()
    if not raw:
        return default_seconds
    try:
        value = int(raw)
    except ValueError:
        return default_seconds
    return value if value > 0 else default_seconds


def _remaining_budget_seconds(*, elapsed_seconds: int | None, budget_seconds: int | None) -> int | None:
    if elapsed_seconds is None or budget_seconds is None:
        return None
    remaining = int(budget_seconds) - int(elapsed_seconds)
    return remaining if remaining >= 0 else 0


def _resolve_launch_mode(override: str | None = None) -> str:
    value = str(override or os.environ.get("SYNDICATE_REFRESH_LAUNCH_MODE") or "").strip().lower()
    if not value and (os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("RENDER_SERVICE_ID")):
        value = "manifest_only"
    if not value:
        value = "detached_subprocess"
    if value in {"detached_subprocess", "manifest_only", "external_runner"}:
        return value
    return "detached_subprocess"


def _is_external_runner_mode(launch_mode: str) -> bool:
    return launch_mode in {"manifest_only", "external_runner"}


def _external_runner_payload(
    *,
    selected_date: str,
    run_stamp: str,
    refresh_status_manifest_path: Path,
    refresh_status_latest_path: Path,
    refresh_and_gate_run_path: Path,
    odds_refresh_path: Path,
    odds_refresh_stderr_path: Path,
    refresh_command: list[str],
) -> dict[str, Any]:
    return {
        "kind": "external_runner",
        "queue_state": "queued",
        "date": selected_date,
        "runStamp": run_stamp,
        "manifestPath": str(refresh_status_manifest_path),
        "latestPath": str(refresh_status_latest_path),
        "runSummaryPath": str(refresh_and_gate_run_path),
        "stdoutPath": str(odds_refresh_path),
        "stderrPath": str(odds_refresh_stderr_path),
        "command": list(refresh_command),
    }


def _derive_refresh_runtime_state(
    manifest: dict[str, Any] | None,
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    manifest = manifest if isinstance(manifest, dict) else {}
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    manifest_state = str(manifest.get("state") or "").strip().lower()
    odds_refresh_payload = ((artifacts.get("odds_refresh") or {}).get("payload") if isinstance(artifacts.get("odds_refresh"), dict) else None)
    odds_refresh_stderr = ((artifacts.get("odds_refresh_stderr") or {}).get("payload") if isinstance(artifacts.get("odds_refresh_stderr"), dict) else None)
    launch_owner = str(manifest.get("launchOwner") or "").strip() or None
    external_runner = manifest.get("externalRunner") if isinstance(manifest.get("externalRunner"), dict) else None

    pid_running = False
    if pid is not None:
        try:
            pid_running = _pid_is_running(pid)
        except Exception:
            pid_running = False

    state = manifest_state or "unknown"
    detail = "No refresh run has been recorded yet."
    if pid_running:
        state = "running"
        detail = f"Refresh process {pid} is still running."
    elif manifest_state == "pending_external":
        state = "pending_external"
        detail = "Refresh run has been recorded and is waiting for an external runner."
    elif isinstance(odds_refresh_payload, dict):
        if bool(odds_refresh_payload.get("ok")):
            state = "finished"
            detail = "Latest refresh run completed successfully."
        else:
            state = "failed"
            detail = "Latest refresh run finished with a failure payload."
    elif manifest_state == "running":
        state = "failed"
        detail = "Refresh process is no longer running and no JSON result was captured."
    elif manifest_state in {"finished", "failed"}:
        state = manifest_state
        detail = f"Latest refresh run is marked {manifest_state}."

    stderr_preview = ""
    if isinstance(odds_refresh_stderr, str) and odds_refresh_stderr:
        stderr_preview = odds_refresh_stderr[:800]

    elapsed_seconds = _elapsed_seconds(started_at=manifest.get("generatedAt"), finished_at=manifest.get("finishedAt"))

    return {
        "state": state,
        "detail": detail,
        "pid": pid,
        "pid_running": pid_running,
        "launch_owner": launch_owner,
        "external_runner": external_runner,
        "exit_code": manifest.get("exitCode"),
        "finished_at": manifest.get("finishedAt"),
        "run_stamp": manifest.get("runStamp"),
        "stderr_preview": stderr_preview,
        "manifest_state": manifest_state or None,
        "elapsed_seconds": elapsed_seconds,
        "runtime_budget_seconds": _runtime_budget_seconds("SYNDICATE_REFRESH_RUNTIME_BUDGET_SECONDS"),
        "remaining_budget_seconds": _remaining_budget_seconds(
            elapsed_seconds=elapsed_seconds,
            budget_seconds=_runtime_budget_seconds("SYNDICATE_REFRESH_RUNTIME_BUDGET_SECONDS"),
        ),
    }


def _load_recent_refresh_history(*, limit: int = 6) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for manifest_path in list_refresh_status_manifest_paths(limit=limit):
        manifest = read_json_file(manifest_path)
        if not manifest:
            continue
        artifacts_dir_raw = str(manifest.get("artifactsDir") or "").strip()
        artifacts: dict[str, Any] = {}
        if artifacts_dir_raw:
            artifacts_dir = Path(artifacts_dir_raw)
            for key, (path, kind) in {
                "odds_refresh": (artifacts_dir / "odds_refresh.json", "json"),
                "odds_refresh_stderr": (artifacts_dir / "odds_refresh.stderr.txt", "text"),
            }.items():
                payload: Any = read_json_file(path) if kind == "json" else read_text_file(path)
                artifacts[key] = {"path": str(path), "exists": path_exists(path), "payload": payload}
        runtime = _derive_refresh_runtime_state(manifest, artifacts)
        history.append(
            {
                "date": manifest.get("date"),
                "run_stamp": manifest.get("runStamp"),
                "artifacts_dir": artifacts_dir_raw,
                "phase": manifest.get("oddsPhase") or "all",
                "sports": manifest.get("oddsSports") or "all",
                "dry_run": bool(manifest.get("dryRun")),
                "runtime": runtime,
            }
        )
        if len(history) >= limit:
            return history
    return history


def _latest_refresh_manifest_context() -> dict[str, Any]:
    refresh_manifest_path = _reports_root() / "refresh_status" / "latest" / "refresh_status_latest.json"
    manifest = read_json_file(refresh_manifest_path) or {}
    artifacts_dir_raw = str(manifest.get("artifactsDir") or "").strip()
    artifacts_dir = Path(artifacts_dir_raw) if artifacts_dir_raw else None
    run_summary_path = Path(str(manifest.get("runSummaryPath") or "").strip()) if str(manifest.get("runSummaryPath") or "").strip() else None
    if run_summary_path is None and artifacts_dir is not None:
        run_summary_path = artifacts_dir / "refresh_and_gate_run.json"
    return {
        "manifest_path": refresh_manifest_path,
        "manifest": manifest,
        "artifacts_dir": artifacts_dir,
        "run_summary_path": run_summary_path,
    }


def _assert_no_active_refresh_run() -> None:
    context = _latest_refresh_manifest_context()
    manifest: dict[str, Any] = context["manifest"] if isinstance(context.get("manifest"), dict) else {}
    state = str(manifest.get("state") or "").strip().lower()
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if pid is not None:
        try:
            if _pid_is_running(pid):
                raise ValueError(f"A refresh run is already active (pid={pid}). Cancel it before starting a new run.")
        except Exception:
            pass
    external_runner = manifest.get("externalRunner") if isinstance(manifest.get("externalRunner"), dict) else {}
    queue_state = str(external_runner.get("queue_state") or "").strip().lower()
    if state == "pending_external":
        raise ValueError("A refresh run is already queued for the external runner. Cancel it before starting a new run.")
    if state == "running" and queue_state in {"queued", "running"}:
        raise ValueError("A refresh run is already queued for the external runner. Cancel it before starting a new run.")


def _update_latest_state(*, state: str, exit_code: int | None = None, canceled_at: str | None = None) -> dict[str, Any]:
    context = _latest_refresh_manifest_context()
    manifest_path: Path = context["manifest_path"]
    manifest: dict[str, Any] = context["manifest"]
    run_summary_path: Path | None = context["run_summary_path"]
    manifest["state"] = state
    if exit_code is not None:
        manifest["exitCode"] = int(exit_code)
    if canceled_at:
        manifest["canceledAt"] = canceled_at
        manifest["finishedAt"] = canceled_at
    write_json_file(manifest_path, manifest)
    if run_summary_path is not None:
        run_summary = read_json_file(run_summary_path) or {}
        run_summary["state"] = state
        if exit_code is not None:
            run_summary["exitCode"] = int(exit_code)
        if canceled_at:
            run_summary["canceledAt"] = canceled_at
            run_summary["finishedAt"] = canceled_at
        write_json_file(run_summary_path, run_summary)
    return manifest


def cancel_latest_refresh_run() -> dict[str, Any]:
    context = _latest_refresh_manifest_context()
    manifest: dict[str, Any] = context["manifest"]
    manifest_state = str(manifest.get("state") or "").strip().lower()
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if pid is None and manifest_state == "pending_external":
        updated = _update_latest_state(state="canceled", exit_code=0, canceled_at=_utc_now())
        return {"ok": True, "pid": None, "state": updated.get("state"), "detail": "Queued external refresh run canceled."}
    if pid is None:
        raise ValueError("No running refresh PID is recorded in the latest manifest.")
    if not _pid_is_running(pid):
        updated = _update_latest_state(state="failed", canceled_at=_utc_now())
        return {"ok": False, "pid": pid, "state": updated.get("state"), "detail": "Recorded PID is not running."}

    canceled = False
    stderr_text = ""
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
        stderr_text = (result.stderr or "").strip()
        canceled = result.returncode == 0 and not _pid_is_running(pid)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            stderr_text = str(exc)

        if _pid_is_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError as exc:
                if not stderr_text:
                    stderr_text = str(exc)

        deadline = time.time() + 2.0
        while _pid_is_running(pid) and time.time() < deadline:
            time.sleep(0.1)
        canceled = not _pid_is_running(pid)
        if canceled:
            stderr_text = ""

    if not canceled and not stderr_text:
        stderr_text = "Refresh process is still running after cancel attempt."

    new_state = "canceled" if canceled else "failed"
    updated = _update_latest_state(state=new_state, exit_code=0 if canceled else 1, canceled_at=_utc_now())
    return {
        "ok": canceled,
        "pid": pid,
        "state": updated.get("state"),
        "detail": "Refresh run canceled." if canceled else (stderr_text or "Unable to cancel refresh run."),
    }


def load_latest_refresh_log(*, stream: str = "stderr") -> dict[str, Any]:
    stream_key = str(stream or "stderr").strip().lower()
    if stream_key not in {"stdout", "stderr"}:
        raise ValueError("stream must be 'stdout' or 'stderr'.")
    context = _latest_refresh_manifest_context()
    manifest: dict[str, Any] = context["manifest"]
    artifacts_dir: Path | None = context["artifacts_dir"]
    if artifacts_dir is None:
        raise ValueError("No latest refresh artifacts directory is available.")
    path = artifacts_dir / ("odds_refresh.json" if stream_key == "stdout" else "odds_refresh.stderr.txt")
    content = read_text_file(path) or ""
    lines = content.splitlines()
    tail = "\n".join(lines[-80:]) if lines else ""
    return {
        "stream": stream_key,
        "path": str(path),
        "exists": path_exists(path),
        "size": path_size(path),
        "content": content,
        "tail": tail,
        "run_stamp": manifest.get("runStamp"),
        "date": manifest.get("date"),
    }


@lru_cache(maxsize=1)
def _refresh_script_module() -> Any:
    script_path = REPO_ROOT / "scripts" / "refresh_odds_sources.py"
    spec = importlib.util.spec_from_file_location("syndicate_refresh_odds_sources", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load refresh script from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_refresh_plan(
    *,
    date: str | None = None,
    sports: str | None = None,
    phase: str | None = None,
    regions: str | None = None,
    bookmakers: str | None = None,
    markets: str | None = None,
    season: int | None = None,
    week: int | None = None,
    skip_mirror: bool = False,
    mirror_only: bool = False,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    module = _refresh_script_module()
    effective_skip_mirror = _effective_skip_mirror(skip_mirror=bool(skip_mirror), mirror_only=bool(mirror_only))
    args = argparse.Namespace(
        date=(date or _today_date()),
        sports=(sports or "all"),
        phase=(phase or "all"),
        regions=(regions or "us"),
        bookmakers=(bookmakers or ""),
        markets=(markets or ""),
        season=season,
        week=week,
        skip_mirror=bool(effective_skip_mirror),
        mirror_only=bool(mirror_only),
        execution_mode=str(execution_mode or "source").strip() or "source",
        continue_on_error=True,
        dry_run=True,
        json=True,
        list=False,
    )
    summary = module._build_summary(args)
    return summary if isinstance(summary, dict) else {"ok": False, "error": "Unable to build refresh plan."}


def load_latest_refresh_status() -> dict[str, Any]:
    current_reports_root = _reports_root()
    refresh_latest_dir = current_reports_root / "refresh_status" / "latest"
    refresh_manifest_path = refresh_latest_dir / "refresh_status_latest.json"
    refresh_manifest = read_json_file(refresh_manifest_path)

    refresh_artifacts: dict[str, Any] = {}
    artifacts_dir_raw = str((refresh_manifest or {}).get("artifactsDir") or "").strip()
    if artifacts_dir_raw:
        artifacts_dir = Path(artifacts_dir_raw)
        artifact_specs = {
            "refresh_and_gate_run": (artifacts_dir / "refresh_and_gate_run.json", "json"),
            "odds_refresh": (artifacts_dir / "odds_refresh.json", "json"),
            "odds_refresh_stderr": (artifacts_dir / "odds_refresh.stderr.txt", "text"),
            "migration_gate_report": (artifacts_dir / "migration_gate_report.json", "json"),
            "migration_gate_console": (artifacts_dir / "migration_gate_console.txt", "text"),
        }
        for key, (path, kind) in artifact_specs.items():
            payload: Any = read_json_file(path) if kind == "json" else read_text_file(path)
            refresh_artifacts[key] = {
                "path": str(path),
                "exists": path_exists(path),
                "payload": payload,
            }
    worker_status_path = refresh_latest_dir / "refresh_worker_status.json"
    refresh_artifacts["refresh_worker_status"] = {
        "path": str(worker_status_path),
        "exists": path_exists(worker_status_path),
        "payload": read_json_file(worker_status_path),
    }
    queued_job_status_path = None
    if artifacts_dir_raw:
        queued_job_status_path = Path(artifacts_dir_raw) / "refresh_job_status.json"
        refresh_artifacts["refresh_job_status"] = {
            "path": str(queued_job_status_path),
            "exists": path_exists(queued_job_status_path),
            "payload": read_json_file(queued_job_status_path),
        }
    runtime_state = _derive_refresh_runtime_state(refresh_manifest, refresh_artifacts)

    daily_update_latest_dir = current_reports_root / "daily_update" / "latest"
    daily_update_manifest_candidates = [
        daily_update_latest_dir / "unified_daily_update_latest.json",
        daily_update_latest_dir / "daily_update_latest.json",
    ]
    daily_update_manifest_path = daily_update_manifest_candidates[0]
    daily_update_manifest = None
    for candidate in daily_update_manifest_candidates:
        candidate_payload = read_json_file(candidate)
        if isinstance(candidate_payload, dict):
            daily_update_manifest_path = candidate
            daily_update_manifest = candidate_payload
            break

    daily_update_checkpoint_path = daily_update_latest_dir / "unified_daily_update_latest_checkpoint.json"
    daily_update_checkpoint = read_json_file(daily_update_checkpoint_path)
    daily_update_run_state_path = daily_update_latest_dir / "unified_daily_update_latest_run_state.json"
    daily_update_run_state = read_json_file(daily_update_run_state_path)
    daily_update_trace_path = daily_update_latest_dir / "unified_daily_update_latest_run_trace.json"
    daily_update_trace = read_json_file(daily_update_trace_path)
    daily_update_runtime = {
        "elapsed_seconds": _elapsed_seconds(
            started_at=(daily_update_manifest or {}).get("generatedAt"),
            finished_at=(daily_update_manifest or {}).get("completedAt"),
        ),
        "runtime_budget_seconds": _runtime_budget_seconds("SYNDICATE_DAILY_UPDATE_RUNTIME_BUDGET_SECONDS"),
        "started_at": (daily_update_manifest or {}).get("generatedAt"),
        "finished_at": (daily_update_manifest or {}).get("completedAt"),
    }
    daily_update_runtime["remaining_budget_seconds"] = _remaining_budget_seconds(
        elapsed_seconds=daily_update_runtime.get("elapsed_seconds"),
        budget_seconds=daily_update_runtime.get("runtime_budget_seconds"),
    )

    return {
        "reports_root": str(current_reports_root),
        "refresh_status": {
            "manifest_path": str(refresh_manifest_path),
            "manifest_exists": path_exists(refresh_manifest_path),
            "manifest": refresh_manifest,
            "artifacts": refresh_artifacts,
            "mirror_manifests": _load_mirror_manifest_summaries_from_current_data_root(),
            "runtime": runtime_state,
            "history": _load_recent_refresh_history(),
        },
        "daily_update": {
            "manifest_path": str(daily_update_manifest_path),
            "manifest_exists": path_exists(daily_update_manifest_path),
            "manifest": daily_update_manifest,
            "runtime": daily_update_runtime,
            "checkpoint_path": str(daily_update_checkpoint_path),
            "checkpoint_exists": path_exists(daily_update_checkpoint_path),
            "checkpoint": daily_update_checkpoint,
            "run_state_path": str(daily_update_run_state_path),
            "run_state_exists": path_exists(daily_update_run_state_path),
            "run_state": daily_update_run_state,
            "trace_path": str(daily_update_trace_path),
            "trace_exists": path_exists(daily_update_trace_path),
            "trace": daily_update_trace,
        },
    }


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _coerce_slug_list(raw: str | None) -> str:
    text = str(raw or "all").strip()
    return text or "all"


def _active_sports_for_date(date_str: str) -> str:
    """Return a comma-separated list of sports whose season overlaps *date_str*.

    Season windows mirror those in scripts/daily_update_in_season.ps1.
    """
    try:
        from datetime import date as _date
        d = _date.fromisoformat(date_str)
        month, day = d.month, d.day
    except Exception:
        return "all"

    active: list[str] = []
    # MLB: March – October
    if 3 <= month <= 10:
        active.append("mlb")
    # NBA: October – June
    if month >= 10 or month <= 6:
        active.append("nba")
    # NHL: October – June
    if month >= 10 or month <= 6:
        active.append("nhl")
    # WNBA: May – October
    if 5 <= month <= 10:
        active.append("wnba")
    # NFL: August – February
    if month >= 8 or month <= 2:
        active.append("nfl")
    # NCAAF: Aug 15 – Dec, January
    if (month == 8 and day >= 15) or (9 <= month <= 12) or month == 1:
        active.append("ncaaf")
    # NCAAB: November – April
    if month >= 11 or month <= 4:
        active.append("ncaab")

    return ",".join(active) if active else "all"


def _effective_skip_mirror(*, skip_mirror: bool, mirror_only: bool) -> bool:
    if mirror_only:
        return False
    return bool(skip_mirror)


def launch_refresh_run(
    *,
    date: str | None = None,
    sports: str | None = None,
    phase: str | None = None,
    mode: str | None = "fast",
    regions: str | None = None,
    bookmakers: str | None = None,
    markets: str | None = None,
    season: int | None = None,
    week: int | None = None,
    skip_mirror: bool = False,
    mirror_only: bool = False,
    execution_mode: str | None = None,
    dry_run: bool = False,
    launch_mode: str | None = None,
) -> dict[str, Any]:
    _assert_no_active_refresh_run()
    selected_date = date or _today_date()
    effective_skip_mirror = _effective_skip_mirror(skip_mirror=bool(skip_mirror), mirror_only=bool(mirror_only))
    # Default to in-season sports for the target date rather than running all sports.
    effective_sports = _coerce_slug_list(sports) if sports else _active_sports_for_date(selected_date)
    run_stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    launch_mode = _resolve_launch_mode(launch_mode)
    current_reports_root = _reports_root()
    refresh_status_root = current_reports_root / "refresh_status"
    refresh_status_run_dir = refresh_status_root / selected_date / run_stamp
    refresh_status_latest_dir = refresh_status_root / "latest"
    artifacts_dir = current_reports_root / "migration_runs" / selected_date / f"odds_refresh_{run_stamp}"

    refresh_status_run_dir.mkdir(parents=True, exist_ok=True)
    refresh_status_latest_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    odds_refresh_path = artifacts_dir / "odds_refresh.json"
    odds_refresh_stderr_path = artifacts_dir / "odds_refresh.stderr.txt"
    refresh_and_gate_run_path = artifacts_dir / "refresh_and_gate_run.json"
    refresh_status_manifest_path = refresh_status_run_dir / "refresh_status_manifest.json"
    refresh_status_latest_path = refresh_status_latest_dir / "refresh_status_latest.json"

    refresh_command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "refresh_odds_sources.py"),
        "--date",
        selected_date,
        "--sports",
        effective_sports,
        "--phase",
        str(phase or "all").strip() or "all",
        "--regions",
        str(regions or "us").strip() or "us",
        "--json",
    ]
    bookmakers_text = str(bookmakers or "").strip()
    markets_text = str(markets or "").strip()
    if bookmakers_text:
        refresh_command.extend(["--bookmakers", bookmakers_text])
    if markets_text:
        refresh_command.extend(["--markets", markets_text])
    refresh_mode = str(mode or "fast").strip().lower() or "fast"
    refresh_command.extend(["--mode", refresh_mode])
    if season is not None:
        refresh_command.extend(["--season", str(season)])
    if week is not None:
        refresh_command.extend(["--week", str(week)])
    execution_mode_text = str(execution_mode or "source").strip() or "source"
    refresh_command.extend(["--execution-mode", execution_mode_text])
    if effective_skip_mirror:
        refresh_command.append("--skip-mirror")
    if mirror_only:
        refresh_command.append("--mirror-only")
    if dry_run:
        refresh_command.append("--dry-run")

    external_runner = _external_runner_payload(
        selected_date=selected_date,
        run_stamp=run_stamp,
        refresh_status_manifest_path=refresh_status_manifest_path,
        refresh_status_latest_path=refresh_status_latest_path,
        refresh_and_gate_run_path=refresh_and_gate_run_path,
        odds_refresh_path=odds_refresh_path,
        odds_refresh_stderr_path=odds_refresh_stderr_path,
        refresh_command=refresh_command,
    )

    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_refresh_odds_job.py"),
        "--manifest-path",
        str(refresh_status_manifest_path),
        "--latest-path",
        str(refresh_status_latest_path),
        "--run-summary-path",
        str(refresh_and_gate_run_path),
        "--stdout-path",
        str(odds_refresh_path),
        "--stderr-path",
        str(odds_refresh_stderr_path),
        "--",
        *refresh_command,
    ]

    run_summary = {
        "date": selected_date,
        "runStamp": run_stamp,
        "artifactsDir": str(artifacts_dir),
        "refreshStatusDir": str(refresh_status_run_dir),
        "jsonMode": True,
        "refreshOdds": True,
        "oddsPhase": str(phase or "all").strip() or "all",
        "oddsSports": effective_sports,
        "oddsRegions": str(regions or "us").strip() or "us",
        "skipMirror": bool(effective_skip_mirror),
        "mirrorOnly": bool(mirror_only),
        "executionMode": execution_mode_text,
        "launchMode": launch_mode,
        "launchOwner": "external_runner" if _is_external_runner_mode(launch_mode) else "web_process",
        "dryRun": bool(dry_run),
        "state": "pending_external" if _is_external_runner_mode(launch_mode) else "running",
        "generatedAt": _utc_now(),
        "command": refresh_command,
        "launcherCommand": command,
        "oddsRefreshPath": str(odds_refresh_path),
        "oddsRefreshStderrPath": str(odds_refresh_stderr_path),
        "externalRunner": external_runner,
    }
    write_json_file(refresh_and_gate_run_path, run_summary)

    refresh_status_manifest = {
        "date": selected_date,
        "runStamp": run_stamp,
        "generatedAt": _utc_now(),
        "artifactsDir": str(artifacts_dir),
        "refreshStatusDir": str(refresh_status_run_dir),
        "latestManifestPath": str(refresh_status_latest_path),
        "refreshOdds": True,
        "oddsPhase": str(phase or "all").strip() or "all",
        "oddsSports": effective_sports,
        "oddsRegions": str(regions or "us").strip() or "us",
        "runSummaryPath": str(refresh_and_gate_run_path),
        "oddsRefreshPath": str(odds_refresh_path),
        "migrationGateReportPath": str(artifacts_dir / "migration_gate_report.json"),
        "migrationGateConsolePath": str(artifacts_dir / "migration_gate_console.txt"),
        "executionMode": execution_mode_text,
        "launchMode": launch_mode,
        "launchOwner": "external_runner" if _is_external_runner_mode(launch_mode) else "web_process",
        "dryRun": bool(dry_run),
        "state": "pending_external" if _is_external_runner_mode(launch_mode) else "running",
        "externalRunner": external_runner,
    }
    write_json_file(refresh_status_manifest_path, refresh_status_manifest)
    write_json_file(refresh_status_latest_path, refresh_status_manifest)

    if _is_external_runner_mode(launch_mode):
        return {
            "ok": True,
            "pid": None,
            "date": selected_date,
            "run_stamp": run_stamp,
            "artifacts_dir": str(artifacts_dir),
            "refresh_status_dir": str(refresh_status_run_dir),
            "command": command,
            "dry_run": bool(dry_run),
            "skip_mirror": bool(effective_skip_mirror),
            "mirror_only": bool(mirror_only),
            "launch_mode": launch_mode,
            "launch_owner": "external_runner",
            "external_runner": external_runner,
            "state": "pending_external",
        }

    popen_kwargs: dict[str, Any] = {
        "cwd": str(REPO_ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **popen_kwargs)

    refresh_status_manifest["pid"] = int(process.pid)
    write_json_file(refresh_status_manifest_path, refresh_status_manifest)
    write_json_file(refresh_status_latest_path, refresh_status_manifest)

    run_summary["pid"] = int(process.pid)
    write_json_file(refresh_and_gate_run_path, run_summary)

    return {
        "ok": True,
        "pid": int(process.pid),
        "date": selected_date,
        "run_stamp": run_stamp,
        "artifacts_dir": str(artifacts_dir),
        "refresh_status_dir": str(refresh_status_run_dir),
        "command": command,
        "dry_run": bool(dry_run),
        "skip_mirror": bool(effective_skip_mirror),
        "mirror_only": bool(mirror_only),
        "launch_mode": launch_mode,
        "launch_owner": "web_process",
        "state": "running",
    }