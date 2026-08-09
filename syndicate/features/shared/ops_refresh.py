"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Builds and tracks refresh plans, runtime state, and launch metadata.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

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
from syndicate.features.shared.refresh_state_store import known_refresh_lanes
from syndicate.features.shared.refresh_state_store import record_known_refresh_lane
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import path_exists
from syndicate.features.shared.refresh_state_store import path_size
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import read_json_file_result
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
    refresh_cycle = None
    refresh_worker_status = artifacts.get("refresh_worker_status") if isinstance(artifacts.get("refresh_worker_status"), dict) else {}
    refresh_worker_payload = refresh_worker_status.get("payload") if isinstance(refresh_worker_status, dict) else None
    if isinstance(refresh_worker_payload, dict) and isinstance(refresh_worker_payload.get("refreshCycle"), dict):
        refresh_cycle = refresh_worker_payload.get("refreshCycle")

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
        "refresh_cycle": refresh_cycle,
    }


def _normalize_failure_message(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("message", "error", "detail", "warning"):
            text = _normalize_failure_message(value.get(key))
            if text:
                return text
        try:
            text = json.dumps(value, sort_keys=True, ensure_ascii=True)
        except Exception:
            text = str(value)
        text = str(text).strip()
        return text or None
    if isinstance(value, (list, tuple, set)):
        parts = [item for item in (_normalize_failure_message(item) for item in value) if item]
        return "; ".join(parts) or None
    text = str(value).strip()
    return text or None


def _extend_unique(target: list[str], values: Any) -> None:
    if values is None:
        return
    items = values if isinstance(values, (list, tuple, set)) else [values]
    for item in items:
        text = _normalize_failure_message(item)
        if text and text not in target:
            target.append(text)


def _refresh_artifact_failure_lists(refresh_payload: dict[str, Any] | None) -> tuple[list[str], list[str], dict[str, Any] | None]:
    required_failures: list[str] = []
    optional_failures: list[str] = []
    refresh_contract: dict[str, Any] | None = None
    if not isinstance(refresh_payload, dict):
        return required_failures, optional_failures, refresh_contract

    results = refresh_payload.get("results") if isinstance(refresh_payload.get("results"), list) else []
    for result in results:
        if not isinstance(result, dict):
            continue
        _extend_unique(required_failures, result.get("required_artifact_failures"))
        _extend_unique(optional_failures, result.get("optional_artifact_failures"))

        if not result.get("ok"):
            fallback_failure = _normalize_failure_message(result.get("error")) or _normalize_failure_message(result.get("detail"))
            if fallback_failure and fallback_failure not in required_failures:
                required_failures.append(fallback_failure)
            elif not fallback_failure:
                sport_name = str(result.get("sport") or "sport").strip() or "sport"
                required_failures.append(f"{sport_name} required artifact failure")

        _extend_unique(optional_failures, result.get("warning"))
        _extend_unique(optional_failures, result.get("warnings"))

        sport_manifest = result.get("sport_manifest") if isinstance(result.get("sport_manifest"), dict) else None
        metadata = (sport_manifest or {}).get("payload", {}).get("metadata") if isinstance((sport_manifest or {}).get("payload"), dict) else None
        if refresh_contract is None and isinstance(metadata, dict) and isinstance(metadata.get("refresh_contract"), dict):
            refresh_contract = dict(metadata.get("refresh_contract"))

    return required_failures, optional_failures, refresh_contract


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
                "lane": manifest.get("lane"),
            }
        )
        if len(history) >= limit:
            return history
    return history


def _latest_refresh_manifest_context(lane: str | None = None) -> dict[str, Any]:
    lane_key = _refresh_lane_key(lane)
    refresh_manifest_path = _reports_root() / "refresh_status" / "latest" / _refresh_manifest_filename(lane_key)
    manifest_raw, manifest_read_ok = read_json_file_result(refresh_manifest_path)
    manifest = manifest_raw if isinstance(manifest_raw, dict) else {}
    artifacts_dir_raw = str(manifest.get("artifactsDir") or "").strip()
    artifacts_dir = Path(artifacts_dir_raw) if artifacts_dir_raw else None
    run_summary_path = Path(str(manifest.get("runSummaryPath") or "").strip()) if str(manifest.get("runSummaryPath") or "").strip() else None
    run_summary = None
    if run_summary_path is None and artifacts_dir is not None:
        run_summary_path = artifacts_dir / "refresh_and_gate_run.json"
    if run_summary_path is not None:
        run_summary = read_json_file(run_summary_path) or {}
    consistency_error = None
    if isinstance(manifest, dict) and run_summary_path is not None:
        manifest_stamp = str(manifest.get("runStamp") or "").strip()
        run_summary_stamp = str(run_summary.get("runStamp") or "").strip() if isinstance(run_summary, dict) else ""
        if manifest_stamp and run_summary_stamp and manifest_stamp != run_summary_stamp:
            consistency_error = (
                "Inconsistent latest refresh artifacts: "
                f"manifest runStamp {manifest_stamp} does not match run summary runStamp {run_summary_stamp}."
            )
    return {
        "lane": lane_key,
        "manifest_path": refresh_manifest_path,
        "manifest": manifest,
        "manifest_read_ok": manifest_read_ok,
        "artifacts_dir": artifacts_dir,
        "run_summary_path": run_summary_path,
        "run_summary": run_summary,
        "consistency_error": consistency_error,
    }


