from __future__ import annotations

import argparse
import json
import threading
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
import os

REPO_ROOT = Path(__file__).resolve().parents[1]


def _memory_trace_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _stream_child_output(pipe, *, chunks: list[str], target_stream) -> None:
    try:
        while True:
            line = pipe.readline()
            if line == "":
                break
            chunks.append(line)
            target_stream.write(line)
            target_stream.flush()
    finally:
        try:
            pipe.close()
        except Exception:
            pass


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
    live_streaming = _memory_trace_enabled()
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    if live_streaming and process.stdout is not None and process.stderr is not None:
        stdout_thread = threading.Thread(
            target=_stream_child_output,
            kwargs={"pipe": process.stdout, "chunks": stdout_chunks, "target_stream": sys.stdout},
            daemon=True,
            name="refresh-job-stdout-stream",
        )
        stderr_thread = threading.Thread(
            target=_stream_child_output,
            kwargs={"pipe": process.stderr, "chunks": stderr_chunks, "target_stream": sys.stdout},
            daemon=True,
            name="refresh-job-stderr-stream",
        )
        stdout_thread.start()
        stderr_thread.start()
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
            if live_streaming:
                process.wait(timeout=timeout_seconds)
                if stdout_thread is not None:
                    stdout_thread.join()
                if stderr_thread is not None:
                    stderr_thread.join()
            else:
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
    summary_keys = sorted(str(key) for key in run_summary.keys()) if isinstance(run_summary, dict) else []
    print(
        f"INTELLIGENCE_REFRESH_QUEUE_CONTEXT run_summary_path={run_summary_path} summary_keys={json.dumps(summary_keys)}",
        flush=True,
    )
    if not isinstance(run_summary, dict):
        print(
            f"INTELLIGENCE_REFRESH_SKIPPED reason=run_summary_not_dict run_summary_path={run_summary_path}",
            flush=True,
        )
        return None

    selected_date = str(
        run_summary.get("date")
        or run_summary.get("selectedDate")
        or run_summary.get("selected_date")
        or ""
    ).strip()
    print(
        f"INTELLIGENCE_REFRESH_QUEUE_CONTEXT selected_date={selected_date or 'null'} summary_keys={json.dumps(summary_keys)}",
        flush=True,
    )
    if not selected_date:
        print(
            f"INTELLIGENCE_REFRESH_SKIPPED reason=missing_selected_date run_summary_path={run_summary_path}",
            flush=True,
        )
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
    print(
        f"INTELLIGENCE_REFRESH_QUEUE_CONTEXT resolved_payload={json.dumps(payload, sort_keys=True)}",
        flush=True,
    )

    from pipeline.intelligence_state import queue_intelligence_state_refresh

    queued_key = queue_intelligence_state_refresh(payload)
    return queued_key, payload


def _echo_captured_output(*, stdout_text: str, stderr_text: str, failed: bool = False) -> None:
    # On Render this process is launched with stdout/stderr DEVNULL'd, so these
    # prints are free there; locally and under GHA they are the fastest way to
    # see why a refresh failed. Full stdout echo stays gated behind the memory
    # trace flag because the result JSON can be large.
    if failed and stderr_text.strip():
        print("[refresh_job_child_stderr_tail]", flush=True)
        print(stderr_text[-4000:], flush=True)
    if not _memory_trace_enabled():
        return
    if stdout_text.strip():
        print("[refresh_job_child_stdout]", flush=True)
        print(stdout_text, flush=True)
    if stderr_text.strip():
        print("[refresh_job_child_stderr]", flush=True)
        print(stderr_text, flush=True)


