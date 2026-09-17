"""Gunicorn hooks for the WEB service -- lane `web-memory-guard` `[2026-09-17]`.

Gunicorn loads `./gunicorn.conf.py` from its working directory by default, so this takes
effect on web without touching `render.yaml` or the start command (a `render.yaml` push is
a production change through `blueprint_sync`). Settings passed on the command line and in
`GUNICORN_CMD_ARGS` still win over anything here; this file only adds HOOKS.

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
   it waits -- unless it is over the HARD limit (limit + `SYNDICATE_WEB_WORKER_HARD_MARGIN_MB`),
   where the kernel is closer than a cold worker. Proof lines: `WEB_MEMORY_GUARD_ARMED` per
   worker, `WEB_WORKER_MEMORY_RECYCLE` per recycle, `WEB_WORKER_MEMORY_RECYCLE_DEFERRED` when
   the stagger holds one back. Switch: `SYNDICATE_WEB_WORKER_ANON_LIMIT_MB` (default 700;
   <= 0 disables).

Hooks never raise: a broken guard must not take a worker down.
"""

from __future__ import annotations

import json
import os
import random
import time

RECYCLE_STAMP_PATH = os.environ.get("SYNDICATE_WEB_WORKER_RECYCLE_STAMP") or "/tmp/syndicate_web_worker_recycle.stamp"
CHECK_EVERY_REQUESTS = 5


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
    return _env_int("SYNDICATE_WEB_WORKER_ANON_LIMIT_MB", 700)


def hard_margin_mb() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_HARD_MARGIN_MB", 150)


def min_age_seconds() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_MIN_AGE_SECONDS", 120)


def recycle_spacing_seconds() -> int:
    return _env_int("SYNDICATE_WEB_WORKER_RECYCLE_SPACING_SECONDS", 90)


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


def post_fork(server, worker) -> None:  # noqa: ARG001 - gunicorn's hook signature
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
            "anon_mb_at_fork": rss_anon_mb(),
        })
    except Exception as exc:  # never take the worker down
        _log("WEB_MEMORY_GUARD_ERROR", {"hook": "post_fork", "error": f"{type(exc).__name__}: {exc}"})


def post_request(worker, req, environ, resp) -> None:  # noqa: ARG001 - gunicorn's hook signature
    try:
        decide_recycle(worker, now=time.time(), anon_mb_reader=rss_anon_mb, stamp_path=RECYCLE_STAMP_PATH)
    except Exception as exc:  # never take the worker down
        _log("WEB_MEMORY_GUARD_ERROR", {"hook": "post_request", "error": f"{type(exc).__name__}: {exc}"})


def decide_recycle(worker, *, now: float, anon_mb_reader, stamp_path: str) -> str:
    """Returns what happened: skipped / below_limit / too_young / deferred / recycled."""
    limit = float(getattr(worker, "_syndicate_limit_mb", 0.0) or 0.0)
    if limit <= 0 or not getattr(worker, "alive", True):
        return "skipped"
    count = int(getattr(worker, "_syndicate_requests", 0)) + 1
    worker._syndicate_requests = count
    if count % CHECK_EVERY_REQUESTS:
        return "skipped"
    anon = anon_mb_reader()
    if anon is None or anon < limit:
        return "below_limit"
    age = now - float(getattr(worker, "_syndicate_born", now))
    if age < min_age_seconds():
        return "too_young"
    hard = anon >= limit + hard_margin_mb()
    other = _recent_recycle_age(now, stamp_path)
    payload = {"pid": os.getpid(), "anon_mb": round(anon, 1), "limit_mb": round(limit, 1), "hard": hard,
               "requests": count, "age_s": round(age, 1),
               "last_recycle_age_s": None if other is None else round(other, 1)}
    if not hard and other is not None and other < recycle_spacing_seconds():
        if not getattr(worker, "_syndicate_deferred_logged", False):
            worker._syndicate_deferred_logged = True
            _log("WEB_WORKER_MEMORY_RECYCLE_DEFERRED", payload)
        return "deferred"
    _touch(stamp_path)
    worker.alive = False
    _log("WEB_WORKER_MEMORY_RECYCLE", payload)
    return "recycled"