def _latest_sport_refresh_log_path(*, manifest: dict[str, Any], sport: str) -> Path | None:
    sport_key = str(sport or "").strip().lower()
    if not sport_key:
        return None
    date_value = str(manifest.get("date") or "").strip()
    results = manifest.get("results") if isinstance(manifest.get("results"), list) else []
    source_repo = None
    for result in results:
        if not isinstance(result, dict):
            continue
        if str(result.get("sport") or "").strip().lower() != sport_key:
            continue
        source_repo = str(result.get("source_repo") or "").strip()
        if source_repo:
            break
    if not source_repo or not date_value:
        return None
    return Path(source_repo) / "logs" / f"syndicate_refresh_oddsapi_props_{date_value}.log"


def _ensure_refresh_context_consistent(context: dict[str, Any]) -> None:
    consistency_error = str(context.get("consistency_error") or "").strip()
    if consistency_error:
        raise ValueError(consistency_error)


def _this_service_identity() -> str:
    return str(os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE_NAME") or "").strip()


def _this_instance_identity() -> str:
    # RENDER_SERVICE_ID/NAME are stable across a redeploy (same service,
    # fresh container) -- RENDER_INSTANCE_ID changes every time. Found via a
    # real production bug: after a redeploy, a stale "running" manifest from
    # the previous container generation still matched on service identity,
    # so _refresh_run_still_active fell into the same-service pid-liveness
    # branch and checked a pid number that could easily be reoccupied by an
    # unrelated process in the fresh container, blocking the next launch.
    return str(os.environ.get("RENDER_INSTANCE_ID") or "").strip()


_LEGACY_REFRESH_LANE_KEY = "global"
_REFRESH_WORKER_LANE_KEY = "refresh-worker"

# A manifest that has already self-reported one of these is done, for good,
# from the job's own authority -- see _assert_no_active_refresh_run's use of
# this below.
_TERMINAL_REFRESH_STATES = frozenset({"finished", "failed", "canceled"})


def _per_service_refresh_lanes_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _refresh_lane_key(explicit_lane: str | None = None) -> str:
    # Root cause of the soccer/WNBA starvation bug: _assert_no_active_refresh_run
    # used to enforce ONE mutex shared across all 3 Render services (web,
    # refresh-worker, live-odds-worker), even though only same-container runs
    # pose any real OOM risk. refresh-worker's frequent MLB-only autorun kept
    # winning that global mutex, starving out live-odds-worker's own tick --
    # the only path that ever refreshes WNBA/soccer/everything else. Each
    # service now gets its own independent manifest ("lane") instead.
    #
    # Defaults OFF (SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES unset/false) so
    # this is a zero-behavior-change merge -- every caller collapses onto the
    # same legacy single manifest path until the flag is flipped.
    if not _per_service_refresh_lanes_enabled():
        return _LEGACY_REFRESH_LANE_KEY
    if explicit_lane:
        return str(explicit_lane).strip() or _LEGACY_REFRESH_LANE_KEY
    # SYNDICATE_REFRESH_LANE is a stable, human-readable override (set per
    # service in render.yaml) preferred over the opaque RENDER_SERVICE_ID/NAME
    # fallback -- it lets code hardcode a known lane name (e.g. the
    # external-runner queue below, which always belongs to refresh-worker
    # regardless of which service actually calls launch_refresh_run).
    configured = str(os.environ.get("SYNDICATE_REFRESH_LANE") or "").strip()
    if configured:
        return configured
    identity = _this_service_identity()
    return identity or "local"


def _refresh_manifest_filename(lane_key: str) -> str:
    if lane_key == _LEGACY_REFRESH_LANE_KEY:
        return "refresh_status_latest.json"
    return f"refresh_status_latest__{lane_key}.json"


def list_latest_refresh_manifests_by_lane() -> dict[str, dict[str, Any]]:
    latest_dir = _reports_root() / "refresh_status" / "latest"
    result: dict[str, dict[str, Any]] = {}
    lane_keys: set[str] = {_LEGACY_REFRESH_LANE_KEY, *known_refresh_lanes()}
    # known_refresh_lanes() is only populated on the keyvalue backend (an
    # explicit Redis-backed index, mirroring _history_index_key()'s existing
    # pattern) -- a raw filesystem glob can't discover lanes written by a
    # DIFFERENT service, since each service has its own separate persistent
    # disk and "latest" manifest files aren't necessarily materialized
    # locally at all under that backend. The glob below still covers local
    # dev/tests (filesystem backend), where every lane's file genuinely does
    # live on the one shared disk being read.
    if latest_dir.exists():
        for path in sorted(latest_dir.glob("refresh_status_latest*.json")):
            prefix = "refresh_status_latest__"
            if path.stem == "refresh_status_latest":
                lane_keys.add(_LEGACY_REFRESH_LANE_KEY)
            elif path.stem.startswith(prefix):
                lane_keys.add(path.stem[len(prefix):])
    for lane_key in lane_keys:
        manifest_path = latest_dir / _refresh_manifest_filename(lane_key)
        manifest = read_json_file(manifest_path)
        if isinstance(manifest, dict) and manifest:
            result[lane_key] = manifest
    return result


def _refresh_run_max_runtime_seconds() -> int:
    # Cross-service pointers can't be verified via OS pid liveness (separate
    # container, separate PID namespace), so a genuinely stuck/crashed
    # cross-service run needs a time-based escape hatch instead. Refresh runs
    # (even a busy live-phase slate with WNBA's forced props refresh) finish
    # in low single-digit minutes; 20 minutes is a generous ceiling that
    # still bounds how long a dead pointer from another service can block
    # new launches.
    raw = str(os.environ.get("SYNDICATE_REFRESH_RUN_MAX_RUNTIME_SECONDS") or "").strip()
    try:
        value = int(raw or 1200)
    except Exception:
        value = 1200
    return max(60, value)


def _process_cmdline(pid: int) -> list[str] | None:
    if os.name == "nt":
        return None
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except Exception:
        return None
    parts = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
    return parts or None


def _process_matches_expected_command(pid: int, expected_command: Any) -> bool:
    # Guards against PID reuse within the SAME container: a dead refresh
    # run's pid can be reassigned to an unrelated process, which would make
    # a stale pointer look perpetually held via liveness alone.
    current = _process_cmdline(pid)
    if current is None:
        # Can't verify (Windows, /proc unavailable, process just exited) --
        # fall back to trusting the liveness check alone.
        return True
    expected = expected_command if isinstance(expected_command, list) else []
    if not expected:
        return True
    return [str(part) for part in current] == [str(part) for part in expected]


def _refresh_run_still_active(manifest: dict[str, Any], *, run_summary: dict[str, Any] | None = None) -> bool:
    # A raw OS pid check is meaningless when the recorded launch happened in
    # a DIFFERENT Render service's container -- live-odds-worker's tick,
    # refresh-worker's autoruns, and ops.py's/intelligence.py's HTTP-triggered
    # launches can all call launch_refresh_run, each in its own container
    # with its own PID namespace, so a pid from one almost always reads "not
    # running" when checked from another, even while genuinely alive
    # elsewhere. Unlike the MLB-sim pointer's advisory check (safe to
    # default open -- a false negative there just costs an extra doomed
    # subprocess), this guard is a real mutex: ambiguity must default to
    # "still active" (fail closed), the opposite default.
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if pid is None:
        return False

    launcher_service_id = str(manifest.get("launcherServiceId") or "").strip()
    this_service_id = _this_service_identity()
    identity_known = bool(launcher_service_id) and bool(this_service_id)
    same_service = identity_known and launcher_service_id == this_service_id

    if identity_known and not same_service:
        generated_at = str(manifest.get("generatedAt") or "").strip()
        try:
            generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00")) if generated_at else None
        except Exception:
            generated_dt = None
        if generated_dt is None:
            # Can't determine the age of a cross-service pointer -- fail closed.
            return True
        age_seconds = (datetime.now(timezone.utc) - generated_dt).total_seconds()
        return age_seconds < _refresh_run_max_runtime_seconds()

    if same_service:
        # RENDER_SERVICE_ID stays the SAME across a redeploy (fresh
        # container, same service) -- RENDER_INSTANCE_ID does not. A pointer
        # recorded by a previous instance can never still be running here:
        # its whole process tree is gone. Checking pid liveness/cmdline
        # instead (as the code below does) is unsafe in this specific case --
        # low pid numbers get reoccupied fast in a fresh container, and
        # _process_matches_expected_command fails OPEN (assumes a match) when
        # the command can't be read, so a coincidentally-alive pid at the
        # same number silently looked like the original run in production.
        launcher_instance_id = str(manifest.get("launcherInstanceId") or "").strip()
        this_instance_id = _this_instance_identity()
        if launcher_instance_id and this_instance_id and launcher_instance_id != this_instance_id:
            return False

    # Same service and instance (or identity unknown, e.g. local dev without
    # RENDER_SERVICE_ID) -- a real, verifiable liveness check is possible.
    if not _pid_is_running(pid):
        return False
    # launcherCommand (not command) is what was actually Popen'd under this
    # pid -- command is the refresh_odds_sources.py invocation the wrapper
    # spawns as its OWN child, a different, untracked pid.
    expected_command = (run_summary or {}).get("launcherCommand") if isinstance(run_summary, dict) else None
    return _process_matches_expected_command(pid, expected_command)


def _assert_refresh_manifest_read_ok(context: dict[str, Any]) -> None:
    # A failed read (transient keyvalue-backend error, malformed JSON) must
    # never be treated the same as "no run recorded" -- that fail-open
    # behavior let overlapping refresh_odds_sources.py launches slip past
    # this guard in production, stacking process trees until the container
    # OOMed. Refuse to launch rather than guess when we can't confirm state.
    if context.get("manifest_read_ok") is False:
        raise ValueError("Cannot confirm refresh-run state (manifest read failed) -- refusing to launch a new run until state is confirmed.")


def _assert_no_active_refresh_run(lane: str | None = None) -> None:
    context = _latest_refresh_manifest_context(lane)
    _assert_refresh_manifest_read_ok(context)
    _ensure_refresh_context_consistent(context)
    manifest: dict[str, Any] = context["manifest"] if isinstance(context.get("manifest"), dict) else {}
    run_summary: dict[str, Any] = context["run_summary"] if isinstance(context.get("run_summary"), dict) else {}
    state = str(manifest.get("state") or "").strip().lower()
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if state == "running" and not _refresh_run_still_active(manifest, run_summary=run_summary):
        _update_latest_state(state="failed", exit_code=1, finished_at=_utc_now(), lane=lane)
        context = _latest_refresh_manifest_context(lane)
        _assert_refresh_manifest_read_ok(context)
        manifest = context["manifest"] if isinstance(context.get("manifest"), dict) else {}
        run_summary = context["run_summary"] if isinstance(context.get("run_summary"), dict) else {}
        state = str(manifest.get("state") or "").strip().lower()
        pid_raw = manifest.get("pid")
        pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    # Confirmed live 2026-08-08: a refresh-worker manifest already reporting
    # `state: finished` (the job's own, authoritative word that it's done)
    # still blocked new launches, because run_refresh_odds_job.py's own
    # wrapper process (the "pid" recorded here) can remain alive for a while
    # after writing that state -- and _refresh_run_still_active only checks
    # OS pid liveness + command match, with no awareness that the manifest
    # it's reading already says done. A terminal state is written by the job
    # itself; a lingering OS process past that point (cleanup, a watchdog
    # thread, or a coincidentally-reused pid within the same container's
    # lifetime -- the risk _this_instance_identity()'s own docstring already
    # flags for the cross-redeploy case) is not evidence the refresh is
    # still running, so it must not override what the job already reported.
    if pid is not None and state not in _TERMINAL_REFRESH_STATES:
        try:
            if _refresh_run_still_active(manifest, run_summary=run_summary):
                raise ValueError(f"A refresh run is already active (pid={pid}). Cancel it before starting a new run.")
        except ValueError:
            raise
        except Exception:
            pass
    external_runner = manifest.get("externalRunner") if isinstance(manifest.get("externalRunner"), dict) else {}
    queue_state = str(external_runner.get("queue_state") or "").strip().lower()

    def _terminal_refresh_state() -> tuple[str | None, int | None, str | None]:
        run_summary_path = context.get("run_summary_path")
        if not isinstance(run_summary_path, Path):
            return None, None, None
        run_summary = read_json_file(run_summary_path) or {}
        if not isinstance(run_summary, dict):
            return None, None, None
        run_summary_state = str(run_summary.get("state") or "").strip().lower()
        if run_summary_state not in _TERMINAL_REFRESH_STATES:
            return None, None, None
        exit_code_raw = run_summary.get("exitCode")
        exit_code = int(exit_code_raw) if isinstance(exit_code_raw, int) or (isinstance(exit_code_raw, str) and str(exit_code_raw).strip().isdigit()) else None
        finished_at = str(run_summary.get("finishedAt") or "").strip() or _utc_now()
        return run_summary_state, exit_code, finished_at

    if state in {"pending_external", "running"} and queue_state in {"queued", "running"}:
        terminal_state, exit_code, finished_at = _terminal_refresh_state()
        if terminal_state is not None:
            _update_latest_state(state=terminal_state, exit_code=exit_code, finished_at=finished_at, lane=lane)
            context = _latest_refresh_manifest_context(lane)
            manifest = context["manifest"] if isinstance(context.get("manifest"), dict) else {}
            state = str(manifest.get("state") or "").strip().lower()
            external_runner = manifest.get("externalRunner") if isinstance(manifest.get("externalRunner"), dict) else {}
            queue_state = str(external_runner.get("queue_state") or "").strip().lower()

    if state == "pending_external":
        raise ValueError("A refresh run is already queued for the external runner. Cancel it before starting a new run.")
    if state == "running" and queue_state in {"queued", "running"}:
        raise ValueError("A refresh run is already queued for the external runner. Cancel it before starting a new run.")


def is_refresh_run_active(lane: str | None = None) -> bool:
    # Read-only check (no state mutation, unlike _assert_no_active_refresh_run):
    # is an odds-refresh run currently in flight? Used by the MLB daily-sim
    # gate to avoid stacking a second heavy pipeline (1000-sim run + the
    # daily_update_multi_profile HR/K-ladder/RFI target generation pass) on
    # top of an in-flight odds refresh -- which can itself spawn WNBA SmartSim
    # -- in the same worker container. Two independent peak-memory pipelines
    # running concurrently is the leading OOM hypothesis; false negatives here
    # just mean occasional stacking as before, so this stays conservative
    # rather than replicating the full stale-pid/external-runner reconciliation
    # logic above.
    #
    # lane defaults to this service's own lane (via _refresh_lane_key), which
    # is correct here without any special-casing: this is only ever called
    # from the MLB sim decision path, which itself only runs on whichever
    # service owns the MLB sim tick (refresh-worker today) -- so the default
    # already resolves to the right lane to check for same-container stacking.
    try:
        context = _latest_refresh_manifest_context(lane)
    except Exception:
        return False
    manifest = context.get("manifest") if isinstance(context, dict) else None
    if not isinstance(manifest, dict):
        return False
    if str(manifest.get("state") or "").strip().lower() != "running":
        return False
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if pid is None:
        return False
    try:
        return bool(_pid_is_running(pid))
    except Exception:
        return False


def _update_latest_state(*, state: str, exit_code: int | None = None, canceled_at: str | None = None, finished_at: str | None = None, lane: str | None = None) -> dict[str, Any]:
    context = _latest_refresh_manifest_context(lane)
    _ensure_refresh_context_consistent(context)
    manifest_path: Path = context["manifest_path"]
    manifest: dict[str, Any] = context["manifest"]
    run_summary_path: Path | None = context["run_summary_path"]
    if run_summary_path is not None:
        run_summary = read_json_file(run_summary_path) or {}
        run_summary["state"] = state
        if exit_code is not None:
            run_summary["exitCode"] = int(exit_code)
        if canceled_at:
            run_summary["canceledAt"] = canceled_at
            run_summary["finishedAt"] = canceled_at
        elif finished_at:
            run_summary["finishedAt"] = finished_at
        write_json_file(run_summary_path, run_summary)
    manifest["state"] = state
    if exit_code is not None:
        manifest["exitCode"] = int(exit_code)
    if canceled_at:
        manifest["canceledAt"] = canceled_at
        manifest["finishedAt"] = canceled_at
    elif finished_at:
        manifest["finishedAt"] = finished_at
    write_json_file(manifest_path, manifest)
    return manifest


def cancel_latest_refresh_run(lane: str | None = None) -> dict[str, Any]:
    context = _latest_refresh_manifest_context(lane)
    _ensure_refresh_context_consistent(context)
    manifest: dict[str, Any] = context["manifest"]
    manifest_state = str(manifest.get("state") or "").strip().lower()
    pid_raw = manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if pid is None and manifest_state == "pending_external":
        updated = _update_latest_state(state="canceled", exit_code=0, canceled_at=_utc_now(), lane=lane)
        return {"ok": True, "pid": None, "state": updated.get("state"), "detail": "Queued external refresh run canceled."}
    if pid is None:
        # A manifest in `running` with a QUEUED external contract and no PID is
        # exactly the condition `_has_pending_external_contract`
        # (run_refresh_worker.py:1311) re-claims on EVERY tick -- it spawns
        # another `run_queued_refresh_job.py` and nothing in that path bounds
        # concurrency or checks whether a prior claim is still alive.
        #
        # Refusing to cancel it is precisely backwards: there is no process to
        # kill *because* the run already died, and the stuck manifest is what
        # keeps respawning it. INCIDENT 2026-08-08: this state survived an OOM
        # kill and a clean reboot, and refresh-worker went 13 -> 35 processes in
        # three minutes with nobody triggering anything. `cancel` was the
        # natural tool and it raised `"No running refresh PID is recorded"` --
        # declining to act on the one manifest that needed it.
        contract = manifest.get("externalRunner") if isinstance(manifest.get("externalRunner"), dict) else {}
        queue_state = str(contract.get("queue_state") or "").strip().lower()
        if manifest_state == "running" and queue_state == "queued":
            updated = _update_latest_state(state="failed", exit_code=1, canceled_at=_utc_now(), lane=lane)
            return {
                "ok": True,
                "pid": None,
                "state": updated.get("state"),
                "detail": "Queued refresh contract had no live PID; manifest driven terminal so the worker stops re-claiming it.",
            }
        raise ValueError("No running refresh PID is recorded in the latest manifest.")
    if not _pid_is_running(pid):
        # Same defect, other branch: the state change was already correct, but
        # returning ok=False reported a successful terminalisation as a failure,
        # so a caller watching `ok` believed the runaway was still uncancelled.
        updated = _update_latest_state(state="failed", exit_code=1, canceled_at=_utc_now(), lane=lane)
        return {
            "ok": True,
            "pid": pid,
            "state": updated.get("state"),
            "detail": "Recorded PID is not running; manifest driven terminal.",
        }

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
    updated = _update_latest_state(state=new_state, exit_code=0 if canceled else 1, canceled_at=_utc_now(), lane=lane)
    return {
        "ok": canceled,
        "pid": pid,
        "state": updated.get("state"),
        "detail": "Refresh run canceled." if canceled else (stderr_text or "Unable to cancel refresh run."),
    }


def load_latest_refresh_log(*, stream: str = "stderr", lane: str | None = None) -> dict[str, Any]:
    stream_key = str(stream or "stderr").strip().lower()
    context = _latest_refresh_manifest_context(lane)
    _ensure_refresh_context_consistent(context)
    manifest: dict[str, Any] = context["manifest"]
    artifacts_dir: Path | None = context["artifacts_dir"]
    if stream_key in {"stdout", "stderr"}:
        if artifacts_dir is None:
            raise ValueError("No latest refresh artifacts directory is available.")
        path = artifacts_dir / ("odds_refresh.json" if stream_key == "stdout" else "odds_refresh.stderr.txt")
    elif stream_key in {"wnba", "wnba_log", "wnba-log"}:
        path = _latest_sport_refresh_log_path(manifest=manifest, sport="wnba")
        if path is None:
            raise ValueError("No latest WNBA refresh log is available.")
    else:
        raise ValueError("stream must be 'stdout', 'stderr', or 'wnba'.")
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
    force_refresh: bool = False,
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
        force_refresh=bool(force_refresh),
    )
    summary = module._build_summary(args)
    return summary if isinstance(summary, dict) else {"ok": False, "error": "Unable to build refresh plan."}