def _failure_summary_from_result(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact per-sport failure detail from a refresh_odds_sources result payload.

    Bounded by design: this is persisted through the shared refresh-state store
    (Redis on Render) so the web service can surface WHY a worker-side refresh
    cycle failed without access to the worker's disk.
    """
    summary: list[dict[str, Any]] = []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return summary
    for sport_result in results:
        if not isinstance(sport_result, dict) or bool(sport_result.get("ok")):
            continue
        entry: dict[str, Any] = {"sport": sport_result.get("sport"), "ok": False}
        failing_steps: list[dict[str, Any]] = []
        step_groups: list[Any] = [sport_result.get("refresh_steps")]
        generation = sport_result.get("generation")
        if isinstance(generation, dict):
            step_groups.append(generation.get("steps"))
        seen_steps: set[str] = set()
        for group in step_groups:
            if not isinstance(group, list):
                continue
            for step in group:
                if not isinstance(step, dict) or bool(step.get("ok")):
                    continue
                name = str(step.get("name") or "unnamed")
                if name in seen_steps:
                    continue
                seen_steps.add(name)
                failing_steps.append(
                    {
                        "name": name,
                        "return_code": step.get("return_code"),
                        "stderr_tail": str(step.get("stderr_tail") or step.get("stderr") or "")[-1600:] or None,
                    }
                )
        if failing_steps:
            entry["failing_steps"] = failing_steps
        post_refresh = sport_result.get("post_refresh")
        if isinstance(post_refresh, dict) and not bool(post_refresh.get("ok")) and not bool(post_refresh.get("dry_run")):
            meta = post_refresh.get("meta") if isinstance(post_refresh.get("meta"), dict) else {}
            entry["post_refresh_error"] = str(meta.get("error") or post_refresh.get("stderr") or "post refresh tracking sync failed")[:800]
        mirror = sport_result.get("mirror")
        if isinstance(mirror, dict) and not bool(mirror.get("ok")) and not bool(mirror.get("dry_run")):
            entry["mirror_error"] = str(mirror.get("stderr_tail") or mirror.get("stderr") or "mirror step failed")[-800:]
        summary.append(entry)
    return summary

def _stderr_tail(stderr_chunks: list[str], *, limit: int = 2000) -> str:
    return "".join(stderr_chunks)[-limit:]


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
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
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
    failure_summary: list[dict[str, Any]] = []
    if return_code != 0 and stdout_payload:
        failure_summary = _failure_summary_from_result(stdout_payload)
        if failure_summary:
            failure_payload["failureSummary"] = failure_summary
            print(f"ODDS_REFRESH_FAILURE_SUMMARY {json.dumps(failure_summary, default=str)}", flush=True)
    _echo_captured_output(stdout_text=stdout_text, stderr_text=stderr_text, failed=return_code != 0)
    if return_code == 0 and stdout_payload:
        print(f"RESULT_FILE_WRITE_BEGIN path={stdout_path}", flush=True)
        _safe_write_json(stdout_path, stdout_payload)
    else:
        if stdout_text.strip() and not stdout_payload:
            failure_payload["stdout"] = stdout_text
        if stdout_payload:
            # Keep the child's full parsed result: it names the failing sport,
            # step, and (post-fix) that step's stderr tail. Discarding it made
            # worker-side failures undiagnosable from published artifacts.
            failure_payload["result"] = stdout_payload
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
        extra={
            "childPid": int(process.pid),
            "childPoll": process.poll(),
            "childReturnCode": process.returncode,
            "stdoutBufferLen": len(stdout_text),
            "stderrBufferLen": len(stderr_text),
            "stderrTail": stderr_text[-2000:],
            **({"failureSummary": failure_summary} if failure_summary else {}),
        },
    )
    if return_code == 0:
        print(f"ODDS_REFRESH_SUCCESS manifest={manifest_path} latest={latest_path}", flush=True)
        try:
            run_summary = read_json_file(run_summary_path)
            run_summary_present = isinstance(run_summary, dict)
            selected_date = str(
                (run_summary or {}).get("date")
                or (run_summary or {}).get("selectedDate")
                or (run_summary or {}).get("selected_date")
                or ""
            ).strip()
            print(
                f"INTELLIGENCE_REFRESH_HANDOFF run_stamp={manifest_path.parent.name} return_code={return_code} selected_date={selected_date or 'null'} run_summary_present={run_summary_present}",
                flush=True,
            )
            queued = _queue_intelligence_snapshot_refresh(run_summary_path=run_summary_path)
            if queued is not None:
                queued_key, queued_payload = queued
                print(
                    f"INTELLIGENCE_REFRESH_ENQUEUED key={queued_key} date={queued_payload.get('date')}",
                    flush=True,
                )
            else:
                reason = "run_summary_not_dict" if not run_summary_present else ("missing_selected_date" if not selected_date else "unknown")
                print(f"INTELLIGENCE_REFRESH_SKIPPED reason={reason}", flush=True)
        except Exception:
            print(f"refresh_job_intelligence_refresh_failed exception={traceback.format_exc().strip().splitlines()[-1] if traceback.format_exc().strip().splitlines() else 'unknown'}", flush=True)
            print("[refresh_job_intelligence_refresh_failed]", file=sys.stderr, flush=True)
            print(traceback.format_exc(), file=sys.stderr, flush=True)
    return int(return_code)


if __name__ == "__main__":
    raise SystemExit(main())