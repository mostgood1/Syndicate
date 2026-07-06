from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _refresh_state_store():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
    from syndicate.features.shared.refresh_state_store import read_json_file
    from syndicate.features.shared.refresh_state_store import write_json_file
    from syndicate.features.shared.refresh_state_store import write_text_file

    return {
        "assert_refresh_state_backend_ready": assert_refresh_state_backend_ready,
        "read_json_file": read_json_file,
        "write_json_file": write_json_file,
        "write_text_file": write_text_file,
    }


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
    store = _refresh_state_store()
    finished_at = _utc_now()
    read_json_file = store["read_json_file"]
    write_json_file = store["write_json_file"]
    manifest = read_json_file(manifest_path) or {}
    manifest["state"] = state
    manifest["exitCode"] = int(exit_code)
    manifest["finishedAt"] = finished_at
    manifest_text = json.dumps(manifest, indent=2)
    print(f"SAFE_WRITE_BEGIN path={manifest_path} payload_size={len(manifest_text.encode('utf-8'))}", flush=True)
    write_json_file(manifest_path, manifest)
    print(f"SAFE_WRITE_SUCCESS path={manifest_path}", flush=True)
    print(f"SAFE_WRITE_BEGIN path={latest_path} payload_size={len(manifest_text.encode('utf-8'))}", flush=True)
    write_json_file(latest_path, manifest)
    print(f"SAFE_WRITE_SUCCESS path={latest_path}", flush=True)

    run_summary = read_json_file(run_summary_path) or {}
    run_summary["state"] = state
    run_summary["exitCode"] = int(exit_code)
    run_summary["finishedAt"] = finished_at
    run_summary_text = json.dumps(run_summary, indent=2)
    print(f"SAFE_WRITE_BEGIN path={run_summary_path} payload_size={len(run_summary_text.encode('utf-8'))}", flush=True)
    write_json_file(run_summary_path, run_summary)
    print(f"SAFE_WRITE_SUCCESS path={run_summary_path}", flush=True)


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
    extra: dict[str, Any] | None = None,
) -> None:
    store = _refresh_state_store()
    write_json_file = store["write_json_file"]
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
    if extra:
        payload.update(extra)
    payload_text = json.dumps(payload, indent=2)
    print(f"SAFE_WRITE_BEGIN path={status_path} payload_size={len(payload_text.encode('utf-8'))}", flush=True)
    write_json_file(status_path, payload)
    print(f"SAFE_WRITE_SUCCESS path={status_path}", flush=True)


