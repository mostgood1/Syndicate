"""Gunicorn hooks for the WEB service -- lane `web-memory-guard` `[2026-09-17]`.

Gunicorn loads `./gunicorn.conf.py` from its working directory by default, so this takes
effect on web without touching `render.yaml` or the start command (a `render.yaml` push is
a production change through `blueprint_sync`). Settings passed on the command line and in
`GUNICORN_CMD_ARGS` still win over anything here; this file adds HOOKS and one setting
(`access_log_format`, see below).

WHY. Web was `oomKilled` at its 2 GiB limit 2026-09-17 16:36:52Z and was back at anon
1,684 MB / 2,047 of 2,048 MB by 17:30:11Z. Workers already auto-restart every ~1,000
requests (`--max-requests`), which under the live-odds-worker publish flood is every ~15
minutes, and still reach ~830 MB before they do.

TWO LEVERS, each with a proof line and an env switch.

1. ARENA CAP (`post_fork`). Web workers ran glibc's DEFAULT arena count: `configure_malloc_arenas`
   (`#285`, `cb3946a2`) was only ever called by the two worker entrypoints. The 2026-09-06 lanes
   measured a ~390 MB glibc arena ceiling per web worker with ~87% of it free-but-retained, and
   on 2026-09-17 17:34Z one worker held 13 arenas, 387 MB of it in secondary arenas. `mallopt`
   only governs arenas created AFTER it returns, so this must run before the worker loads the
   app and starts its request threads -- `post_fork` is exactly that point. Proof line:
   `MALLOC_ARENA_INIT` (emitted by `configure_malloc_arenas`). Switch:
   `SYNDICATE_WEB_MALLOC_ARENA_MAX` (default 2; <= 0 disables).

2. MEMORY GUARD (`post_request`). A worker whose anonymous memory (`RssAnon`) is over its limit
   stops accepting after the current request and exits gracefully; the master starts a fresh
   one. This is a ceiling, not a diagnosis: it holds whatever the cause. It never recycles a
   worker younger than `SYNDICATE_WEB_WORKER_MIN_AGE_SECONDS`, and it STAGGERS: if another
   worker in this container recycled within `SYNDICATE_WEB_WORKER_RECYCLE_SPACING_SECONDS`,
   it waits. Over the HARD limit (limit + `SYNDICATE_WEB_WORKER_HARD_MARGIN_MB`) it waits only
   `SYNDICATE_WEB_WORKER_HARD_RECYCLE_SPACING_SECONDS` (see `decide_recycle`), and not at all
   over the EMERGENCY ceiling (hard limit + `SYNDICATE_WEB_WORKER_EMERGENCY_MARGIN_MB`). Proof lines: `WEB_MEMORY_GUARD_ARMED` per
   worker, `WEB_WORKER_MEMORY_RECYCLE` per recycle, `WEB_WORKER_MEMORY_RECYCLE_DEFERRED` when
   the stagger holds one back. Switch: `SYNDICATE_WEB_WORKER_ANON_LIMIT_MB` (default 650, sized for overshoot;
   <= 0 disables).

Hooks never raise: a broken guard must not take a worker down.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time

RECYCLE_STAMP_PATH = os.environ.get("SYNDICATE_WEB_WORKER_RECYCLE_STAMP") or "/tmp/syndicate_web_worker_recycle.stamp"
CHECK_EVERY_REQUESTS = 5

# THE ACCESS LOG CARRIES EACH REQUEST'S DURATION -- lane `web-access-log-durations`
# `[2026-09-22]`. Gunicorn's default format plus `%(M)s` (request time in ms). Web
# runs 8 request slots (2 workers x 4 threads) and ~43% of its deploys since
# 2026-09-15 were followed by `/healthz` timeouts when those slots filled
# (lane `web-flap-0922`); the log could COUNT the requests in flight but not say
# which ones held a slot for seconds. `GUNICORN_CMD_ARGS` sets `--access-logfile -`
# and no format, so this setting applies; a command-line format would override it.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(M)sms'

# A RECYCLING WORKER SERVES WHAT IT ALREADY ACCEPTED -- lane `web-worker-drain-on-recycle`
# `[2026-10-01]`. Stock gthread exits by closing its poller with accepted-but-unread
# connections still in it, so every recycle (the memory guard below, `--max-requests`,
# SIGTERM) could reset a request: the local-fleet audit sweep got ConnectionResetError
# after 0.0s the second worker 181021 recycled, and an isolated repro failed 101-106 of
# 4,000 requests per round with stock gthread vs 0 with this worker. See
# `syndicate/web_worker.py`. Applies only when no `--worker-class`/`-k` is given on the
# command line. Switch: `SYNDICATE_WEB_WORKER_DRAIN` (default on; 0/false/off restores
# stock gthread, which gunicorn picks itself because `--threads` > 1).
if str(os.environ.get("SYNDICATE_WEB_WORKER_DRAIN") or "").strip().lower() not in {"0", "false", "no", "off"}:
    worker_class = "syndicate.web_worker.DrainingThreadWorker"

# A HUP LOADS THE WORKER CLASS FRESH -- lane `web-restart-healthz` `[2026-10-06]`.
# The MASTER imports `worker_class` and forks every worker from itself, so a change
# to `syndicate/web_worker.py` used to need a full master restart: on HUP gunicorn
# re-reads this file and re-resolves the class, but `import_module` returned the copy
# cached at boot and the new workers ran the OLD class. This file runs again on every
# HUP, so dropping the cached module here makes `local_production.py reload-web`
# (HUP, never refused) load worker-class changes too. Only the master holds it
# before the fork; a worker already running is untouched.
sys.modules.pop("syndicate.web_worker", None)


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        # A typo must not silently disable the guard.
        return default


def arena_max() -> int:
    return _env_int("SYNDICATE_WEB_MALLOC_ARENA_MAX", 2)


def anon_limit_mb() -> int:
    """Default 650 MB, sized for OVERSHOOT, not for the limit.

    MEASURED 2026-09-17 on the first two recycles (18:01:54Z, 18:04:08Z): pid 41 crossed at
    666.7 MB against a 666.0 limit, but pid 40 crossed at 723.2 against 678.4 -- **44.8 MB
    above it**. At the ~1.3 MB/request growth of that window, a 5-request check interval
    explains ~7 MB, so the rest is ONE request allocating tens of MB (a board build or a
    multi-MB publish). Checking more often would not have caught it; leaving room would.
    Worst case then is 2 x (650 + ~100) = ~1,500 MB against the 2,048 MB limit, plus the
    master (~30 MB) and up to two merge children (~100-200 MB each).
    """
    return _env_int("SYNDICATE_WEB_WORKER_ANON_LIMIT_MB", 650)


def hard_margin_mb() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_HARD_MARGIN_MB", 150)


def min_age_seconds() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_MIN_AGE_SECONDS", 120)


def recycle_spacing_seconds() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_RECYCLE_SPACING_SECONDS", 90)


# A HARD RECYCLE WAITS FOR THE OTHER WORKER'S REPLACEMENT -- lane `web-silent-worker-kills`
# `[2026-11-18]`. A hard recycle used to skip the stagger outright ("the kernel is closer than a
# cold worker"), which was true on Render: one 2 GiB container held both workers. So two workers
# over the hard limit recycled together and web had NO booted worker until a replacement came up:
# 18:48:01.6Z and 18:48:03.3Z 2026-11-18, replacements booted 18:48:09.4Z and 18:48:31.0Z (the
# portfolio probe's reads stalled 4-12 s). Measured: 2-59 such doubles (< 30 s apart) a day
# 11-05..11-18, every one hard, the second worker 150-777 MB over its limit.
# On the fleet the web role has no memory cap of its own (cgroup `memory.max` = max, read
# 2026-11-18 19:3xZ; the WSL VM has 15.7 GB), so a short wait is cheap. A hard recycle within
# this many seconds of another worker's recycle waits, re-checking on EVERY request, not every
# 5th, so at most one request's growth lands past the threshold; 30 s covers the replacement's
# boot (1-28 s measured that day). <= 0 restores the old behaviour.
def hard_recycle_spacing_seconds() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_HARD_RECYCLE_SPACING_SECONDS", 30)


# ...unless it is this far over the HARD limit: then it goes at once, stagger or not. 600 MB
# puts the ceiling at ~1.4 GB per worker; one second worker of the 400+ doubles since 11-05 was
# that far over (777 MB on 11-14).
def emergency_margin_mb() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_EMERGENCY_MARGIN_MB", 600)


def _log(event: str, payload: dict) -> None:
    print(f"{event} {json.dumps(payload, sort_keys=True, default=str)}", flush=True)


def rss_anon_mb(status_path: str = "/proc/self/status") -> float | None:
    """The process's anonymous resident memory in MB, or None where /proc is unavailable."""
    try:
        with open(status_path, "r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("RssAnon:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def _recent_recycle_age(now: float, stamp_path: str) -> float | None:
    try:
        return now - os.path.getmtime(stamp_path)
    except OSError:
        return None


def _touch(stamp_path: str) -> None:
    try:
        with open(stamp_path, "a", encoding="ascii"):
            pass
        os.utime(stamp_path, None)
    except OSError:
        pass


# NO AUTOMATIC FULL COLLECTIONS IN A WEB WORKER (lane `web-silent-worker-kills`, 2026-11-23, user "Tune GC next").
# A full (generation 2) collection holds the GIL while it walks the whole heap, so every thread stops -- the main
# loop included, and its heartbeat is what the master's 60 s kill reads. Measured from `WEB_GC_PAUSE` (>= 0.25 s):
#   * 3,344 / 3,830 / 4,262 full collections a CST day on 11-20 / 11-21 / 11-22, 1,910-3,039 s of pause a day;
#   * they were 4 of the 7 main-loop stalls >= 5 s in the 22 h after 11-21 20:14Z, and the longest, 18.57 s: worker
#     2641469 at 1,199 MB (6:22 PM CST 11-21). The pause grows with the heap, and the memory guard only checks
#     on requests, so a quiet worker's heap is not bounded (that one had served 10 requests in 79 min);
#   * 7,079 objects in all over 11,989 logged full collections 11-20 17:03Z..11-23 14:03Z. That counts OBJECTS, not
#     bytes: one cyclic container can hold a 36 MB decoded state, so it never showed they free nothing.
# CPython 3.11 (the fleet's) runs one whenever the survivors since the last exceed a quarter of the long-lived
# count, and the board warmer's rebuilds keep that true about once a minute per worker.
# The tuning keeps the young collections (generations 0 and 1) and never starts a full one on its own. Cost: a cycle
# that reaches the old generation stays until the worker recycles. An explicit `gc.collect()` still runs one.
# REVERTED TO CPYTHON'S OWN BY DEFAULT 2026-11-24 (user "Yes, revert it"). On its first day (loaded 14:17Z 11-23) it
# removed every full collection, but stalls >= 5 s stayed 3 against 3, and a tuned worker 5 min old reached ~9.7 GB
# and was killed by the kernel OOM killer (1:28:53 PM CST 11-23): the only kill without a WORKER TIMEOUT since 11-01.
# The memory guard checks only every 5th request, so nothing bounded it. One event does not prove the tuning caused
# it, but with full collections off only a recycle frees old cyclic garbage.
# Switch: `SYNDICATE_WEB_GC_AUTO_FULL` -- absent / 1 / on = CPython's own (default); 0 / false / off / no = the tuning.
# Proof line: `WEB_GC_TUNED` per worker (`applied` false by default); `WEB_WORKER_FAST_EXIT` carries the collections
# per generation since the fork, so a full collection is counted, not merely inferred from the pause log.
GC_FULL_THRESHOLD_OFF = 2**31 - 1


def gc_auto_full_enabled() -> bool:
    """CPython's automatic full collections stay ON unless the switch says off. Absent = on (since 2026-11-24)."""
    return str(os.environ.get("SYNDICATE_WEB_GC_AUTO_FULL") or "").strip().lower() not in {"0", "false", "off", "no"}


def _gc_collections(gc_module) -> list[int]:
    return [int(stats.get("collections", 0)) for stats in gc_module.get_stats()]


def tune_gc(worker=None, *, gc_module=None) -> dict:
    """Stop automatic full collections in this process only when `SYNDICATE_WEB_GC_AUTO_FULL` is off (default: leave
    CPython's own). Returns the `WEB_GC_TUNED` payload either way."""
    import gc

    g = gc_module or gc
    before = list(g.get_threshold())
    payload = {"pid": os.getpid(), "before": before}
    if worker is not None:
        worker._syndicate_gc_at_fork = _gc_collections(g)
    if gc_auto_full_enabled():
        payload.update(applied=False, reason="SYNDICATE_WEB_GC_AUTO_FULL", after=before)
        return payload
    g.set_threshold(before[0], before[1], GC_FULL_THRESHOLD_OFF)
    payload.update(applied=True, after=list(g.get_threshold()))
    return payload


def post_fork(server, worker) -> None:  # noqa: ARG001 - gunicorn's hook signature
    try:
        _log("WEB_GC_TUNED", tune_gc(worker))
    except Exception as exc:  # never take the worker down
        _log("WEB_MEMORY_GUARD_ERROR", {"hook": "post_fork_gc", "error": f"{type(exc).__name__}: {exc}"})
    try:
        worker._syndicate_born = time.time()
        worker._syndicate_requests = 0
        # Jitter the limit per worker so two workers that grow together do not cross it on
        # the same request.
        limit = anon_limit_mb()
        worker._syndicate_limit_mb = limit * random.uniform(0.95, 1.0) if limit > 0 else 0.0
        arenas = arena_max()
        applied = None
        if arenas > 0:
            from syndicate.features.shared.memory_observability import configure_malloc_arenas

            applied = configure_malloc_arenas(arenas)
        _log("WEB_MEMORY_GUARD_ARMED", {
            "pid": os.getpid(),
            "arena_max": arenas,
            "arena_cap_applied": applied,
            "anon_limit_mb": round(worker._syndicate_limit_mb, 1),
            "hard_margin_mb": hard_margin_mb(),
            "min_age_s": min_age_seconds(),
            "spacing_s": recycle_spacing_seconds(),
            "hard_spacing_s": hard_recycle_spacing_seconds(),
            "emergency_margin_mb": emergency_margin_mb(),
            "anon_mb_at_fork": rss_anon_mb(),
        })
    except Exception as exc:  # never take the worker down
        _log("WEB_MEMORY_GUARD_ERROR", {"hook": "post_fork", "error": f"{type(exc).__name__}: {exc}"})


def post_request(worker, req, environ, resp) -> None:  # noqa: ARG001 - gunicorn's hook signature
    try:
        decide_recycle(worker, now=time.time(), anon_mb_reader=rss_anon_mb, stamp_path=RECYCLE_STAMP_PATH)
    except Exception as exc:  # never take the worker down
        _log("WEB_MEMORY_GUARD_ERROR", {"hook": "post_request", "error": f"{type(exc).__name__}: {exc}"})


# THE LOOP-STALL BLACK BOX -- lane `web-silent-worker-kills` `[2026-11-18]`.
#
# WHAT IT CATCHES. On 2026-11-17 gunicorn killed 4 web workers with `WORKER TIMEOUT` (15:23,
# 16:38, 16:49, 21:36Z; 0 a day on 11-12..11-16) while they were alive and serving: none had
# the `WEB_WORKER_MEMORY_RECYCLE` / `WEB_WORKER_DRAINED` lines of the older drain-path kills.
# The master kills a worker whose heartbeat (`worker.notify()`, called once per turn of the
# worker's main loop in `syndicate/web_worker.py`) is 60 s old, so for 60 s that loop did not
# turn. The logs cannot say why:
#   * each kill took ONE worker, while both heartbeat files share one filesystem, so a disk
#     stall long enough to miss the heartbeat would have taken both -- and 3 of the 4 came after
#     C: had been relieved (37-130 GB free);
#   * the main loop's own calls are short by construction (non-blocking sockets; the fast
#     /healthz answer is bounded by a 2 s send timeout);
#   * which leaves a thread in the SAME process holding the GIL in one long C call, or a main-
#     loop call blocking in a way the code does not show. Only a stack of every thread, taken
#     while the loop is stuck, separates those.
#
# HOW. `faulthandler.dump_traceback_later` runs a C watchdog thread that writes every Python
# thread's stack to fd 2 WITHOUT needing the GIL. Each heartbeat re-arms it (at most every
# `STALL_DUMP_REARM_SECONDS`, so a busy loop does not churn its thread), so it fires only when
# the loop has not turned for `stall_dump_seconds()` -- 40 s by default, always at least 10 s
# before the master's kill. A loop that recovers just leaves the dump behind; one that does not
# is killed ~20 s later with its stack already in web.log. The dump starts with
# `Timeout (0:00:40)!`; the worker's pid is in the `WEB_LOOP_STALL_DUMP_ARMED` line it printed
# at boot. Switch: `SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS` (0 disables).
STALL_DUMP_REARM_SECONDS = 5.0


def stall_dump_seconds(kill_timeout: float) -> float:
    """Seconds without a loop turn before the stack dump: the env value (default 40), always at
    least 10 s inside the master's kill timeout and never under 1 s. 0 or less disables it."""
    raw = str(os.environ.get("SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS") or "").strip()
    try:
        wanted = float(raw) if raw else 40.0
    except ValueError:
        wanted = 40.0
    if wanted <= 0:
        return 0.0
    ceiling = max(1.0, float(kill_timeout or 0) - 10.0)
    return max(1.0, min(wanted, ceiling))


def install_loop_stall_dump(worker, *, now=time.monotonic, dump_later=None, stream=None) -> str:
    """Wrap `worker.notify` so every heartbeat re-arms the stall dump. Returns armed / disabled."""
    import faulthandler

    seconds = stall_dump_seconds(float(getattr(worker.cfg, "timeout", 0) or 0))
    if seconds <= 0:
        return "disabled"
    arm = dump_later or faulthandler.dump_traceback_later
    out = stream or getattr(sys, "__stderr__", None) or sys.stderr
    original = worker.notify
    state = {"armed_at": None}

    def notify() -> None:
        original()
        t = now()
        if state["armed_at"] is None or t - state["armed_at"] >= STALL_DUMP_REARM_SECONDS:
            arm(seconds, repeat=False, file=out, exit=False)
            state["armed_at"] = t

    worker.notify = notify
    _log("WEB_LOOP_STALL_DUMP_ARMED", {
        "pid": os.getpid(),
        "dump_after_s": seconds,
        "rearm_every_s": STALL_DUMP_REARM_SECONDS,
        "kill_timeout_s": float(getattr(worker.cfg, "timeout", 0) or 0),
    })
    return "armed"


# WHICH CALL HOLDS THE GIL, AND IS IT REALLY WORKING (lane `web-silent-worker-kills`, 2026-11-20).
# The 16:08:10Z 11-20 dump named the stalled call: a request thread inside ONE `json.loads` at
# `pipeline/intelligence_state.py:4613` (`_decompress_oversized_values`, the board query's cold
# board read) held the GIL for 40+ s, and live /proc sampling showed that thread at a full core
# with the main loop locked out. The same decode takes 0.3-1.1 s in a side process. Three things
# fit and need separating before a fix: a cyclic-GC pause fired inside the decode, the decode
# itself, or the host starving that vCPU. Two log lines separate them, both instruments only:
#   * `WEB_LOOP_STALL` -- logged by the main thread when its heartbeat resumes after a gap of
#     `loop_stall_log_seconds()` (5 s) or more: the gap, and the PROCESS CPU used during it. A
#     ratio near 1.0 is one thread burning a full core; far below it is a starved process.
#   * `WEB_GC_PAUSE` -- every collection of `gc_pause_log_seconds()` (0.25 s) or more: its
#     generation, wall pause, the CPU the collecting thread spent in it, and which thread.
# Switches: `SYNDICATE_WEB_LOOP_STALL_LOG_SECONDS`, `SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS` (0 disables).
def _float_env(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        return max(0.0, float(raw)) if raw else default
    except ValueError:
        return default


def loop_stall_log_seconds() -> float:
    return _float_env("SYNDICATE_WEB_LOOP_STALL_LOG_SECONDS", 5.0)


def gc_pause_log_seconds() -> float:
    return _float_env("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", 0.25)


def install_loop_stall_log(worker, *, now=time.monotonic, cpu=time.process_time) -> str:
    """Wrap `worker.notify` so a heartbeat that ends a long gap logs `WEB_LOOP_STALL`. Returns armed / disabled."""
    threshold = loop_stall_log_seconds()
    if threshold <= 0:
        return "disabled"
    import threading

    original = worker.notify
    state = {"t": now(), "cpu": cpu()}

    def notify() -> None:
        original()
        t, c = now(), cpu()
        gap = t - state["t"]
        if gap >= threshold:
            _log("WEB_LOOP_STALL", {"pid": os.getpid(), "gap_s": round(gap, 2),
                                    "process_cpu_s": round(c - state["cpu"], 2),
                                    "cpu_per_wall": round((c - state["cpu"]) / gap, 2) if gap > 0 else None,
                                    "threads": threading.active_count()})
        state["t"], state["cpu"] = t, c

    worker.notify = notify
    return "armed"


# NEVER WRITE FROM INSIDE A GC CALLBACK (the 2026-11-20 20:01:56Z kill, pid 1860718). A collection runs on
# whichever allocation crosses the threshold -- including one inside `StampedStream.write`
# (`scripts/local_logstamp/sitecustomize.py`), which holds a NON-reentrant lock around its timestamp. The first
# version of this hook printed from the callback: the board warmer's own print fired a full collection inside
# that lock, the hook's print re-entered `write` on the same thread and waited on itself forever, every thread
# that printed after it queued on the same lock, and the main loop joined them at its first fast-healthz line;
# the master killed the worker 60 s later (dump: every thread at sitecustomize.py:47). A worker whose main loop
# never printed again would have kept heartbeating, accepting connections it could never answer. So the
# callback only appends to a bounded deque (no I/O, no lock) and the main loop's heartbeat writes the lines.
GC_PAUSE_QUEUE_CAP = 256


def install_gc_pause_log(worker=None, *, now=time.perf_counter, thread_cpu=time.thread_time, callbacks=None,
                         clock=time.monotonic) -> str:
    """Add a `gc.callbacks` hook that QUEUES `WEB_GC_PAUSE` for long collections, and wrap `worker.notify` so each
    heartbeat writes what is queued. Returns armed / disabled."""
    import collections
    import gc
    import threading

    threshold = gc_pause_log_seconds()
    if threshold <= 0:
        return "disabled"
    started: dict[str, float] = {}
    pending: collections.deque = collections.deque()
    dropped = [0]

    def on_gc(phase, info) -> None:
        try:
            if phase == "start":
                started["t"], started["cpu"] = now(), thread_cpu()
                return
            t0 = started.pop("t", None)
            if t0 is None:
                return
            pause = now() - t0
            if pause < threshold:
                return
            if len(pending) >= GC_PAUSE_QUEUE_CAP:
                dropped[0] += 1
                return
            pending.append({"pid": os.getpid(), "generation": info.get("generation"),
                            "pause_s": round(pause, 3),
                            "thread_cpu_s": round(thread_cpu() - started.pop("cpu", 0.0), 3),
                            "collected": info.get("collected"), "uncollectable": info.get("uncollectable"),
                            "thread": threading.current_thread().name, "_queued_at": clock()})
        except Exception:  # a GC callback must never raise
            pass

    def drain() -> None:
        while pending:
            try:
                payload = pending.popleft()
            except IndexError:
                return
            payload["written_after_s"] = round(clock() - payload.pop("_queued_at", clock()), 2)
            if dropped[0]:
                payload["dropped_before"], dropped[0] = dropped[0], 0
            _log("WEB_GC_PAUSE", payload)

    if worker is not None:
        original = worker.notify

        def notify() -> None:
            original()
            if pending:
                drain()

        worker.notify = notify
    (gc.callbacks if callbacks is None else callbacks).append(on_gc)
    return "armed"


def post_worker_init(worker) -> None:
    try:
        install_loop_stall_dump(worker)
    except Exception as exc:  # never take the worker down
        _log("WEB_LOOP_STALL_DUMP_ERROR", {"hook": "post_worker_init", "error": f"{type(exc).__name__}: {exc}"})
    try:
        _log("WEB_STALL_INSTRUMENTS_ARMED", {"pid": os.getpid(),
                                             "loop_stall_log": install_loop_stall_log(worker),
                                             "loop_stall_log_s": loop_stall_log_seconds(),
                                             "gc_pause_log": install_gc_pause_log(worker),
                                             "gc_pause_log_s": gc_pause_log_seconds()})
    except Exception as exc:  # never take the worker down
        _log("WEB_LOOP_STALL_DUMP_ERROR", {"hook": "stall_instruments", "error": f"{type(exc).__name__}: {exc}"})


# EXIT WITHOUT CPYTHON'S SHUTDOWN (lane `web-silent-worker-kills`, 2026-11-21).
# The 17:04:54Z 11-21 dump was ONE thread with `<no Python frame>`. Worker 2300114 had logged
# `Worker exiting` at 17:04:19Z after a normal memory recycle (1,289 MB anon). It then spent ~55 s
# inside CPython's own interpreter shutdown, and was reaped ~5 s before the master's 60 s kill:
#   * a single thread means the other thread states were already deleted, so it was past atexit;
#   * no Python frame means it was in C: the final collection and the teardown of a ~1.3 GB heap.
# Since 10-31, 5,296 exits: median 1.5 s from `Worker exiting` to the replacement booting, p99 9.2 s.
# 5 more were KILLED in that shutdown (10-31..11-11), 30-60 s after `Worker exiting`. Until a worker
# is reaped its slot is not refilled: web ran on one worker for ~55 s.
# A web worker whose loop has returned has nothing to hand over:
#   * the drain is done and every request future has finished;
#   * the only atexit work web registers releases flock()s, which the kernel drops with the fds;
#   * the warmer thread is a daemon, which the stock shutdown never joins either.
# So `worker_exit` flushes stdio and leaves with `os._exit(0)`, but only when the loop RETURNED with
# nothing in flight. A worker that failed to boot, raised out of its loop or still has a request
# running exits the stock way, so exit codes 3 / 4 still halt the arbiter.
# Switch: `SYNDICATE_WEB_WORKER_FAST_EXIT` (0 / false / off restores the stock exit).
def fast_exit_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_WEB_WORKER_FAST_EXIT") or "").strip().lower() not in {"0", "false", "off", "no"}


def worker_exit(server, worker, *, exit_now=None, streams=None, clock=time.monotonic, gc_module=None) -> str:  # noqa: ARG001
    """gunicorn's child-side exit hook, after `Worker exiting`. Returns why it left it to the stock exit; on the fast
    path it does not return."""
    try:
        if not fast_exit_enabled():
            return "disabled"
        returned_at = getattr(worker, "_syndicate_run_returned_at", None)
        if returned_at is None:
            return "loop_did_not_return"
        running = sum(1 for fut in list(getattr(worker, "futures", None) or ()) if not fut.done())
        if running:
            _log("WEB_WORKER_STOCK_EXIT", {"pid": os.getpid(), "reason": "request_running", "running": running})
            return "request_running"
        payload = {"pid": os.getpid(), "after_loop_s": round(clock() - float(returned_at), 3)}
        at_fork = getattr(worker, "_syndicate_gc_at_fork", None)
        if at_fork:
            try:
                import gc

                now_counts = _gc_collections(gc_module or gc)
                payload["gc_collections"] = [now - then for now, then in zip(now_counts, at_fork)]
            except Exception:  # a count is evidence, never a reason to stay in shutdown
                pass
        _log("WEB_WORKER_FAST_EXIT", payload)
        for stream in (streams if streams is not None else (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)):
            try:
                stream.flush()
            except Exception:  # a closed stream must not keep the worker in shutdown
                pass
    except Exception as exc:  # never raise into gunicorn: the stock exit is the fallback
        try:
            _log("WEB_WORKER_STOCK_EXIT", {"pid": os.getpid(), "reason": "error", "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
        return "error"
    (exit_now or os._exit)(0)
    return "exited"


def decide_recycle(worker, *, now: float, anon_mb_reader, stamp_path: str) -> str:
    """Returns what happened: skipped / below_limit / too_young / deferred / deferred_hard / recycled."""
    limit = float(getattr(worker, "_syndicate_limit_mb", 0.0) or 0.0)
    if limit <= 0 or not getattr(worker, "alive", True):
        return "skipped"
    count = int(getattr(worker, "_syndicate_requests", 0)) + 1
    worker._syndicate_requests = count
    # A worker holding back a HARD recycle checks on every request until it goes.
    if count % CHECK_EVERY_REQUESTS and not getattr(worker, "_syndicate_hard_pending", False):
        return "skipped"
    anon = anon_mb_reader()
    if anon is None or anon < limit:
        # A dip ends any hold: a later hard crossing is a NEW hold, logged and timed from its own start.
        worker._syndicate_hard_pending = False
        worker._syndicate_hard_deferred_at = None
        return "below_limit"
    age = now - float(getattr(worker, "_syndicate_born", now))
    if age < min_age_seconds():
        return "too_young"
    hard = anon >= limit + hard_margin_mb()
    emergency = anon >= limit + hard_margin_mb() + emergency_margin_mb()
    other = _recent_recycle_age(now, stamp_path)
    payload = {"pid": os.getpid(), "anon_mb": round(anon, 1), "limit_mb": round(limit, 1), "hard": hard,
               "emergency": emergency, "requests": count, "age_s": round(age, 1),
               "last_recycle_age_s": None if other is None else round(other, 1)}
    if not hard and other is not None and other < recycle_spacing_seconds():
        if not getattr(worker, "_syndicate_deferred_logged", False):
            worker._syndicate_deferred_logged = True
            _log("WEB_WORKER_MEMORY_RECYCLE_DEFERRED", payload)
        return "deferred"
    hard_spacing = hard_recycle_spacing_seconds()
    if hard and not emergency and hard_spacing > 0 and other is not None and other < hard_spacing:
        worker._syndicate_hard_pending = True
        if getattr(worker, "_syndicate_hard_deferred_at", None) is None:
            worker._syndicate_hard_deferred_at = now
            _log("WEB_WORKER_MEMORY_RECYCLE_DEFERRED", {**payload, "hard_spacing_s": hard_spacing})
        return "deferred_hard"
    held_since = getattr(worker, "_syndicate_hard_deferred_at", None)
    if held_since is not None:
        payload["hard_deferred_s"] = round(now - held_since, 1)
    _touch(stamp_path)
    worker.alive = False
    _log("WEB_WORKER_MEMORY_RECYCLE", payload)
    return "recycled"
