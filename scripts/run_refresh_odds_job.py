from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the shared odds refresh command and update Syndicate status manifests on completion.")
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--latest-path", required=True)
    parser.add_argument("--run-summary-path", required=True)
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
    stdout_path = Path(args.stdout_path)
    stderr_path = Path(args.stderr_path)

    result = subprocess.run(command, capture_output=True, text=True)
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")

    state = "finished" if result.returncode == 0 else "failed"
    _update_state(
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state=state,
        exit_code=int(result.returncode),
    )
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())