def _safe_write_text(path: Path, payload: str) -> None:
    try:
        payload_text = str(payload or "")
        print(f"SAFE_WRITE_BEGIN path={path} payload_size={len(payload_text.encode('utf-8'))}", flush=True)
        _refresh_state_store()["write_text_file"](path, payload)
        print(f"SAFE_WRITE_SUCCESS path={path}", flush=True)
        print(f"[refresh_job_write_text_ok] path={path}", flush=True)
    except Exception as exc:
        print(
            f"SAFE_WRITE_EXCEPTION exception_type={type(exc).__name__} exception_message={exc} path={path}",
            file=sys.stderr,
            flush=True,
        )
        print(f"[refresh_job_write_text_failed] path={path}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        payload_text = json.dumps(payload, indent=2)
        print(f"SAFE_WRITE_BEGIN path={path} payload_size={len(payload_text.encode('utf-8'))}", flush=True)
        _refresh_state_store()["write_text_file"](path, payload_text)
        print(f"SAFE_WRITE_SUCCESS path={path}", flush=True)
        print(f"[refresh_job_write_json_ok] path={path}", flush=True)
    except Exception as exc:
        print(
            f"SAFE_WRITE_EXCEPTION exception_type={type(exc).__name__} exception_message={exc} path={path}",
            file=sys.stderr,
            flush=True,
        )
        print(f"[refresh_job_write_json_failed] path={path}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise


def _wait_for_child_process(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: int = 5,
    status_path: Path,
    manifest_path: Path,
    latest_path: Path,
    run_summary_path: Path,
    started_at: str,
    command: list[str],
) -> tuple[str, str, int]:
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    wait_started_at = _utc_now()
    print(
        f"WRAPPER_WAIT_BEGIN pid={int(process.pid)} poll={process.poll()} returncode={process.returncode} stdout_len=0 stderr_len=0",
        flush=True,
    )
    _update_job_status(
        status_path=status_path,
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state="running",
        started_at=started_at,
        command=command,
        extra={
            "waitState": "waiting",
            "waitStartedAt": wait_started_at,
            "waitTimeoutSeconds": timeout_seconds,
            "childPid": int(process.pid),
            "childPoll": process.poll(),
            "childReturnCode": process.returncode,
        },
    )
    while True:
        try:
            print(
                f"WRAPPER_WAIT_POLL pid={int(process.pid)} poll={process.poll()} returncode={process.returncode} stdout_len={sum(len(chunk) for chunk in stdout_chunks)} stderr_len={sum(len(chunk) for chunk in stderr_chunks)}",
                flush=True,
            )
            stdout_text, stderr_text = process.communicate(timeout=timeout_seconds)
            stdout_chunks.append(str(stdout_text or ""))
            stderr_chunks.append(str(stderr_text or ""))
            print(
                f"WRAPPER_WAIT_END pid={int(process.pid)} poll={process.poll()} returncode={process.returncode} stdout_len={sum(len(chunk) for chunk in stdout_chunks)} stderr_len={sum(len(chunk) for chunk in stderr_chunks)}",
                flush=True,
            )
            _update_job_status(
                status_path=status_path,
                manifest_path=manifest_path,
                latest_path=latest_path,
                run_summary_path=run_summary_path,
                state="running",
                started_at=started_at,
                command=command,
                extra={
                    "waitState": "complete",
                    "waitFinishedAt": _utc_now(),
                    "waitTimeoutSeconds": timeout_seconds,
                    "childPid": int(process.pid),
                    "childPoll": process.poll(),
                    "childReturnCode": process.returncode,
                    "stdoutBufferLen": sum(len(chunk) for chunk in stdout_chunks),
                    "stderrBufferLen": sum(len(chunk) for chunk in stderr_chunks),
                },
            )
            return "".join(stdout_chunks), "".join(stderr_chunks), int(process.returncode or 0)
        except subprocess.TimeoutExpired as exc:
            if exc.output:
                stdout_chunks.append(str(exc.output))
            if exc.stderr:
                stderr_chunks.append(str(exc.stderr))
            print(
                f"WRAPPER_WAIT_TIMEOUT pid={int(process.pid)} poll={process.poll()} returncode={process.returncode} stdout_len={sum(len(chunk) for chunk in stdout_chunks)} stderr_len={sum(len(chunk) for chunk in stderr_chunks)} timeout_seconds={timeout_seconds}",
                flush=True,
            )
            _update_job_status(
                status_path=status_path,
                manifest_path=manifest_path,
                latest_path=latest_path,
                run_summary_path=run_summary_path,
                state="running",
                started_at=started_at,
                command=command,
                extra={
                    "waitState": "waiting",
                    "waitTickAt": _utc_now(),
                    "waitTimeoutSeconds": timeout_seconds,
                    "childPid": int(process.pid),
                    "childPoll": process.poll(),
                    "childReturnCode": process.returncode,
                    "stdoutBufferLen": sum(len(chunk) for chunk in stdout_chunks),
                    "stderrBufferLen": sum(len(chunk) for chunk in stderr_chunks),
                },
            )


def _queue_intelligence_snapshot_refresh(*, run_summary_path: Path) -> tuple[str, dict[str, Any]] | None:
    store = _refresh_state_store()
    read_json_file = store["read_json_file"]
    run_summary = read_json_file(run_summary_path) or {}
    if not isinstance(run_summary, dict):
        return None

    selected_date = str(
        run_summary.get("date")
        or run_summary.get("selectedDate")
        or run_summary.get("selected_date")
        or ""
    ).strip()
    if not selected_date:
        return None

    payload: dict[str, Any] = {
        "date": selected_date,
        "question": "top edges today",
        "mode": "live",
        "sport": "all",
        "timing": "",
        "limit": 10,
        "include_props": True,
        "include_games": True,
        "force_refresh": True,
    }

    from pipeline.intelligence_state import queue_intelligence_state_refresh

    queued_key = queue_intelligence_state_refresh(payload)
    return queued_key, payload


def main() -> int:
    print("[refresh_job] script entry reached", flush=True)
    store = _refresh_state_store()
    assert_refresh_state_backend_ready = store["assert_refresh_state_backend_ready"]
    read_json_file = store["read_json_file"]
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

    try:
        assert_refresh_state_backend_ready(process_name="refresh-job")
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
        print(f"LAUNCH_COMMAND command={json.dumps(command)}", flush=True)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(f"LAUNCH_PID pid={int(process.pid)}", flush=True)
        stdout_text, stderr_text, return_code = _wait_for_child_process(
            process,
            timeout_seconds=5,
            status_path=status_path,
            manifest_path=manifest_path,
            latest_path=latest_path,
            run_summary_path=run_summary_path,
            started_at=started_at,
            command=command,
        )
        print(f"RETURN_CODE return_code={return_code}", flush=True)
        print(f"STDOUT_LENGTH length={len(stdout_text)}", flush=True)
        print(f"STDERR_LENGTH length={len(stderr_text)}", flush=True)
        failure_error = None
    except Exception as exc:
        started_at = locals().get("started_at", _utc_now())
        failure_error = f"{type(exc).__name__}: {exc}"
        trace_text = traceback.format_exc()
        stdout_text = json.dumps(
            {
                "ok": False,
                "error": failure_error,
                "command": command,
                "startedAt": started_at,
            },
            indent=2,
        )
        stderr_text = f"{failure_error}\n\n{trace_text}"
        _safe_write_text(stderr_path, stderr_text)
        _safe_write_json(
            stdout_path,
            {
                "ok": False,
                "returnCode": 1,
                "startedAt": started_at,
                "finishedAt": _utc_now(),
                "command": command,
                "error": failure_error,
                "traceback": trace_text,
            },
        )
        try:
            _update_job_status(
                status_path=status_path,
                manifest_path=manifest_path,
                latest_path=latest_path,
                run_summary_path=run_summary_path,
                state="failed",
                exit_code=1,
                started_at=started_at,
                finished_at=_utc_now(),
                command=command,
            )
        except Exception:
            pass
        return 1

    state = "finished" if return_code == 0 else "failed"
    finished_at = _utc_now()
    stdout_payload: dict[str, Any]
    try:
        stdout_payload = json.loads(stdout_text) if stdout_text.strip() else {}
    except Exception:
        stdout_payload = {}

    failure_payload: dict[str, Any] = {
        "ok": return_code == 0,
        "returnCode": int(return_code),
        "startedAt": started_at,
        "finishedAt": finished_at,
        "command": command,
    }
    if failure_error:
        failure_payload["error"] = failure_error
    if return_code != 0:
        if stdout_text.strip():
            print("[refresh_job_child_stdout]", flush=True)
            print(stdout_text, flush=True)
        if stderr_text.strip():
            print("[refresh_job_child_stderr]", flush=True)
            print(stderr_text, flush=True)
    if return_code == 0 and stdout_payload:
        print(f"RESULT_FILE_WRITE_BEGIN path={stdout_path}", flush=True)
        _safe_write_json(stdout_path, stdout_payload)
    else:
        if stdout_text.strip() and not stdout_payload:
            failure_payload["stdout"] = stdout_text
        print(f"RESULT_FILE_WRITE_BEGIN path={stdout_path}", flush=True)
        _safe_write_json(stdout_path, failure_payload)
    print(f"SNAPSHOT_WRITTEN path={stdout_path} ok={return_code == 0}", flush=True)
    print(f"RESULT_FILE_WRITE_BEGIN path={stderr_path}", flush=True)
    _safe_write_text(stderr_path, stderr_text)
    print(f"RESULT_FILE_WRITE_END path={stderr_path}", flush=True)
    _update_state(
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state=state,
        exit_code=int(return_code),
    )
    _update_job_status(
        status_path=status_path,
        manifest_path=manifest_path,
        latest_path=latest_path,
        run_summary_path=run_summary_path,
        state=state,
        exit_code=int(return_code),
        started_at=started_at,
        finished_at=finished_at,
        command=command,
    )
    if return_code == 0:
        print(f"ODDS_REFRESH_SUCCESS manifest={manifest_path} latest={latest_path}", flush=True)
        try:
            queued = _queue_intelligence_snapshot_refresh(run_summary_path=run_summary_path)
            if queued is not None:
                queued_key, queued_payload = queued
                print(
                    f"INTELLIGENCE_REFRESH_ENQUEUED key={queued_key} date={queued_payload.get('date')}",
                    flush=True,
                )
        except Exception:
            print("[refresh_job_intelligence_refresh_failed]", file=sys.stderr, flush=True)
            print(traceback.format_exc(), file=sys.stderr, flush=True)
    return int(return_code)


if __name__ == "__main__":
    raise SystemExit(main())