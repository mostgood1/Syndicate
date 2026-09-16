"""refresh-worker restarts its own process when the heavy build is stuck refused.

WHY (lane `heavy-build-memory-refusal`, measured 2026-09-12/13 on refresh-worker).
After its first full board build the worker's main process keeps 2.1-2.4 GB of
anon memory and never returns it (~84% of it is not Python objects:
`UNTRACKED_BYTES_CENSUS explained_pct_of_anon=16.0`). The heavy build's guard,
`MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900`, then
refuses every cycle -- 403 times from 09-12 21:34Z to 09-13 16:14Z -- and with
it the candidate pool, board publication, paper orders and Kalshi capture. Child
jobs were NOT the cause (3,303 refused-level samples with no child process).
Every stretch ended only when the process restarted (deploys at 13:42Z, 16:23Z
and 18:31Z), after which heavy builds resumed within minutes.

The guard's 1,900 MB is roughly right, not stale: steady-state builds measured
+296 / 719 / 1,416 MB at peak (2 s watchdog), so it is not lowered. What is
added is the restart the deploys were doing by accident, under conditions that
make it harmless:

- the heavy build has been refused `N` times IN A ROW (default 15, ~30-45 min);
  only a COMPLETED candidate-pool build resets the count, so a single
  low-headroom cycle never counts;
- the process has been up at least `min_uptime` (default 30 min), so a worker that
  boots straight into refusal cannot restart-loop;
- NO child process of the worker is alive -- sims, odds jobs, soccer builds, the
  isolated overview child. This is the deploy preflight's own rule (a restart
  kills children exactly like a deploy does), and an un-enumerable process table
  is UNKNOWN, which refuses;
- no deploy drain is requested.

User decision 2026-09-13 ~19:40 CT: "Approve, default ON at 15 (Recommended)".
`SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS=0` turns it off.

A REFUSAL AT ANY GUARD COUNTS, AND PASSING THE FIRST GUARD RESETS NOTHING
(2026-09-16). The count used to be fed only by `pre_source_state_fingerprint`,
and a pass there reset it. On 2026-09-16 22:08Z-23:06Z refresh-worker's builds
passed that first guard and were then refused mid-build -- at
`post_pull_hot_artifacts` (22:23:04Z) and `post_collect_candidates_with_fallback_merge`
(22:48:30Z, 22:55:37Z), unreclaimable 2,258-2,375 MB against the 2,196 MB line --
so each cycle reset the count to 0, no recycle could fire, and the served board
stayed 60+ minutes stale. So every `_abort_build_candidate_pool_if_memory_critical`
refusal reports here (`note_heavy_build_refused`), and the reset moved to the
end of a candidate-pool build that ran every guard (`note_heavy_build_completed`).
User decision 2026-09-16: "do 1".

This module decides; it never exits the process itself. The caller (the worker's
main loop) returns from `main()`, and Render restarts the service, as
live-odds-worker's uptime recycle already does.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "recycle_after_refusals",
    "recycle_min_uptime_seconds",
    "note_heavy_build_refused",
    "note_heavy_build_completed",
    "consecutive_refusals",
    "child_process_pids",
    "recycle_decision",
]

_DEFAULT_AFTER_REFUSALS = 15
_DEFAULT_MIN_UPTIME_SECONDS = 1800

_lock = threading.Lock()
_state: dict[str, Any] = {"consecutive_refusals": 0, "total_refusals": 0, "total_completed": 0, "last_refusal_stage": None}


def recycle_after_refusals() -> int:
    """Consecutive refusals before a recycle. 0 or negative disables; junk -> default."""
    raw = str(os.environ.get("SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS") or "").strip()
    if not raw:
        return _DEFAULT_AFTER_REFUSALS
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_AFTER_REFUSALS


def recycle_min_uptime_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_REFRESH_WORKER_RECYCLE_MIN_UPTIME_SECONDS") or "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MIN_UPTIME_SECONDS
    except ValueError:
        value = _DEFAULT_MIN_UPTIME_SECONDS
    return max(0, value)


def note_heavy_build_refused(stage: str) -> int:
    """Record one heavy-build refusal at any guard. Returns the consecutive-refusal count. Never raises."""
    try:
        with _lock:
            _state["consecutive_refusals"] += 1
            _state["total_refusals"] += 1
            _state["last_refusal_stage"] = str(stage)
            return int(_state["consecutive_refusals"])
    except Exception:  # pragma: no cover - defensive
        return 0


def note_heavy_build_completed() -> None:
    """Record a candidate-pool build that ran every guard. The only reset. Never raises."""
    try:
        with _lock:
            _state["consecutive_refusals"] = 0
            _state["total_completed"] += 1
    except Exception:  # pragma: no cover - defensive
        pass


def consecutive_refusals() -> int:
    with _lock:
        return int(_state["consecutive_refusals"])


def _last_refusal_stage() -> str | None:
    with _lock:
        return _state["last_refusal_stage"]


def _reset_for_tests() -> None:
    with _lock:
        _state.update({"consecutive_refusals": 0, "total_refusals": 0, "total_completed": 0, "last_refusal_stage": None})


def child_process_pids(parent_pid: int, *, proc_root: Path = Path("/proc")) -> list[int] | None:
    """Live (non-zombie) direct children of `parent_pid`, or None when that cannot be read.

    None is UNKNOWN and the caller must treat it as "children may be running".
    A zombie (state Z) is already dead and cannot be harmed by a restart, the same
    rule `deploy_preflight.is_defunct` applies.
    """
    try:
        if not proc_root.is_dir():
            return None
        children: list[int] = []
        readable = 0
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            # /proc/<pid>/stat: "pid (comm) state ppid ...". comm may contain spaces
            # and parentheses, so split after the LAST ')'.
            tail = stat.rsplit(")", 1)[-1].split()
            if len(tail) < 2:
                continue
            readable += 1
            state, ppid = tail[0], tail[1]
            if ppid == str(parent_pid) and state != "Z":
                children.append(int(entry.name))
        return children if readable else None
    except Exception:
        return None


def recycle_decision(
    *,
    uptime_seconds: float,
    parent_pid: int,
    children_fn: Callable[[int], list[int] | None] = child_process_pids,
    drain_active_fn: Callable[[], bool] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """(recycle, reason, detail). Pure apart from the two injected reads. Never raises."""
    threshold = recycle_after_refusals()
    refusals = consecutive_refusals()
    detail: dict[str, Any] = {
        "consecutive_refusals": refusals,
        "last_refusal_stage": _last_refusal_stage(),
        "threshold": threshold,
        "uptime_s": int(uptime_seconds),
        "min_uptime_s": recycle_min_uptime_seconds(),
    }
    if threshold <= 0:
        return False, "disabled", detail
    if refusals < threshold:
        return False, "below_threshold", detail
    if uptime_seconds < detail["min_uptime_s"]:
        return False, "min_uptime", detail
    try:
        children = children_fn(parent_pid)
    except Exception:
        children = None
    if children is None:
        return False, "children_unknown", detail
    detail["children"] = len(children)
    if children:
        return False, "children_running", detail
    if drain_active_fn is None:
        try:
            from syndicate.features.shared.deploy_drain import drain_active as drain_active_fn  # type: ignore[no-redef]
        except Exception:
            drain_active_fn = None
    try:
        draining = bool(drain_active_fn()) if drain_active_fn is not None else False
    except Exception:
        draining = False
    if draining:
        return False, "drain_requested", detail
    return True, "recycle", detail


_MODULE_LOADED_AT = __import__("time").time()
_last_logged: dict[str, Any] = {"key": None}


def _process_uptime_seconds() -> float:
    """Seconds since this process booted. Prefers deploy_drain's boot stamp, which the
    worker's main loop imports on its first cycle; falls back to this module's load."""
    import time as _time

    try:
        from syndicate.features.shared.deploy_drain import _PROCESS_BOOTED_AT as booted
    except Exception:
        booted = _MODULE_LOADED_AT
    return max(0.0, _time.time() - float(booted))


def maybe_recycle(*, parent_pid: int, **kwargs: Any) -> bool:
    """Main-loop entry point: True means the caller should exit so the service restarts.

    Logs `RECYCLE_CHECK` once per (refusal count, reason) change while at or over the
    threshold, so a held-off recycle is visible without a line every poll, and
    `RECYCLE_EXIT` when it fires. Never raises.
    """
    try:
        recycle, reason, detail = recycle_decision(
            uptime_seconds=kwargs.pop("uptime_seconds", None) or _process_uptime_seconds(),
            parent_pid=parent_pid,
            **kwargs,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[worker_recycle] RECYCLE_CHECK_FAILED {type(exc).__name__}: {exc}", flush=True)
        return False
    if reason in {"disabled", "below_threshold"}:
        _last_logged["key"] = None
        return False
    key = (detail.get("consecutive_refusals"), reason)
    if recycle:
        print(f"[worker_recycle] RECYCLE_EXIT reason=heavy_build_refused {detail}", flush=True)
        return True
    if key != _last_logged["key"]:
        _last_logged["key"] = key
        print(f"[worker_recycle] RECYCLE_CHECK held={reason} {detail}", flush=True)
    return False
