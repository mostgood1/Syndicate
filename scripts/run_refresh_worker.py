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
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_queued_refresh_job.py"),
        "--latest-manifest",
        str(latest_manifest_path),
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
            "updatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    )


def _run_pending_job(latest_manifest_path: Path) -> int:
    command = _build_runner_command(latest_manifest_path)
    result = subprocess.run(command)
    return int(result.returncode)


def main() -> int:
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
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="running",
                detail="Queued refresh contract detected; invoking queued job runner.",
                ran_job=False,
            )
            exit_code = _run_pending_job(latest_manifest_path)
            latest_manifest = read_json_file(latest_manifest_path) or {}
            latest_state = str(latest_manifest.get("state") or "").strip().lower() or None
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="finished" if exit_code == 0 or latest_state == "finished" else "failed",
                detail="Queued refresh contract finished successfully." if exit_code == 0 or latest_state == "finished" else "Queued refresh contract finished with a failure.",
                ran_job=True,
                run_exit_code=exit_code,
                latest_manifest_state=latest_state,
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