def _build_refresh_status_detail(*, refresh_latest_dir: Path, refresh_manifest_path: Path) -> dict[str, Any]:
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
    odds_refresh_payload = (refresh_artifacts.get("odds_refresh") or {}).get("payload") if isinstance(refresh_artifacts.get("odds_refresh"), dict) else None
    required_artifact_failures, optional_artifact_failures, refresh_contract = _refresh_artifact_failure_lists(odds_refresh_payload if isinstance(odds_refresh_payload, dict) else None)
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
    return {
        "manifest_path": str(refresh_manifest_path),
        "manifest_exists": path_exists(refresh_manifest_path),
        "manifest": refresh_manifest,
        "artifacts": refresh_artifacts,
        "required_artifact_failures": required_artifact_failures,
        "optional_artifact_failures": optional_artifact_failures,
        "refresh_contract": refresh_contract,
        "mirror_manifests": _load_mirror_manifest_summaries_from_current_data_root(),
        "runtime": runtime_state,
        "history": _load_recent_refresh_history(),
    }


def _most_recently_updated_lane(by_lane: dict[str, dict[str, Any]]) -> str | None:
    best_lane: str | None = None
    best_epoch = -1.0
    for lane_key, manifest in by_lane.items():
        generated_at = str((manifest or {}).get("generatedAt") or "").strip()
        if not generated_at:
            continue
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except Exception:
            continue
        epoch = parsed.timestamp()
        if epoch > best_epoch:
            best_epoch = epoch
            best_lane = lane_key
    return best_lane


