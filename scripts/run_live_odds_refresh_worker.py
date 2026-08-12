from __future__ import annotations

import argparse
import atexit
import gc
import random
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
from syndicate.features.shared.live_refresh_loop import _live_refresh_loop_interval_for_meta
from syndicate.features.shared.live_refresh_loop import _run_live_refresh_tick
from syndicate.features.shared.live_refresh_loop import _acquire_process_lock
from syndicate.features.shared.live_refresh_loop import _release_process_lock
from syndicate.features.shared.live_refresh_loop import _LIVE_REFRESH_LOOP_STOP
from syndicate.features.shared.live_lens_loop import start_live_lens_loop
from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.memory_observability import log_all_process_memory
from syndicate.features.shared.memory_observability import log_runtime_memory
from syndicate.features.shared.ops_refresh import _active_sports_for_date
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.timezone import central_today_iso
from vendor.mlb_bettingv2.tools.web.flask_frontend import start_live_lens_background_loop


# #148. Soccer's pregame steps (schedule/odds/props/picks --
# scripts/refresh_odds_sources.py's _build_soccer_steps, phases=("pregame",))
# depend on _run_live_refresh_tick's shared adaptive phase ever actually
# resolving to "pregame" -- but that phase is a single GLOBAL decision across
# ALL active sports (effective_phase = "live" the instant ANY sport anywhere
# has a live game), not per-sport. With MLB/WNBA/NBA running live games most
# evenings, soccer's own per-sport pregame-cadence window
# (_apply_pregame_sport_cadence, 8h) and the tick's global phase being
# genuinely "pregame" rarely coincide in practice -- confirmed live
# 2026-07-30: MLB's live game made effective_phase="live" while soccer was
# independently "due" for its own sweep, so soccer's pregame steps still got
# filtered out of that tick's launch entirely. That's why #137/#146's own
# workaround put a dedicated, unconditional autorun on refresh-worker instead
# (phase="all", bundling odds+props+schedule with the sim) -- but that made
# refresh-worker a second direct OddsAPI caller for soccer, the same
# violation class fixed for MLB in #139/#144.
#
# This is the real fix: an independent, soccer-scoped pregame trigger that
# never depends on the shared tick's cross-sport phase at all -- runs on its
# own cadence, calls launch_refresh_run(phase="pregame") directly, only ever
# covering schedule/odds/props/picks (odds ownership stays on
# live-odds-worker, where it belongs). refresh-worker's own autorun now
# requests phase="live" only, keeping just the sim (soccer_{league}_artifacts,
# phases=("pregame","live")) and live_state polling.
def _soccer_pregame_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _soccer_pregame_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_SOCCER_PREGAME_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 14400)  # 4h -- matches refresh-worker's old cadence for this same work.
    except ValueError:
        value = 14400
    return max(1, value)


def _soccer_pregame_autorun_status_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "soccer_pregame_autorun_status.json"


def _soccer_active_for_date(date_str: str) -> bool:
    active = {item.strip().lower() for item in _active_sports_for_date(date_str).split(",") if item.strip()}
    return "soccer" in active


