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


def _report_previous_soccer_pregame_run(last_status: dict) -> None:
    """Print the PREVIOUS run's per-step outcome to THIS worker's stdout (`#433`).

    WHY THIS EXISTS, and it is not a nice-to-have. Soccer game odds stopped
    being captured on 2026-08-10 and nobody saw an error for four days. Not
    because nothing was logged -- because of WHERE it was logged:

      * `launch_refresh_run` spawns the refresh detached with
        `stdout=DEVNULL, stderr=DEVNULL` (`ops_refresh.py`). Its comment says
        the child's output is "already captured to
        odds_refresh.json/odds_refresh.stderr.txt ... so there's no diagnostic
        value in inheriting them here." That is TRUE and, on this deployment,
        misleading: those files land on **live-odds-worker's own disk**, and
        Render gives the web service a DIFFERENT disk. So
        `/api/ops/odds-refresh/logs` returns `exists=False` from web forever --
        which reads as "no logs" and is really "wrong machine".
      * Render's log collector only captures a service's OWN stdout.

    The worker CAN read its own disk. So rather than inheriting the child's
    stdout -- which would push a full 50-step refresh, thousands of lines, into
    the log collector every 4 hours -- this reads the run artifact the child
    already wrote and emits ONE compact line per step plus a summary.

    Deliberately reports the PREVIOUS run, on the next tick. The launch is
    fire-and-forget by design (`ops_refresh.py` documents that making it
    blocking stalled this worker's tick loop and contributed to an OOM), so
    there is no point at which this function could wait for a result. Reading
    last tick's artifact costs nothing and cannot stall anything.

    Never raises: an observability side-effect must not be able to break the
    autorun it is describing -- the same rule `_append_soccer_book_quotes`
    follows, and the reason a failing shard append stayed silent.
    """
    try:
        artifacts_dir = str((last_status or {}).get("artifactsDir") or "").strip()
        stamp = str((last_status or {}).get("runStamp") or "").strip()
        if not artifacts_dir or (last_status or {}).get("reported"):
            return
        result_path = Path(artifacts_dir) / "odds_refresh.json"
        if not result_path.exists():
            # A launched run with no artifact is itself the finding: the child
            # died before writing anything. Say so -- silence here is what the
            # four-day outage looked like from outside.
            print(
                f"[live_odds_worker] SOCCER_PREGAME_RUN_NO_ARTIFACT stamp={stamp} "
                f"path={result_path} (child wrote nothing)",
                flush=True,
            )
            return
        payload = json.loads(result_path.read_text(encoding="utf-8", errors="replace"))
        results = payload.get("results") or []
        steps = []
        for entry in results if isinstance(results, list) else []:
            generation = (entry or {}).get("generation") or {}
            for step in generation.get("steps") or []:
                steps.append(step)
        ok_count = sum(1 for s in steps if s.get("ok") or s.get("return_code") == 0)
        failed = [s for s in steps if not (s.get("ok") or s.get("return_code") == 0)]
        print(
            f"[live_odds_worker] SOCCER_PREGAME_RUN_SUMMARY stamp={stamp} "
            f"steps={len(steps)} ok={ok_count} failed={len(failed)}",
            flush=True,
        )
        # Only the odds steps by name, plus every failure. The full 50-step list
        # every 4 hours is noise; the odds steps are the ones this outage was
        # about, and a failure anywhere is always worth a line.
        for step in steps:
            name = str(step.get("name") or "")
            is_odds = name.endswith("_odds")
            ok = bool(step.get("ok") or step.get("return_code") == 0)
            if is_odds or not ok:
                print(
                    f"[live_odds_worker] SOCCER_PREGAME_STEP name={name} ok={ok} "
                    f"rc={step.get('return_code')} skipped={step.get('skipped')}",
                    flush=True,
                )
    except Exception as exc:  # noqa: BLE001
        print(f"[live_odds_worker] SOCCER_PREGAME_RUN_SUMMARY_FAILED {type(exc).__name__}: {exc}", flush=True)


