from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
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
from syndicate.features.shared.refresh_state_store import write_text_file


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _default_latest_manifest_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "refresh_status_latest.json"


def _pid_is_running(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

def _is_stale_running_external_contract(latest_manifest: dict[str, Any]) -> bool:
    if str(latest_manifest.get("state") or "").strip().lower() != "running":
        return False
    pid_raw = latest_manifest.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    if pid is not None and _pid_is_running(pid):
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
    if manifest_state not in {"pending_external", "claimed"} and not _is_stale_running_external_contract(latest_manifest):
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


def _mark_wrapper_failure(*, contract: dict[str, Any], error_message: str, trace_text: str) -> None:
    finished_at = _utc_now()
    manifest_path = Path(str(contract.get("manifestPath") or "").strip())
    latest_path = Path(str(contract.get("latestPath") or "").strip())
    run_summary_path = Path(str(contract.get("runSummaryPath") or "").strip())
    job_status_path = Path(str(contract.get("jobStatusPath") or "").strip())
    stderr_path = Path(str(contract.get("stderrPath") or "").strip())
    stdout_path = Path(str(contract.get("stdoutPath") or "").strip())
    failure_payload = {
        "ok": False,
        "returnCode": 1,
        "startedAt": contract.get("runnerClaimedAt") or finished_at,
        "finishedAt": finished_at,
        "command": contract.get("command") or [],
        "error": error_message,
        "traceback": trace_text,
    }
    try:
        write_text_file(stderr_path, f"{error_message}\n\n{trace_text}")
    except Exception:
        pass
    try:
        write_json_file(stdout_path, failure_payload)
    except Exception:
        pass
    try:
        write_json_file(job_status_path, {"state": "failed", "exitCode": 1, "error": error_message, "finishedAt": finished_at})
    except Exception:
        pass
    try:
        if manifest_path.exists() or latest_path.exists() or run_summary_path.exists():
            for path in (manifest_path, latest_path, run_summary_path):
                if path.exists():
                    payload = read_json_file(path) or {}
                    if isinstance(payload, dict):
                        payload["state"] = "failed"
                        payload["exitCode"] = 1
                        payload["finishedAt"] = finished_at
                        write_json_file(path, payload)
    except Exception:
        pass


def main() -> int:
    assert_refresh_state_backend_ready(process_name="queued-refresh-job")
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

    try:
        print(f"[queue_runner] launching refresh job: {json.dumps(wrapper_command)}", flush=True)
        result = subprocess.run(wrapper_command)
        print(f"[queue_runner] return code: {result.returncode}", flush=True)
        return int(result.returncode)
    except Exception as exc:
        trace_text = traceback.format_exc()
        error_message = f"{type(exc).__name__}: {exc}"
        print(f"[queue_runner_fatal] {error_message}", file=sys.stderr, flush=True)
        print(trace_text, file=sys.stderr, flush=True)
        _mark_wrapper_failure(contract=contract, error_message=error_message, trace_text=trace_text)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())