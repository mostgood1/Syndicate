from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.ops_refresh import launch_refresh_run
from pipeline.intelligence_state import start_intelligence_state_background_loop
from syndicate.features.shared.timezone import central_today_iso


def _refresh_state_store() -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
    from syndicate.features.shared.refresh_state_store import data_root
    from syndicate.features.shared.refresh_state_store import read_json_file
    from syndicate.features.shared.refresh_state_store import reports_root
    from syndicate.features.shared.refresh_state_store import write_json_file

    return {
        "assert_refresh_state_backend_ready": assert_refresh_state_backend_ready,
        "data_root": data_root,
        "read_json_file": read_json_file,
        "reports_root": reports_root,
        "write_json_file": write_json_file,
    }


def _default_latest_manifest_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "refresh_status_latest.json"


def _default_worker_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "refresh_worker_status.json"


def _default_poll_seconds() -> float:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_POLL_SECONDS") or "30").strip()
    try:
        poll_seconds = float(raw_value)
    except ValueError:
        poll_seconds = 30.0
    return max(1.0, poll_seconds)


def _default_max_active_jobs() -> int:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS") or "1").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 1
    return max(1, value)


def _default_stuck_claim_timeout_minutes() -> int:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_STUCK_CLAIM_TIMEOUT_MINUTES") or "15").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 15
    return max(1, value)