def load_latest_refresh_status() -> dict[str, Any]:
    current_reports_root = _reports_root()
    refresh_latest_dir = current_reports_root / "refresh_status" / "latest"

    by_lane_manifests = list_latest_refresh_manifests_by_lane()
    primary_lane = _most_recently_updated_lane(by_lane_manifests) if by_lane_manifests else None
    primary_manifest_path = (
        refresh_latest_dir / _refresh_manifest_filename(primary_lane)
        if primary_lane is not None
        else refresh_latest_dir / "refresh_status_latest.json"
    )
    refresh_status_detail = _build_refresh_status_detail(refresh_latest_dir=refresh_latest_dir, refresh_manifest_path=primary_manifest_path)
    refresh_status_by_lane = {
        lane_key: _build_refresh_status_detail(
            refresh_latest_dir=refresh_latest_dir,
            refresh_manifest_path=refresh_latest_dir / _refresh_manifest_filename(lane_key),
        )
        for lane_key in by_lane_manifests
    }

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
    daily_update_simulation_contract_path = daily_update_latest_dir / "unified_daily_update_latest_simulation_contract.json"
    daily_update_simulation_contract = read_json_file(daily_update_simulation_contract_path)
    daily_update_market_summary = daily_update_simulation_contract.get("market_summary") if isinstance(daily_update_simulation_contract, dict) else None
    daily_update_market_summary_by_sport = daily_update_simulation_contract.get("market_summary_by_sport") if isinstance(daily_update_simulation_contract, dict) else None
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
        "refresh_status": refresh_status_detail,
        # Per-lane detail (populated once SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES
        # is enabled and each service has written its own manifest) -- additive,
        # existing consumers of "refresh_status" above keep working unchanged,
        # reading whichever lane was most recently updated.
        "refresh_status_by_lane": refresh_status_by_lane,
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
            "simulation_contract_path": str(daily_update_simulation_contract_path),
            "simulation_contract_exists": path_exists(daily_update_simulation_contract_path),
            "simulation_contract": daily_update_simulation_contract,
            "market_summary": daily_update_market_summary,
            "market_summary_by_sport": daily_update_market_summary_by_sport,
        },
    }


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _coerce_slug_list(raw: str | None) -> str:
    text = str(raw or "all").strip()
    return text or "all"


