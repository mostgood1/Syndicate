from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import write_text_file
from syndicate.features.shared.refresh_state_store import write_json_file


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _update_state(
    *,
    manifest_path: Path,
    latest_path: Path,
    run_summary_path: Path,
    state: str,
    exit_code: int,
) -> None:
    finished_at = _utc_now()
    manifest = read_json_file(manifest_path) or {}
    manifest["state"] = state
    manifest["exitCode"] = int(exit_code)
    manifest["finishedAt"] = finished_at
    write_json_file(manifest_path, manifest)
    write_json_file(latest_path, manifest)

    run_summary = read_json_file(run_summary_path) or {}
    run_summary["state"] = state
    run_summary["exitCode"] = int(exit_code)
    run_summary["finishedAt"] = finished_at
    write_json_file(run_summary_path, run_summary)


def _update_job_status(
    *,
    status_path: Path,
    manifest_path: Path,
    latest_path: Path,
    run_summary_path: Path,
    state: str,
    exit_code: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    command: list[str] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "state": state,
        "manifestPath": str(manifest_path),
        "latestPath": str(latest_path),
        "runSummaryPath": str(run_summary_path),
        "updatedAt": _utc_now(),
    }
    if started_at is not None:
        payload["startedAt"] = started_at
    if finished_at is not None:
        payload["finishedAt"] = finished_at
    if exit_code is not None:
        payload["exitCode"] = int(exit_code)
    if command is not None:
        payload["command"] = [str(part) for part in command]
    write_json_file(status_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the shared odds refresh command and update Syndicate status manifests on completion.")
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--latest-path", required=True)
    parser.add_argument("--run-summary-path", required=True)
    parser.add_argument("--status-path", default="")
    parser.add_argument("--stdout-path", required=True)
    parser.add_argument("--stderr-path", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command or [])
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("No refresh command provided.")

    manifest_path = Path(args.manifest_path)
    latest_path = Path(args.latest_path)
    run_summary_path = Path(args.run_summary_path)
    status_path = Path(args.status_path) if str(args.status_path or "").strip() else run_summary_path.parent / "refresh_job_status.json"
    stdout_path = Path(args.stdout_path)
    stderr_path = Path(args.stderr_path)

    started_at = _utc_now()
    _update_job_status(
        status_path=status_path,
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state="running",
        started_at=started_at,
        command=command,
    )
    result = subprocess.run(command, capture_output=True, text=True)
    write_text_file(stdout_path, result.stdout or "")
    write_text_file(stderr_path, result.stderr or "")

    state = "finished" if result.returncode == 0 else "failed"
    finished_at = _utc_now()
    _update_state(
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state=state,
        exit_code=int(result.returncode),
    )
    _update_job_status(
        status_path=status_path,
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state=state,
        exit_code=int(result.returncode),
        started_at=started_at,
        finished_at=finished_at,
        command=command,
    )
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())