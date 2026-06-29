from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file


def _default_latest_manifest_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "refresh_status_latest.json"


def _default_worker_status_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "refresh_worker_status.json"


def _default_poll_seconds() -> float:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_POLL_SECONDS") or "30").strip()
    try:
        poll_seconds = float(raw_value)
    except ValueError:
        poll_seconds = 30.0
    return max(1.0, poll_seconds)


def _has_pending_external_contract(latest_manifest_path: Path) -> bool:
    payload = read_json_file(latest_manifest_path) or {}
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
    payload = read_json_file(latest_manifest_path) or {}
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
) -> None:
    write_json_file(
        worker_status_path,
        {
            "state": state,
            "detail": detail,
            "latestManifestPath": str(latest_manifest_path),
            "ranJob": bool(ran_job),
            "runExitCode": int(run_exit_code) if run_exit_code is not None else None,
            "latestManifestState": latest_manifest_state,
            "launchPid": int(launch_pid) if launch_pid is not None else None,
            "updatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    )


def _spawn_pending_job(latest_manifest_path: Path) -> subprocess.Popen[Any]:
    command = _build_runner_command(latest_manifest_path)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(REPO_ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(command, **popen_kwargs)


def _mark_claimed_external_contract(latest_manifest_path: Path) -> None:
    latest_manifest = read_json_file(latest_manifest_path) or {}
    if not latest_manifest:
        return
    claimed_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    latest_manifest["state"] = "claimed"
    latest_manifest["workerClaimedAt"] = claimed_at
    latest_manifest["workerKind"] = "refresh_worker"
    write_json_file(latest_manifest_path, latest_manifest)


def main() -> int:
    assert_refresh_state_backend_ready(process_name="refresh-worker")
    parser = argparse.ArgumentParser(description="Poll Syndicate refresh state and execute queued external-runner jobs.")
    parser.add_argument("--latest-manifest", default=str(_default_latest_manifest_path()))
    parser.add_argument("--worker-status", default=str(_default_worker_status_path()))
    parser.add_argument("--poll-seconds", type=float, default=_default_poll_seconds())
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args()

    latest_manifest_path = Path(str(args.latest_manifest or "").strip()).expanduser().resolve()
    worker_status_path = Path(str(args.worker_status or "").strip()).expanduser().resolve()
    poll_seconds = max(1.0, float(args.poll_seconds))
    max_iterations = max(0, int(args.max_iterations))

    iterations = 0
    while True:
        if _has_pending_external_contract(latest_manifest_path):
            _mark_claimed_external_contract(latest_manifest_path)
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="claimed",
                detail="Queued refresh contract detected; job runner launched asynchronously.",
                ran_job=False,
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
            )
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
            )
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())