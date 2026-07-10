from __future__ import annotations

import argparse
import atexit
import gc
import signal
import sys
import time
import json
from pathlib import Path

import os

try:
    import psutil
except Exception:
    psutil = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_refresh_loop import _live_refresh_loop_interval_seconds
from syndicate.features.shared.live_refresh_loop import _run_live_refresh_tick
from syndicate.features.shared.live_refresh_loop import _acquire_process_lock
from syndicate.features.shared.live_refresh_loop import _release_process_lock
from syndicate.features.shared.live_refresh_loop import _LIVE_REFRESH_LOOP_STOP
from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
from syndicate.features.shared.memory_observability import log_runtime_memory
from vendor.mlb_bettingv2.tools.web.flask_frontend import start_live_lens_background_loop


def _memory_trace_enabled() -> bool:
    return str(__import__("os").environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE") or "").strip().lower() in {"1", "true", "yes", "on"}


def _rss_bytes() -> int | None:
    if psutil is None:
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            process = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, os.getpid())
            if not process:
                return None
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
                return int(counters.WorkingSetSize)
        except Exception:
            try:
                with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
            except Exception:
                pass
            return None
        return None
    try:
        return int(psutil.Process().memory_info().rss)
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
        except Exception:
            pass
        return None


def _largest_gc_object_summary() -> dict[str, object] | None:
    largest_size = -1
    largest_type = None
    largest_len = None
    try:
        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
            except Exception:
                continue
            if size <= largest_size:
                continue
            largest_size = size
            largest_type = type(obj).__name__
            try:
                largest_len = len(obj) if hasattr(obj, "__len__") else None
            except Exception:
                largest_len = None
    except Exception:
        return None
    if largest_size < 0:
        return None
    payload: dict[str, object] = {"type": largest_type, "size_bytes": largest_size}
    if largest_len is not None:
        payload["len"] = largest_len
    return payload


def _phase_memory_snapshot() -> dict[str, object]:
    return {
        "rss_bytes": _rss_bytes(),
        "largest_gc_object": _largest_gc_object_summary(),
    }


def _log_worker_memory(stage: str, **extra: object) -> None:
    if not _memory_trace_enabled():
        return
    payload: dict[str, object] = {
        "stage": stage,
        **extra,
    }
    payload.update(_phase_memory_snapshot())
    print(f"LIVE_ODDS_WORKER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", flush=True)


def _handle_stop(_signum: int, _frame: object) -> None:
    _LIVE_REFRESH_LOOP_STOP.set()


def _run_tick() -> None:
    try:
        _log_worker_memory("tick_start")
        meta = _run_live_refresh_tick()
        _log_worker_memory("tick_end", ok=bool(meta.get("ok", False)), skipped=bool(meta.get("skipped")))
        print(f"LIVE ODDS REFRESH TICK: {meta.get('ok', False)}")
    except Exception as exc:
        _log_worker_memory("tick_error", error=f"{type(exc).__name__}: {exc}")
        print(f"LIVE ODDS REFRESH ERROR: {exc}")


def _start_live_lens_reports() -> None:
    try:
        _log_worker_memory("start_live_lens_reports_before")
        start_live_lens_background_loop()
        _log_worker_memory("start_live_lens_reports_after")
    except Exception:
        _log_worker_memory("start_live_lens_reports_error")
        pass


def main() -> int:
    _log_worker_memory("startup", argv=list(sys.argv), pid=os.getpid())
    log_runtime_memory("startup", worker="run_live_odds_refresh_worker", pid=os.getpid(), argv=list(sys.argv))
    assert_refresh_state_backend_ready(process_name="live-odds-worker")
    parser = argparse.ArgumentParser(description="Run the Syndicate live odds refresh worker loop.")
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()

    def _emit_exit_memory() -> None:
        log_runtime_memory("before_exit", worker="run_live_odds_refresh_worker", pid=os.getpid())

    atexit.register(_emit_exit_memory)

    try:
        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)
    except Exception:
        pass

    if not _acquire_process_lock():
        _log_worker_memory("lock_unavailable")
        print("LIVE ODDS REFRESH WORKER SKIPPED: lock_unavailable")
        return 0

    _start_live_lens_reports()

    try:
        interval_seconds = max(5, int(_live_refresh_loop_interval_seconds()))
    except Exception:
        interval_seconds = 60

    if args.run_once:
        try:
            _log_worker_memory("run_once_start", interval_seconds=interval_seconds)
            _run_tick()
            return 0
        finally:
            _log_worker_memory("run_once_finally")
            _release_process_lock()

    try:
        _log_worker_memory("loop_start", interval_seconds=interval_seconds)
        while not _LIVE_REFRESH_LOOP_STOP.is_set():
            _log_worker_memory("loop_tick_begin", interval_seconds=interval_seconds)
            _run_tick()
            _log_worker_memory("loop_sleep", interval_seconds=interval_seconds)
            time.sleep(interval_seconds)
    finally:
        _log_worker_memory("loop_finally")
        _release_process_lock()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())