# PHASE 2 of the migration off the daily-update GHA cron. Phase 1 moved
# NFL/NCAAF/NCAAB to refresh-worker's weekly autorun (`render.yaml`); WNBA was
# never re-homed, so NOTHING called `refresh_wnba_oddsapi_props.main()` on any
# cadence. Measured 2026-08-17: `MAIN_ENTRY` 0 hits over 8h on BOTH workers, and
# `GAME_CARDS_CENSUS` 0 over ~2 days with the emitter confirmed present in both
# deployed SHAs. The GHA cron cannot cover it either -- it reads
# `RUN_FULL_PIPELINE` from `github.event.inputs`, which is empty on the
# `schedule` trigger, so full regeneration is manual-dispatch only.
#
# `phase="pregame"` IS LOAD-BEARING, NOT COPIED FROM SOCCER. This worker is 2GB
# and already carries WNBA SmartSim + live-lens load; `render.yaml` records sim
# workers cut to 1 and the WNBA sim count cut 500 -> 250 -> 100 fighting for that
# memory, against a WNBA refresh leg measured at ~1.3-1.5GB RSS. Pregame covers
# schedule/odds/props/picks and EXCLUDES the sim leg. A full-phase autorun here
# would OOM the service.
def _wnba_pregame_refresh_enabled() -> bool:
    # DEFAULT OFF. New periodic worker work is never free (`#241` caused a
    # production restart loop), and enabling it is a `render.yaml` change, which
    # is a deploy and therefore coordinator-owned.
    raw_value = str(os.environ.get("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _wnba_pregame_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_WNBA_PREGAME_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 14400)  # 4h, matching soccer's cadence for the same work.
    except ValueError:
        value = 14400
    return max(1, value)


def _wnba_pregame_autorun_status_path() -> Path:
    return reports_root() / "refresh_status" / "latest" / "wnba_pregame_autorun_status.json"


def _wnba_active_for_date(date_str: str) -> bool:
    active = {item.strip().lower() for item in _active_sports_for_date(date_str).split(",") if item.strip()}
    return "wnba" in active


def _report_previous_wnba_pregame_run(last_status: dict) -> None:
    """Print the PREVIOUS run's outcome to THIS worker's stdout.

    Same reason as `_report_previous_soccer_pregame_run` (`#433`): soccer odds
    stopped for FOUR DAYS with no visible error because `launch_refresh_run`
    spawns the child detached with stdout/stderr to DEVNULL, so the launch is
    otherwise the last thing anyone hears about the run. A silent WNBA autorun
    would reproduce exactly the invisibility this whole lane exists to fix.
    """
    if not last_status:
        return
    err = last_status.get("error")
    if err:
        print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_PREV date={last_status.get('date')} FAILED {err}", flush=True)
        return
    print(
        f"[live_odds_worker] WNBA_PREGAME_AUTORUN_PREV date={last_status.get('date')} "
        f"launched=ok runStamp={last_status.get('runStamp')} artifactsDir={last_status.get('artifactsDir')}",
        flush=True,
    )


def _launch_autorun_wnba_pregame_refresh() -> None:
    if not _wnba_pregame_refresh_enabled():
        return
    selected_date = central_today_iso()
    if not _wnba_active_for_date(selected_date):
        return
    status_path = _wnba_pregame_autorun_status_path()
    last_status = read_json_file(status_path) or {}
    # BEFORE the cadence gate, for the same reason soccer does it: the gate
    # returns on most ticks, so reporting after it would surface the previous
    # run's outcome up to 4 hours late -- most of the way back to silence.
    _report_previous_wnba_pregame_run(last_status)
    if last_status and not last_status.get("reported"):
        try:
            write_json_file(status_path, {**last_status, "reported": True})
        except Exception:  # noqa: BLE001
            pass
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_wnba_pregame_refresh_interval_seconds()):
        return
    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="wnba",
            phase="pregame",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        write_json_file(status_path, {"epoch": time.time(), "sports": "wnba", "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_FAILED {type(exc).__name__}: {exc}", flush=True)
        return
    write_json_file(
        status_path,
        {
            "epoch": time.time(),
            "sports": "wnba",
            "date": selected_date,
            "artifactsDir": (result or {}).get("artifactsDir"),
            "runStamp": (result or {}).get("runStamp"),
            "reported": False,
        },
    )
    print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_LAUNCHED date={selected_date} phase=pregame", flush=True)


def _launch_autorun_soccer_pregame_refresh() -> None:
    if not _soccer_pregame_refresh_enabled():
        return
    selected_date = central_today_iso()
    if not _soccer_active_for_date(selected_date):
        return
    status_path = _soccer_pregame_autorun_status_path()
    last_status = read_json_file(status_path) or {}
    # BEFORE the cadence gate, deliberately. The gate returns on most ticks, so
    # reporting after it would emit the previous run's outcome only on the tick
    # that launches the NEXT one -- i.e. up to 4 hours late, which is most of
    # the way back to the silence this is fixing.
    _report_previous_soccer_pregame_run(last_status)
    if last_status and not last_status.get("reported"):
        # Mark reported so the summary is emitted once, not on every tick for
        # four hours. Written back with the rest of the record intact.
        try:
            write_json_file(status_path, {**last_status, "reported": True})
        except Exception:  # noqa: BLE001
            pass
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
    # `artifactsDir` and `runStamp` are what make the NEXT tick able to report
    # this run's outcome. Without them the summary has no artifact to read and
    # the launch is once again the last thing anyone hears about the run.
    write_json_file(
        status_path,
        {
            "epoch": time.time(),
            "sports": "soccer",
            "date": selected_date,
            "runStamp": result.get("run_stamp"),
            "artifactsDir": result.get("artifacts_dir"),
            "pid": result.get("pid"),
            "reported": False,
        },
    )
    print(
        f"[live_odds_worker] SOCCER_PREGAME_AUTORUN_LAUNCHED date={selected_date} "
        f"pid={result.get('pid')} stamp={result.get('run_stamp')}",
        flush=True,
    )


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
    # Phase 2 (WNBA). Same shape and the same independence as soccer above: its
    # own interval gate makes this a no-op on every call except when due, and its
    # own try/except means a WNBA failure can never take down the soccer autorun
    # or the tick that follows.
    try:
        _launch_autorun_wnba_pregame_refresh()
    except Exception as exc:
        print(f"[live_odds_worker] WNBA_PREGAME_AUTORUN_ERROR {type(exc).__name__}: {exc}", flush=True)
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

    # THIS SERVICE BUILDS THE SOCCER ARTIFACTS, SO IT NEEDS SOCCER'S SEED FILES.
    #
    # `#145`/`#170`/`#361` fixed exactly this three times in
    # `scripts/run_refresh_worker.py`, and it came back a fourth time here
    # because the soccer sim moved to a service whose entrypoint never ran any
    # bootstrap. Measured 2026-08-15: `_launch_autorun_soccer_pregame_refresh`
    # below spawns `scripts/build_soccer_artifacts.py` on THIS worker (its PID
    # is in our own ALL_PROCESS_MEMORY payload at 02:25:48Z, matching the
    # `generated_at` on all four published recommendations files), and
    # `_load_player_rows` reads `players_*.csv` off THIS disk -- which is not
    # refresh-worker's, and which nothing seeded. Every published file carried
    # `player_props: 0`, so all 107 player-prop rows on the soccer board had no
    # projection while the committed CSVs sat correct and unread in git.
    #
    # Must run AFTER assert_refresh_state_backend_ready: it resolves the
    # destination through `refresh_state_store.data_root()`.
    #
    # Never fatal. Missing seeds degrade the sim; a seeder that can stop this
    # worker booting is strictly worse than the bug it fixes.
    try:
        from syndicate.features.soccer.seed_bootstrap import bootstrap_soccer_seed_files

        bootstrap_soccer_seed_files(log_prefix="live_odds_worker")
    except Exception as exc:
        print(
            f"[live_odds_worker] SOCCER_SEED_BOOTSTRAP_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )

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