def _launch_autorun_soccer_pregame_refresh() -> None:
    if not _soccer_pregame_refresh_enabled():
        return
    selected_date = central_today_iso()
    if not _soccer_active_for_date(selected_date):
        return
    status_path = _soccer_pregame_autorun_status_path()
    last_status = read_json_file(status_path) or {}
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_soccer_pregame_refresh_interval_seconds()):
        return
    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="soccer",
            phase="pregame",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        write_json_file(status_path, {"epoch": time.time(), "sports": "soccer", "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        print(f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_FAILED {type(exc).__name__}: {exc}", flush=True)
        return
    write_json_file(status_path, {"epoch": time.time(), "sports": "soccer", "date": selected_date})
    print(f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_LAUNCHED date={selected_date} pid={result.get('pid')}", flush=True)


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
    largest_obj: object = None
    try:
        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
            except Exception:
                continue
            if size <= largest_size:
                continue
            largest_size = size
            largest_obj = obj
    except Exception:
        return None
    if largest_size < 0:
        return None
    largest_type = type(largest_obj).__name__
    try:
        largest_len = len(largest_obj) if hasattr(largest_obj, "__len__") else None
    except Exception:
        largest_len = None
    payload: dict[str, object] = {"type": largest_type, "size_bytes": largest_size}
    if largest_len is not None:
        payload["len"] = largest_len
    # A container this big is a memory-spike smoking gun on its own, but "type
    # + len" alone isn't enough to trace it back to a call site. Sample its
    # shape so a future spike is identifiable straight from the log line
    # instead of needing another guess-and-deploy round to add this after
    # the fact.
    if largest_len and largest_len > 1000:
        try:
            if isinstance(largest_obj, (list, tuple)):
                sample = largest_obj[0]
                if isinstance(sample, dict):
                    payload["sample_keys"] = sorted(str(key) for key in sample.keys())[:20]
                else:
                    payload["sample_repr"] = repr(sample)[:200]
            elif isinstance(largest_obj, dict):
                keys = list(largest_obj.keys())
                payload["sample_keys"] = [str(key) for key in keys[:20]]
        except Exception:
            pass
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


def _max_uptime_seconds() -> float | None:
    # Long-lived worker processes doing routine multi-sport file I/O every
    # tick accumulate page cache over hours of uptime that never gets
    # credited back (observed climbing from ~416MB to ~989MB container
    # memory in production with no single repeated expensive call to blame --
    # see docs/fix_notes_log.md). Render restarts the process on exit
    # regardless of exit code, so a periodic clean self-exit resets the
    # container's page cache to baseline instead of letting it climb
    # indefinitely toward another OOM kill. 0 or unset disables the restart.
    raw = str(os.environ.get("SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS") or "21600").strip()
    try:
        value = float(raw)
    except Exception:
        value = 21600.0
    if value <= 0:
        return None
    # +/-10% jitter so the restart doesn't land at the same wall-clock offset
    # every single day (which could otherwise coincide with a live game).
    jitter = value * random.uniform(-0.1, 0.1)
    return max(300.0, value + jitter)


def _run_tick() -> dict[str, object] | None:
    # #148: independent of the shared adaptive tick below (same relationship
    # as run_refresh_worker.py's own MLB sim tick, called every cycle
    # regardless of the queued-contract handling) -- its own interval gate
    # makes this a no-op on every call except when soccer's pregame refresh
    # is actually due, so calling it unconditionally here is cheap.
    try:
        _launch_autorun_soccer_pregame_refresh()
    except Exception as exc:
        print(f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_ERROR {type(exc).__name__}: {exc}", flush=True)
    try:
        _log_worker_memory("tick_start")
        meta = _run_live_refresh_tick()
        _log_worker_memory("tick_end", ok=bool(meta.get("ok", False)), skipped=bool(meta.get("skipped")), error=meta.get("error"))
        print(f"LIVE ODDS REFRESH TICK: {meta.get('ok', False)}")
        if meta.get("skipped") or meta.get("error"):
            print(f"LIVE ODDS REFRESH SKIP/ERROR DETAIL: {meta.get('error')}", flush=True)
        return meta
    except Exception as exc:
        _log_worker_memory("tick_error", error=f"{type(exc).__name__}: {exc}")
        print(f"LIVE ODDS REFRESH ERROR: {exc}")
        return None


def _start_live_lens_reports() -> None:
    try:
        _log_worker_memory("start_live_lens_reports_before")
        start_live_lens_background_loop()
        _log_worker_memory("start_live_lens_reports_after")
    except Exception:
        _log_worker_memory("start_live_lens_reports_error")
        pass
    try:
        _log_worker_memory("start_live_lens_loop_before")
        start_live_lens_loop()
        _log_worker_memory("start_live_lens_loop_after")
    except Exception:
        _log_worker_memory("start_live_lens_loop_error")
        pass


def main() -> int:
    _log_worker_memory("startup", argv=list(sys.argv), pid=os.getpid())
    log_all_process_memory("startup", worker="run_live_odds_refresh_worker", pid=os.getpid(), argv=list(sys.argv))
    log_runtime_memory("startup", worker="run_live_odds_refresh_worker", pid=os.getpid(), argv=list(sys.argv))
    assert_refresh_state_backend_ready(process_name="live-odds-worker")
    # #57: the intelligence board build can now be hosted here instead of on
    # refresh-worker, where it no longer fits alongside the MLB sim in 2GB.
    # This service runs neither the sim nor the intelligence pipeline today,
    # which is why it is the candidate.
    #
    # Gated by the same env var refresh-worker uses, so exactly one service
    # owns the loop -- two owners would recompute the same state concurrently
    # and put the collision back, just on a different box.
    #
    # The risk here is different from refresh-worker's: this service's own
    # odds refresh can spawn WNBA SmartSim and is documented spiking to
    # ~1.3-1.5GB. The pipeline defers to an in-flight refresh for that reason
    # (see _odds_refresh_in_flight in pipeline/intelligence_state.py).
    if str(os.environ.get("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP") or "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[live_odds_worker] INTELLIGENCE_LOOP_ENABLED calling start_intelligence_state_background_loop()", flush=True)
        try:
            from pipeline.intelligence_state import start_intelligence_state_background_loop

            loop_started = start_intelligence_state_background_loop()
            print(f"[live_odds_worker] INTELLIGENCE_LOOP_START_RESULT started={loop_started}", flush=True)
        except Exception as exc:
            # Must not stop this worker doing its actual job.
            print(f"[live_odds_worker] INTELLIGENCE_LOOP_START_FAILED {type(exc).__name__}: {exc}", flush=True)
    else:
        print("[live_odds_worker] INTELLIGENCE_LOOP_DISABLED", flush=True)
    parser = argparse.ArgumentParser(description="Run the Syndicate live odds refresh worker loop.")
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()

    def _emit_exit_memory() -> None:
        log_all_process_memory("before_exit", worker="run_live_odds_refresh_worker", pid=os.getpid())
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

    loop_started_at = time.monotonic()
    max_uptime_seconds = _max_uptime_seconds()
    recycled_for_uptime = False

    try:
        _log_worker_memory("loop_start", interval_seconds=interval_seconds, max_uptime_seconds=max_uptime_seconds)
        while not _LIVE_REFRESH_LOOP_STOP.is_set():
            _log_worker_memory("loop_tick_begin", interval_seconds=interval_seconds)
            meta = _run_tick()
            # Disk maintenance: compaction + retention, once per day, AFTER the
            # tick rather than during it. Its own interval gate and its own
            # enable flag make this a no-op on every call but one per day, and a
            # no-op entirely until SYNDICATE_DISK_MAINTENANCE_ENABLED is set --
            # so calling it unconditionally here is cheap, the same relationship
            # as the soccer pregame autorun above. See `#241` for why periodic
            # work on this worker is never free.
            try:
                from syndicate.features.shared.disk_maintenance import run_disk_maintenance

                run_disk_maintenance()
            except Exception as exc:
                print(f"[live_odds_worker] DISK_MAINTENANCE_ERROR {type(exc).__name__}: {exc}", flush=True)
            # Use the adaptive interval (900s idle/pregame, 60s once a game is
            # actually live -- see _live_refresh_loop_interval_for_meta) rather
            # than the fixed base interval. Sleeping a fixed 60s regardless of
            # phase meant every pregame tick relaunched the full predict-date +
            # SmartSim pipeline before the previous attempt could possibly
            # finish (confirmed taking 20-30+ minutes cold), so the cold-start
            # WNBA/MLB slate could never complete -- each attempt got cut off
            # ~60-70s in as the next tick's launch collided with it.
            try:
                sleep_seconds = _live_refresh_loop_interval_for_meta(meta) if meta is not None else interval_seconds
            except Exception:
                sleep_seconds = interval_seconds
            uptime_seconds = time.monotonic() - loop_started_at
            if max_uptime_seconds is not None and uptime_seconds >= max_uptime_seconds:
                recycled_for_uptime = True
                _log_worker_memory("loop_recycle_for_uptime", uptime_seconds=uptime_seconds, max_uptime_seconds=max_uptime_seconds)
                print(f"LIVE ODDS REFRESH WORKER RECYCLING after {uptime_seconds:.0f}s uptime to reset accumulated page cache", flush=True)
                break
            _log_worker_memory("loop_sleep", interval_seconds=sleep_seconds)
            time.sleep(sleep_seconds)
    finally:
        _log_worker_memory("loop_finally", recycled_for_uptime=recycled_for_uptime)
        _release_process_lock()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())