def _env_text(name: str) -> str | None:
    value = str(os.environ.get(name) or "").strip()
    return value or None


def _env_bool(name: str) -> bool | None:
    value = str(os.environ.get(name) or "").strip().lower()
    if not value:
        return None
    return value in {"1", "true", "yes", "on"}


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
    # Soccer: 10 leagues combined span the full calendar year (MLS runs
    # Feb-Dec, European leagues run Aug-May); always active.
    active.append("soccer")

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
    skip_mirror: bool | None = None,
    mirror_only: bool = False,
    execution_mode: str | None = None,
    dry_run: bool = False,
    launch_mode: str | None = None,
    force_refresh: bool = False,
    force_refresh_sports: str | None = None,
    wnba_only_matchups: str | None = None,
    lane: str | None = None,
    soccer_leagues: str | None = None,
    soccer_date: str | None = None,
) -> dict[str, Any]:
    launch_mode = _resolve_launch_mode(launch_mode)
    # The queued/external-runner path is always claimed and executed by
    # refresh-worker's own poll loop (scripts/run_refresh_worker.py), regardless
    # of which service's process actually calls launch_refresh_run to enqueue
    # it -- so it must always resolve to refresh-worker's lane specifically,
    # not the calling service's own lane, or refresh-worker would never find
    # what it queued.
    effective_lane = _refresh_lane_key(_REFRESH_WORKER_LANE_KEY if _is_external_runner_mode(launch_mode) else lane)
    record_known_refresh_lane(effective_lane)
    _assert_no_active_refresh_run(lane=effective_lane)
    selected_date = date or _today_date()
    skip_mirror_value = _env_bool("SYNDICATE_LIVE_ODDS_REFRESH_SKIP_MIRROR") if skip_mirror is None else bool(skip_mirror)
    effective_skip_mirror = _effective_skip_mirror(skip_mirror=bool(skip_mirror_value), mirror_only=bool(mirror_only))
    # Default to in-season sports for the target date rather than running all sports.
    effective_sports = _coerce_slug_list(sports) if sports else _active_sports_for_date(selected_date)
    run_stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
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
    refresh_status_latest_path = refresh_status_latest_dir / _refresh_manifest_filename(effective_lane)

    refresh_mode = str(mode or _env_text("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "fast").strip().lower() or "fast"
    phase_text = str(phase or _env_text("SYNDICATE_LIVE_ODDS_REFRESH_PHASE") or "all").strip() or "all"
    regions_text = str(regions or _env_text("SYNDICATE_LIVE_ODDS_REFRESH_REGIONS") or "us").strip() or "us"
    execution_mode_text = str(execution_mode or _env_text("SYNDICATE_LIVE_ODDS_REFRESH_EXECUTION_MODE") or "source").strip() or "source"

    refresh_command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "refresh_odds_sources.py"),
        "--date",
        selected_date,
        "--sports",
        effective_sports,
        "--phase",
        phase_text,
        "--regions",
        regions_text,
        "--json",
    ]
    bookmakers_text = str(bookmakers or "").strip()
    markets_text = str(markets or "").strip()
    if bookmakers_text:
        refresh_command.extend(["--bookmakers", bookmakers_text])
    if markets_text:
        refresh_command.extend(["--markets", markets_text])
    refresh_command.extend(["--mode", refresh_mode])
    if bool(force_refresh):
        refresh_command.append("--force-refresh")
        force_refresh_sports_text = str(force_refresh_sports or "").strip()
        if force_refresh_sports_text:
            # Scopes --force-refresh to just the sport(s) that actually need
            # it (e.g. an NBA-only injury change) instead of every sport in
            # this launch's --sports list -- an unscoped force-refresh was
            # forcing WNBA's props refresh to bypass its cache on an NBA-only
            # change, and vice versa. Omitted entirely == today's behavior
            # (force-refresh applies to every force-refresh-capable sport in
            # the launch), so this is purely additive.
            refresh_command.extend(["--force-refresh-sports", force_refresh_sports_text])
        wnba_only_matchups_text = str(wnba_only_matchups or "").strip()
        if wnba_only_matchups_text:
            # Nested under force_refresh deliberately: without --force-refresh,
            # refresh_wnba_oddsapi_props.py's own cache-reuse gate skips the
            # predictions run entirely before --wnba-only-matchups would ever
            # matter, so this pairing should be structural rather than left to
            # caller discipline.
            refresh_command.extend(["--wnba-only-matchups", wnba_only_matchups_text])
    if season is not None:
        refresh_command.extend(["--season", str(season)])
    if week is not None:
        refresh_command.extend(["--week", str(week)])
    # #282: scope one launch to one league-date. Omitted entirely == the old
    # behaviour (every in-season league, horizon-bounded matchweek), so this is
    # additive for every existing caller.
    soccer_leagues_text = str(soccer_leagues or "").strip()
    if soccer_leagues_text:
        refresh_command.extend(["--soccer-leagues", soccer_leagues_text])
    soccer_date_text = str(soccer_date or "").strip()
    if soccer_date_text:
        refresh_command.extend(["--soccer-date", soccer_date_text])
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
        "oddsPhase": phase_text,
        "oddsSports": effective_sports,
        "oddsRegions": regions_text,
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

    refresh_status_manifest = {
        "date": selected_date,
        "runStamp": run_stamp,
        "generatedAt": _utc_now(),
        "artifactsDir": str(artifacts_dir),
        "refreshStatusDir": str(refresh_status_run_dir),
        "latestManifestPath": str(refresh_status_latest_path),
        "refreshOdds": True,
        "oddsPhase": phase_text,
        "oddsSports": effective_sports,
        "oddsRegions": regions_text,
        "runSummaryPath": str(refresh_and_gate_run_path),
        "oddsRefreshPath": str(odds_refresh_path),
        "migrationGateReportPath": str(artifacts_dir / "migration_gate_report.json"),
        "migrationGateConsolePath": str(artifacts_dir / "migration_gate_console.txt"),
        "executionMode": execution_mode_text,
        "launchMode": launch_mode,
        "launchOwner": "external_runner" if _is_external_runner_mode(launch_mode) else "web_process",
        "launcherServiceId": _this_service_identity() or None,
        "launcherInstanceId": _this_instance_identity() or None,
        "lane": effective_lane,
        "dryRun": bool(dry_run),
        "state": "pending_external" if _is_external_runner_mode(launch_mode) else "running",
        "externalRunner": external_runner,
    }
    if _is_external_runner_mode(launch_mode):
        write_json_file(refresh_and_gate_run_path, run_summary)
        write_json_file(refresh_status_manifest_path, refresh_status_manifest)
        write_json_file(refresh_status_latest_path, refresh_status_manifest)
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
            "lane": effective_lane,
        }

    # Always launch detached and fire-and-forget: every caller (HTTP job-start
    # endpoints, the worker loop's tick, run_refresh_worker.py's autorun) expects
    # this to return immediately with a pid, not block until the refresh finishes.
    # This used to switch to an attached, blocking `process.wait()` whenever
    # SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE was set -- a debug-logging flag
    # that had no business changing subprocess launch semantics. With that flag
    # left on in Render, it silently turned this into a synchronous call that
    # stalled the live-odds-worker's tick loop for the full refresh duration and
    # was a confirmed contributor to a production OOM. The child's stdout/stderr
    # are already captured to odds_refresh.json/odds_refresh.stderr.txt by
    # run_refresh_odds_job.py regardless, so there's no diagnostic value in
    # inheriting them here.
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

    # state and pid land in the manifest in the SAME write, only after the
    # subprocess is confirmed spawned. This used to write state="running"
    # with no pid BEFORE Popen, then a second write added pid afterward -- a
    # reader landing in that window saw state=="running", pid==None, which
    # _assert_no_active_refresh_run's self-heal logic (mis)treated as "died
    # without updating status" and stamped "failed", silently clearing the
    # way for a new launch while the original was still starting.
    refresh_status_manifest["pid"] = int(process.pid)
    run_summary["pid"] = int(process.pid)
    write_json_file(refresh_and_gate_run_path, run_summary)
    write_json_file(refresh_status_manifest_path, refresh_status_manifest)
    write_json_file(refresh_status_latest_path, refresh_status_manifest)

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
        "lane": effective_lane,
    }