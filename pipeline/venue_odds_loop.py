"""Venue price refresh on the VENUE's cadence, not the board build's.

WHY THIS EXISTS. `run_kalshi_odds_refresh()` had exactly ONE production caller
-- inside `_compute_board_publication_response` -- and
`run_polymarket_odds_refresh()` had none at all once the boot-only hook was
retired (`fcdc5c57`). So each venue's configured interval was unreachable:

    kalshi     DEFAULT_REFRESH_INTERVAL_SECONDS = 120
    polymarket DEFAULT_REFRESH_INTERVAL_SECONDS = 300
    board build period, MEASURED 2026-08-27 21:19-22:17Z: 680-874s

A 120-second interval enforced by a caller that comes around every 11-15
minutes is not a 120-second interval. The board loop was setting the venue
cadence, and the board build's period is set by OddsAPI's rate limit and the
cost of hydrating MLB -- neither of which has anything to do with how often it
is useful to re-read Kalshi's book.

WHAT THIS DOES NOT DO: it does not remove the board build's call. That call
self-gates -- `run_kalshi_odds_refresh` returns the cached markets when it is
inside its interval -- so once this loop is keeping the artifact warm, the
board build's call becomes a CACHE READ rather than a fetch, with no edit to
the build path at all. Removing it would also remove `join_to_board`'s input
for no gain.

OFF BY DEFAULT, and that is not timidity. This worker has 110 OOM kills on
record and `worker_periodic_work_never_free` is a standing rule here: `#241`
put the service into a restart loop by adding periodic work to it. So this
starts only when `SYNDICATE_VENUE_ODDS_LOOP_ENABLED` is truthy, and the
measurement comes before the default flips.

MEMORY DISCIPLINE, stated because it is the risk that matters on this service:
the refresh functions RETURN their market list, and this loop drops it on the
floor. Nothing is retained between ticks except two floats. The artifact is
the product; the return value is not.

THE TICK DOES NOT READ THE ARTIFACT. Both refresh functions decide staleness by
reading their own artifact and checking `fetched_at` -- and Kalshi's is 4.4MB
on a keyvalue backend, so calling it every tick purely to be told "cached"
would pull 4.4MB over the network every tick to avoid a fetch. This loop keeps
its own in-memory `last attempted` per venue and only calls when that says the
interval has elapsed. The refresh's own check then acts as a correctness
backstop rather than the primary gate.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

__all__ = [
    "venue_odds_loop_enabled",
    "start_venue_odds_loop",
    "stop_venue_odds_loop",
]

# How often the loop WAKES. Not how often a venue is refreshed -- each venue's
# own interval decides that. Small enough that a 120s venue interval is not
# rounded up materially, large enough to be free.
_TICK_SECONDS = 20.0

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()


def venue_odds_loop_enabled() -> bool:
    """Default OFF. See the module docstring on why this is not the default."""
    raw = (os.environ.get("SYNDICATE_VENUE_ODDS_LOOP_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, fallback: float) -> float:
    try:
        parsed = float(str(os.environ.get(name) or "").strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _venues() -> list[tuple[str, Callable[[], Any], Callable[[], float]]]:
    """(name, refresh, interval) per venue, imported lazily.

    LAZY because a venue module that cannot import must not stop the loop --
    or the other venue -- from running. Each entry is built independently and a
    failure is named and skipped, matching how every other optional subsystem
    on this worker degrades.
    """
    out: list[tuple[str, Callable[[], Any], Callable[[], float]]] = []
    try:
        from pipeline.kalshi_odds_refresh import (
            refresh_interval_seconds as kalshi_interval,
            run_kalshi_odds_refresh,
        )

        out.append(("kalshi", run_kalshi_odds_refresh, lambda: float(kalshi_interval())))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[venue_odds_loop] VENUE_UNAVAILABLE venue=kalshi {type(exc).__name__}: {exc}", flush=True)
    try:
        from pipeline.polymarket_odds_refresh import (
            refresh_interval_seconds as poly_interval,
            run_polymarket_odds_refresh,
        )

        out.append(("polymarket", run_polymarket_odds_refresh, lambda: float(poly_interval())))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[venue_odds_loop] VENUE_UNAVAILABLE venue=polymarket {type(exc).__name__}: {exc}", flush=True)
    return out


def _refresh_once(name: str, refresh: Callable[[], Any]) -> None:
    """One venue refresh. Reports, retains nothing, and never raises.

    The result is READ for its status and count and then dropped -- see the
    module docstring on memory. `status` is carried into the log because
    `cached` and `ok` are the two readings that distinguish "this loop is
    doing the work" from "the loop is running and the board build still is".
    """
    started = time.monotonic()
    try:
        result = refresh() or {}
        status = str(result.get("status") or "?")
        count = result.get("count")
        if count is None:
            markets = result.get("markets")
            count = len(markets) if isinstance(markets, list) else "?"
        reason = result.get("reason")
        print(
            f"[venue_odds_loop] REFRESH venue={name} status={status} count={count}"
            f" elapsed_s={round(time.monotonic() - started, 2)}"
            + (f" reason={reason}" if reason else ""),
            flush=True,
        )
    except Exception as exc:
        # NAMED and swallowed. A venue being unreachable must not end the loop
        # -- the next tick is a free retry, and the previous artifact is left
        # in place by the refresh functions themselves.
        print(
            f"[venue_odds_loop] REFRESH_FAILED venue={name}"
            f" elapsed_s={round(time.monotonic() - started, 2)}"
            f" {type(exc).__name__}: {exc}",
            flush=True,
        )


def _loop() -> None:
    print("[venue_odds_loop] LOOP_START tick_s=%s" % _TICK_SECONDS, flush=True)
    venues = _venues()
    if not venues:
        print("[venue_odds_loop] LOOP_EXIT reason=no_venues_available", flush=True)
        return
    # `-inf` rather than 0 so every venue refreshes on the FIRST tick instead of
    # waiting out an interval it has no reading for. A loop that starts by
    # sleeping is indistinguishable from a loop that did not start.
    last_attempt: dict[str, float] = {name: float("-inf") for name, _, _ in venues}
    while not _stop.is_set():
        now = time.monotonic()
        for name, refresh, interval in venues:
            try:
                due = interval()
            except Exception:
                due = 300.0
            if now - last_attempt[name] < due:
                continue
            # Stamped BEFORE the call, not after: a refresh that takes longer
            # than its own interval must not become a hot loop the moment it
            # returns.
            last_attempt[name] = now
            _refresh_once(name, refresh)
            if _stop.is_set():
                break
        _stop.wait(timeout=_TICK_SECONDS)
    print("[venue_odds_loop] LOOP_STOP", flush=True)


def start_venue_odds_loop() -> bool:
    """Start the loop once. True if this call started it.

    Idempotent under the same lock the stop path uses, because
    `start_intelligence_state_background_loop` is reachable from more than one
    place and two loops hitting one venue would double the request rate while
    reporting normally.
    """
    global _thread
    if not venue_odds_loop_enabled():
        print("[venue_odds_loop] DISABLED set SYNDICATE_VENUE_ODDS_LOOP_ENABLED=1 to enable", flush=True)
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="venue-odds-loop", daemon=True)
        _thread.start()
        return True


def stop_venue_odds_loop(timeout: float = 5.0) -> None:
    """Signal and join. Exists for tests; production runs it as a daemon."""
    global _thread
    with _lock:
        _stop.set()
        thread = _thread
        _thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