def _mlb_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("MLB_ENABLE_REFRESH_WORKER_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _mlb_live_lens_report_path(selected_date: str) -> Path:
    data_root = _refresh_state_store()["data_root"]()
    date_slug = str(selected_date or "").replace("-", "_")
    return data_root / "mlb_source" / "source_artifacts" / "data" / "live_lens" / f"live_lens_report_{date_slug}.json"


def _file_age_seconds(path: Path) -> float | None:
    try:
        stat_result = path.stat()
    except Exception:
        return None
    return max(0.0, time.time() - float(stat_result.st_mtime))


def _mlb_live_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("MLB_LIVE_ODDSAPI_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 60)
    except ValueError:
        value = 60
    return max(1, value)


def _launch_autorun_mlb_refresh(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    if not _mlb_auto_refresh_enabled():
        return False
    selected_date = central_today_iso()
    report_path = _mlb_live_lens_report_path(selected_date)
    report_age_seconds = _file_age_seconds(report_path)
    if report_age_seconds is not None and report_age_seconds < float(_mlb_live_refresh_interval_seconds()):
        return False

    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="mlb",
            phase="live",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-launch MLB refresh: {type(exc).__name__}: {exc}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-launched MLB refresh because {selected_date} report was stale.",
        ran_job=True,
        run_exit_code=None,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        launch_pid=int(result.get("pid") or 0) or None,
        refresh_cycle=refresh_cycle,
    )
    return True


def _pid_is_running(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _latest_manifest_payload(latest_manifest_path: Path) -> dict[str, Any]:
    payload = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    return payload if isinstance(payload, dict) else {}


def _current_active_job_count(latest_manifest_path: Path) -> int:
    payload = _latest_manifest_payload(latest_manifest_path)
    state = str(payload.get("state") or "").strip().lower()
    if state not in {"claimed", "launched", "running"}:
        return 0
    pid = payload.get("launchPid")
    if isinstance(pid, int) and _pid_is_running(pid):
        return 1
    pid = payload.get("pid")
    if isinstance(pid, int) and _pid_is_running(pid):
        return 1
    return 0


def _recover_stuck_claim(latest_manifest_path: Path, *, timeout_minutes: int) -> bool:
    payload = _latest_manifest_payload(latest_manifest_path)
    if str(payload.get("state") or "").strip().lower() != "claimed":
        return False
    if _current_active_job_count(latest_manifest_path) > 0:
        return False
    claimed_at = _parse_utc_timestamp(str(payload.get("workerClaimedAt") or "") or str(payload.get("runnerClaimedAt") or "") or str(payload.get("claimedAt") or ""))
    if claimed_at is None:
        return False
    age_minutes = max(0, int((datetime.utcnow() - claimed_at).total_seconds() // 60))
    if age_minutes < int(timeout_minutes):
        return False
    payload["state"] = "pending_external"
    payload["workerRecoveredAt"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    payload["workerRecoveryReason"] = f"stuck_claim_timeout_{timeout_minutes}m"
    for key in ("workerClaimedAt", "workerKind", "launchPid"):
        payload.pop(key, None)
    _refresh_state_store()["write_json_file"](latest_manifest_path, payload)
    return True


def _has_pending_external_contract(latest_manifest_path: Path) -> bool:
    payload = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    state = str(payload.get("state") or "").strip().lower()
    if state == "pending_external":
        return isinstance(payload.get("externalRunner"), dict)
    if state != "running":
        return False
    if isinstance(payload.get("pid"), int) and int(payload.get("pid") or 0) > 0:
        return False
    contract = payload.get("externalRunner") if isinstance(payload.get("externalRunner"), dict) else {}
    if str(contract.get("queue_state") or "").strip().lower() != "queued":
        return False
    return bool(str(contract.get("command") or "").strip()) or bool(str(contract.get("runStamp") or "").strip())


def _build_runner_command(latest_manifest_path: Path) -> list[str]:
    payload = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    run_stamp = str(payload.get("runStamp") or "").strip()
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_queued_refresh_job.py"),
        "--latest-manifest",
        str(latest_manifest_path),
        *(["--run-stamp", run_stamp] if run_stamp else []),
    ]


def _write_worker_status(
    *,
    worker_status_path: Path,
    latest_manifest_path: Path,
    state: str,
    detail: str,
    ran_job: bool = False,
    run_exit_code: int | None = None,
    latest_manifest_state: str | None = None,
    launch_pid: int | None = None,
    refresh_cycle: dict[str, int] | None = None,
) -> None:
    _refresh_state_store()["write_json_file"](
        worker_status_path,
        {
            "state": state,
            "detail": detail,
            "latestManifestPath": str(latest_manifest_path),
            "ranJob": bool(ran_job),
            "runExitCode": int(run_exit_code) if run_exit_code is not None else None,
            "latestManifestState": latest_manifest_state,
            "launchPid": int(launch_pid) if launch_pid is not None else None,
            "refreshCycle": refresh_cycle or {"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 0},
            "updatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    )


def _spawn_pending_job(latest_manifest_path: Path) -> subprocess.Popen[Any]:
    command = _build_runner_command(latest_manifest_path)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(REPO_ROOT),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(command, **popen_kwargs)


def _mark_claimed_external_contract(latest_manifest_path: Path) -> None:
    latest_manifest = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    if not latest_manifest:
        return
    claimed_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    latest_manifest["state"] = "claimed"
    latest_manifest["workerClaimedAt"] = claimed_at
    latest_manifest["workerKind"] = "refresh_worker"
    _refresh_state_store()["write_json_file"](latest_manifest_path, latest_manifest)


def _mark_throttled_worker_status(*, worker_status_path: Path, latest_manifest_path: Path, active_jobs: int, max_active_jobs: int) -> None:
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="throttled",
        detail=f"Active refresh jobs {active_jobs} reached the configured limit {max_active_jobs}.",
        ran_job=False,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        refresh_cycle={"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 1},
    )


def main() -> int:
    store = _refresh_state_store()
    assert_refresh_state_backend_ready = store["assert_refresh_state_backend_ready"]
    read_json_file = store["read_json_file"]
    print("[refresh_worker] BOOTED", flush=True)
    assert_refresh_state_backend_ready(process_name="refresh-worker")
    start_intelligence_state_background_loop()
    parser = argparse.ArgumentParser(description="Poll Syndicate refresh state and execute queued external-runner jobs.")
    parser.add_argument("--latest-manifest", default=str(_default_latest_manifest_path()))
    parser.add_argument("--worker-status", default=str(_default_worker_status_path()))
    parser.add_argument("--poll-seconds", type=float, default=_default_poll_seconds())
    parser.add_argument("--max-active-jobs", type=int, default=_default_max_active_jobs())
    parser.add_argument("--stuck-claim-timeout-minutes", type=int, default=_default_stuck_claim_timeout_minutes())
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args()

    latest_manifest_path = Path(str(args.latest_manifest or "").strip()).expanduser().resolve()
    worker_status_path = Path(str(args.worker_status or "").strip()).expanduser().resolve()
    poll_seconds = max(1.0, float(args.poll_seconds))
    max_active_jobs = max(1, int(args.max_active_jobs))
    stuck_claim_timeout_minutes = max(1, int(args.stuck_claim_timeout_minutes))
    max_iterations = max(0, int(args.max_iterations))

    iterations = 0
    while True:
        refresh_cycle = {"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 0}
        if _recover_stuck_claim(latest_manifest_path, timeout_minutes=stuck_claim_timeout_minutes):
            refresh_cycle["reclaimed_count"] = 1
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="recovered",
                detail=f"Recovered a stuck claimed refresh contract older than {stuck_claim_timeout_minutes} minutes.",
                ran_job=False,
                latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
                refresh_cycle=refresh_cycle,
            )

        active_jobs = _current_active_job_count(latest_manifest_path)
        if active_jobs >= max_active_jobs:
            refresh_cycle["skipped_due_to_cap"] = 1
            _mark_throttled_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                active_jobs=active_jobs,
                max_active_jobs=max_active_jobs,
            )
            if args.run_once:
                return 0

        if _has_pending_external_contract(latest_manifest_path):
            refresh_cycle["claimed_count"] = 1
            _mark_claimed_external_contract(latest_manifest_path)
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="claimed",
                detail="Queued refresh contract detected; job runner launched asynchronously.",
                ran_job=False,
                refresh_cycle=refresh_cycle,
            )
            process = _spawn_pending_job(latest_manifest_path)
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="launched",
                detail="Queued refresh contract launched asynchronously.",
                ran_job=True,
                run_exit_code=None,
                latest_manifest_state=str((read_json_file(latest_manifest_path) or {}).get("state") or "").strip().lower() or None,
                launch_pid=int(getattr(process, "pid", 0) or 0) or None,
                refresh_cycle=refresh_cycle,
            )
            if args.run_once:
                return 0
        elif _launch_autorun_mlb_refresh(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif args.run_once:
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="idle",
                detail="No queued external refresh contract was available.",
                ran_job=False,
                run_exit_code=None,
                latest_manifest_state=str((read_json_file(latest_manifest_path) or {}).get("state") or "").strip().lower() or None,
                refresh_cycle=refresh_cycle,
            )
            return 0

        iterations += 1
        if args.run_once:
            return 0
        if max_iterations and iterations >= max_iterations:
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="idle",
                detail="Worker reached the configured max iterations.",
                ran_job=False,
                refresh_cycle=refresh_cycle,
            )
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[refresh_worker_fatal] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise