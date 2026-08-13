"""`#409` phase 1 -- record what was in flight when a worker is killed.

WHY THIS EXISTS. `refresh-worker` installs no signal handler at all.
`run_live_odds_refresh_worker.py:350` installs one; `run_refresh_worker.py`
installs none. So on every deploy the process is signalled and simply dies, and
a board build that was 20 minutes into a 23-minute run leaves NOTHING behind --
no line, no artifact, no trace. The observable symptom is "the board is stale
and nobody knows why", which is what four lanes spent 2026-08-12 chasing.

`#388` gave SIMS death certificates. Builds still have none. This closes that
half.

WHAT IT DELIBERATELY DOES NOT DO. It does not drain, wait, or finish anything --
that is `#409` phase 2, and it cannot be done inside a signal handler anyway
because Render follows SIGTERM with SIGKILL after a short grace. This only
observes and records, then exits.

THE ONE REAL HAZARD, and why the exit is explicit: installing a handler CHANGES
what SIGTERM does. Today the default handler terminates the process
immediately. A handler that records and then returns would leave the worker
running, ignoring the signal, until Render SIGKILLs it -- converting a clean
stop into a hard kill and making things worse. So this records and then exits
immediately, matching today's behaviour and adding only the record.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from typing import Any

_STARTED_AT = time.time()

# Long in-process work can register itself here so the record names it. The
# board build is the intended first user and is NOT wired in -- see
# `_board_build_in_flight`, which infers it instead, because
# `pipeline/intelligence_state.py` and `syndicate/features/intelligence.py` are
# under active change by another lane and this must not conflict with them.
_IN_FLIGHT: dict[str, float] = {}
_IN_FLIGHT_LOCK = threading.Lock()


def mark_in_flight(name: str) -> None:
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT[str(name)] = time.time()


def clear_in_flight(name: str) -> None:
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT.pop(str(name), None)


# Frame names that mean a board build is running. Inferred from the stack rather
# than from a flag the build sets, so this needs no change in a file another lane
# is editing. `collect_candidates` is the span that takes 13-23 minutes
# (`intelligence.py:10026`); the others bracket it.
_BUILD_FRAME_MARKERS = (
    "collect_candidates",
    "candidate_collection_with_fallback",
    "build_candidate_pool",
    "_build_intelligence_state",
)

_INTERESTING_CHILD_MARKERS = (
    "run_mlb_daily_sim_job",
    "daily_update",
    "generate_smartsim",
    "refresh_odds_sources",
    "run_queued_refresh_job",
    "predict-date",
)


def _board_build_in_flight() -> dict[str, Any]:
    """Is a board build running, and in which frame?

    Reads live stacks via `sys._current_frames()`. Cheap (no walking of process
    memory) and safe to call from a signal handler.
    """
    out: dict[str, Any] = {"in_flight": False, "frame": None, "thread": None}
    try:
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            depth = 0
            f = frame
            while f is not None and depth < 80:
                code_name = f.f_code.co_name
                if code_name in _BUILD_FRAME_MARKERS:
                    out["in_flight"] = True
                    out["frame"] = code_name
                    out["thread"] = names.get(ident, str(ident))
                    return out
                f = f.f_back
                depth += 1
    except Exception as exc:  # pragma: no cover - must never raise in a handler
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _interesting_children() -> list[str]:
    """Sim-shaped child processes still running. Best effort."""
    found: list[str] = []
    try:
        from syndicate.features.shared.memory_observability import get_all_process_memory_snapshot

        snapshot = get_all_process_memory_snapshot() or {}
        for entry in (snapshot.get("processes") or []):
            cmd = " ".join(entry.get("cmdline") or []) if isinstance(entry.get("cmdline"), list) else str(entry.get("cmdline") or "")
            if any(marker in cmd for marker in _INTERESTING_CHILD_MARKERS):
                found.append(f"pid={entry.get('pid')} {cmd[:120]}")
    except Exception:
        pass
    return found


def _live_threads() -> list[str]:
    try:
        return sorted(t.name for t in threading.enumerate() if t.is_alive())
    except Exception:
        return []


def _safe(fn, default):
    """Every field is independently defensive.

    `build_shutdown_record` is called from a signal handler racing SIGKILL. One
    unavailable helper -- procfs missing, a thread list mutating mid-walk -- must
    cost that FIELD, not the whole record. The handler has its own try/except,
    but relying on it means one bad field discards the line that is the entire
    point of this module.
    """
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive
        return default if not isinstance(default, dict) else {**default, "error": f"{type(exc).__name__}: {exc}"}


def build_shutdown_record(worker: str, signal_name: str) -> dict[str, Any]:
    build = _safe(_board_build_in_flight, {"in_flight": False, "frame": None, "thread": None})
    with _IN_FLIGHT_LOCK:
        registered = dict(_IN_FLIGHT)
    return {
        "worker": worker,
        "signal": signal_name,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uptime_seconds": int(time.time() - _STARTED_AT),
        # Which code was actually running -- the question `#403` had to answer
        # from logs because nothing recorded it.
        "commit": str(os.environ.get("RENDER_GIT_COMMIT") or "")[:12] or None,
        "board_build": build,
        "registered_in_flight": {k: int(time.time() - v) for k, v in registered.items()},
        "children": _safe(_interesting_children, []),
        "threads": _safe(_live_threads, []),
    }


def _write_record(record: dict[str, Any]) -> None:
    """Best effort, and deliberately AFTER the print.

    The print reaches Render's log collector and is the thing that must not be
    lost; this write goes through the keyvalue-backed state store and can block
    if Redis is slow, which inside a signal handler racing SIGKILL is exactly
    where a hang costs the record.
    """
    try:
        from syndicate.features.shared.refresh_state_store import reports_root, write_json_file

        slug = str(os.environ.get("SYNDICATE_REFRESH_LANE") or record.get("worker") or "worker").strip().lower()
        slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug) or "worker"
        write_json_file(reports_root() / "refresh_status" / "latest" / f"worker_shutdown_{slug}.json", record)
    except Exception:
        pass


def install_shutdown_recorder(worker: str) -> None:
    """Install SIGTERM/SIGINT handlers that record and then exit immediately.

    Idempotent-ish: installing twice just replaces the handler.
    """

    def _handle(signum, _frame):  # noqa: ANN001
        # THE EXIT IS IN A `finally`, AND THAT IS THE WHOLE SAFETY ARGUMENT.
        #
        # Raised in review by the oversight session, and it closes the one gap
        # the tests could not: `except Exception` does NOT catch BaseException.
        # A KeyboardInterrupt from a second signal arriving mid-handler, a
        # SystemExit, anything outside the Exception hierarchy -- each would
        # escape and skip the exit, putting us back in the case this module
        # exists to avoid: SIGTERM ignored, Render escalating to SIGKILL, a
        # clean stop turned into a hard kill.
        #
        # `sys._current_frames()` inspection is the riskiest thing in here. It
        # walks live stacks in a signal context, and if it throws something
        # nobody anticipated the exit must STILL be reachable. `finally` is
        # reachable from every path including the ones nobody imagined, which
        # `except BaseException` alone is not (it does not cover a `return`).
        #
        # Same principle as `#406` putting the file cap at the bound rather than
        # in a docstring: put the guarantee where control flow cannot route
        # around it.
        try:
            try:
                name = signal.Signals(signum).name
            except BaseException:
                name = str(signum)
            record = build_shutdown_record(worker, name)
            # PRINT FIRST. This is the line that survives; everything after it is
            # a bonus racing SIGKILL.
            print(f"[worker_shutdown] WORKER_SHUTDOWN {json.dumps(record, sort_keys=True, default=str)}", flush=True)
            if record.get("board_build", {}).get("in_flight"):
                print(
                    "[worker_shutdown] WORKER_SHUTDOWN_KILLED_BOARD_BUILD "
                    f"frame={record['board_build'].get('frame')} uptime_s={record.get('uptime_seconds')} "
                    "-- this build's work is lost and will restart from zero on the next boot",
                    flush=True,
                )
            _write_record(record)
        except BaseException as exc:  # noqa: BLE001 - deliberate, see above
            try:
                print(f"[worker_shutdown] WORKER_SHUTDOWN_RECORD_FAILED {type(exc).__name__}: {exc}", flush=True)
            except BaseException:
                pass
        finally:
            os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle)
        except Exception:
            # Not all signals are installable on every platform (Windows dev
            # boxes). Never fatal -- the worker's job is not to record its own
            # death.
            pass
