from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _default_latest_manifest_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "refresh_status_latest.json"

def _is_stale_running_external_contract(latest_manifest: dict[str, Any]) -> bool:
    if str(latest_manifest.get("state") or "").strip().lower() != "running":
        return False
    if isinstance(latest_manifest.get("pid"), int) and int(latest_manifest.get("pid") or 0) > 0:
        return False
    contract = latest_manifest.get("externalRunner")
    if not isinstance(contract, dict):
        return False
    if str(contract.get("queue_state") or "").strip().lower() != "queued":
        return False
    return bool(str(contract.get("command") or "").strip()) or bool(str(contract.get("runStamp") or "").strip())


def _claim_external_runner_contract(*, latest_manifest_path: Path, expected_run_stamp: str | None = None) -> dict[str, Any]:
    latest_manifest = read_json_file(latest_manifest_path) or {}
    if not latest_manifest:
        raise ValueError(f"Latest refresh manifest not found or invalid: {latest_manifest_path}")

    manifest_state = str(latest_manifest.get("state") or "").strip().lower()
    if manifest_state != "pending_external" and not _is_stale_running_external_contract(latest_manifest):
        raise ValueError(f"Latest refresh manifest is not queued for an external runner: {manifest_state or 'missing state'}")

    contract = latest_manifest.get("externalRunner")
    if not isinstance(contract, dict):
        raise ValueError("Latest refresh manifest is missing an externalRunner contract.")

    if expected_run_stamp and str(contract.get("runStamp") or "") != str(expected_run_stamp):
        raise ValueError(
            f"Latest queued run does not match expected run stamp {expected_run_stamp}: {contract.get('runStamp') or 'missing'}"
        )

    manifest_path_text = str(contract.get("manifestPath") or "").strip()
    run_summary_path_text = str(contract.get("runSummaryPath") or "").strip()
    job_status_path_text = str(contract.get("jobStatusPath") or "").strip()
    if not manifest_path_text:
        raise ValueError("External runner contract is missing manifestPath.")
    if not run_summary_path_text:
        raise ValueError("External runner contract is missing runSummaryPath.")

    manifest_path = Path(manifest_path_text)
    run_summary_path = Path(run_summary_path_text)
    job_status_path = Path(job_status_path_text) if job_status_path_text else run_summary_path.parent / "refresh_job_status.json"

    manifest = read_json_file(manifest_path) or {}
    if not manifest:
        raise ValueError(f"Queued refresh manifest is missing or invalid: {manifest_path}")

    claimed_at = _utc_now()
    latest_manifest["state"] = "running"
    latest_manifest["runnerClaimedAt"] = claimed_at
    latest_manifest["runnerKind"] = "external_runner"
    write_json_file(latest_manifest_path, latest_manifest)

    manifest["state"] = "running"
    manifest["runnerClaimedAt"] = claimed_at
    manifest["runnerKind"] = "external_runner"
    write_json_file(manifest_path, manifest)

    run_summary = read_json_file(run_summary_path) or {}
    if run_summary:
        run_summary["state"] = "running"
        run_summary["runnerClaimedAt"] = claimed_at
        run_summary["runnerKind"] = "external_runner"
        write_json_file(run_summary_path, run_summary)

    contract["jobStatusPath"] = str(job_status_path)
    contract["runnerClaimedAt"] = claimed_at
    contract["runnerKind"] = "external_runner"

    return contract


def _build_wrapper_command(contract: dict[str, Any]) -> list[str]:
    required = {
        "manifestPath": "manifest path",
        "latestPath": "latest status path",
        "runSummaryPath": "run summary path",
        "jobStatusPath": "job status path",
        "stdoutPath": "stdout path",
        "stderrPath": "stderr path",
    }
    missing = [label for key, label in required.items() if not str(contract.get(key) or "").strip()]
    if missing:
        raise ValueError(f"External runner contract is missing required fields: {', '.join(missing)}")

    command = contract.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError("External runner contract is missing a refresh command.")

    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_refresh_odds_job.py"),
        "--manifest-path",
        str(contract["manifestPath"]),
        "--latest-path",
        str(contract["latestPath"]),
        "--run-summary-path",
        str(contract["runSummaryPath"]),
        "--status-path",
        str(contract["jobStatusPath"]),
        "--stdout-path",
        str(contract["stdoutPath"]),
        "--stderr-path",
        str(contract["stderrPath"]),
        "--",
        *[str(part) for part in command],
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim the latest queued Syndicate refresh contract and run it through the refresh job wrapper.")
    parser.add_argument("--latest-manifest", default=str(_default_latest_manifest_path()))
    parser.add_argument("--run-stamp", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    latest_manifest_path = Path(str(args.latest_manifest or "").strip()).expanduser().resolve()
    contract = _claim_external_runner_contract(
        latest_manifest_path=latest_manifest_path,
        expected_run_stamp=str(args.run_stamp or "").strip() or None,
    )
    wrapper_command = _build_wrapper_command(contract)

    if args.dry_run:
        print(json.dumps({"ok": True, "latest_manifest": str(latest_manifest_path), "wrapper_command": wrapper_command}, indent=2))
        return 0

    result = subprocess.run(wrapper_command)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())