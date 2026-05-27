from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root


def _default_latest_manifest_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "refresh_status_latest.json"


def _default_poll_seconds() -> float:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_POLL_SECONDS") or "15").strip()
    try:
        poll_seconds = float(raw_value)
    except ValueError:
        poll_seconds = 15.0
    return max(1.0, poll_seconds)


def _has_pending_external_contract(latest_manifest_path: Path) -> bool:
    payload = read_json_file(latest_manifest_path) or {}
    if str(payload.get("state") or "").strip().lower() != "pending_external":
        return False
    return isinstance(payload.get("externalRunner"), dict)


def _build_runner_command(latest_manifest_path: Path) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_queued_refresh_job.py"),
        "--latest-manifest",
        str(latest_manifest_path),
    ]


def _run_pending_job(latest_manifest_path: Path) -> int:
    command = _build_runner_command(latest_manifest_path)
    result = subprocess.run(command)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll Syndicate refresh state and execute queued external-runner jobs.")
    parser.add_argument("--latest-manifest", default=str(_default_latest_manifest_path()))
    parser.add_argument("--poll-seconds", type=float, default=_default_poll_seconds())
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args()

    latest_manifest_path = Path(str(args.latest_manifest or "").strip()).expanduser().resolve()
    poll_seconds = max(1.0, float(args.poll_seconds))
    max_iterations = max(0, int(args.max_iterations))

    iterations = 0
    while True:
        if _has_pending_external_contract(latest_manifest_path):
            _run_pending_job(latest_manifest_path)
        elif args.run_once:
            return 0

        iterations += 1
        if args.run_once:
            return 0
        if max_iterations and iterations >= max_iterations:
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())