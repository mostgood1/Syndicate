"""One rebuild at a time, and serve stale rather than pile up. `#632`.

WHY THIS EXISTS, measured on production 2026-09-07. `/api/intelligence/query`
runs a **5-second median and an 18-second max**, and it is one of the routes
starving web's thread pool -- 32.5% of requests exceed the 5-second health-check
budget, which is what actually restarts the instance (35 `server_failed` events,
zero `evicted=True`; web is not being OOM-killed, it is timing out).

THE CACHE IT ALREADY HAS CANNOT HELP, for two compounding reasons:

1. **No single-flight.** `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` is read and
   written with no lock between, so N concurrent misses each start their OWN
   rebuild. On a service with 8 request slots (`WEB_CONCURRENCY=2` x
   `GUNICORN_THREADS=4`), one expiry can put every slot into the same 5-18 s
   work at once -- and `/healthz` then has nowhere to run.

2. **The TTL is SHORTER THAN THE REBUILD.** `SYNDICATE_INTELLIGENCE_COMBINED_
   BOARD_CACHE_SECONDS` defaults to **15 s** while the rebuild costs 5-18 s. Past
   ~15 s the entry is stale the moment it is written, so every request rebuilds
   and the cache stops existing in any useful sense. That is a collapse mode, not
   a slow path.

WHAT THIS DOES. A fresh value is returned directly. On a miss, exactly ONE caller
per key rebuilds; the others get the previous value IMMEDIATELY if there is one,
and only block when there is nothing to serve at all (a genuinely cold key).

WHY SERVE STALE RATHER THAN WAIT. Waiting converts a thundering herd into a
queue, which still holds every thread for the length of the rebuild -- the
health check does not care whether a thread is computing or blocked. Returning
data a few seconds older costs nothing here: the TTL is already 15 s, so every
caller was accepting 15-second-old data anyway.

STALENESS IS BOUNDED AND REPORTED. `max_stale_seconds` caps how old a served
fallback may be; past that, callers wait for the rebuild rather than being handed
something arbitrarily old. Every return says which branch produced it, so a
reader is never guessing whether a number is fresh.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class SingleFlightCache:
    """TTL cache where a miss triggers ONE rebuild and others serve stale.

    Deliberately not a decorator: the caller owns the key, and the export path
    keys on `(dates, sport, limit)` which is not derivable from a function
    signature alone.
    """

    def __init__(self, *, ttl_seconds: float, max_stale_seconds: float | None = None,
                 max_entries: int = 32) -> None:
        self._ttl = float(ttl_seconds)
        # Default: tolerate serving something up to 10x the TTL old while a
        # rebuild is in flight. Past that, correctness beats latency and the
        # caller waits.
        self._max_stale = (float(max_stale_seconds) if max_stale_seconds is not None
                           else float(ttl_seconds) * 10.0)
        self._max_entries = int(max_entries)
        self._lock = threading.Lock()
        self._values: dict[Any, tuple[float, Any]] = {}
        self._building: dict[Any, threading.Event] = {}
        self.stats = {"hit": 0, "miss": 0, "stale_served": 0, "waited": 0}

    def _prune_locked(self) -> None:
        if len(self._values) <= self._max_entries:
            return
        # Oldest first. Bounded like the cache it replaces, so this cannot
        # become the memory problem the last one was capped for.
        for key, _ in sorted(self._values.items(), key=lambda kv: kv[1][0])[
                :len(self._values) - self._max_entries]:
            self._values.pop(key, None)

    def get_or_build(self, key: Any, builder: Callable[[], Any]) -> tuple[Any, str]:
        """Return `(value, source)` where source is hit|built|stale|waited.

        `builder` runs OUTSIDE the lock -- it is the 5-18 second call, and
        holding a process-wide lock across it would serialise every key and
        recreate the starvation this exists to prevent.
        """
        now = time.time()
        with self._lock:
            entry = self._values.get(key)
            if entry is not None and (now - entry[0]) < self._ttl:
                self.stats["hit"] += 1
                return entry[1], "hit"
            in_flight = self._building.get(key)
            if in_flight is None:
                # We are the one rebuild.
                event = threading.Event()
                self._building[key] = event
                self.stats["miss"] += 1
                mine = True
            else:
                event = in_flight
                mine = False
                # Somebody else is already doing this work. Serve what we have
                # rather than starting a second copy of it.
                if entry is not None and (now - entry[0]) <= self._max_stale:
                    self.stats["stale_served"] += 1
                    return entry[1], "stale"

        if not mine:
            # Nothing servable: wait for the in-flight rebuild instead of
            # launching a duplicate.
            self.stats["waited"] += 1
            event.wait(timeout=max(30.0, self._ttl * 4))
            with self._lock:
                entry = self._values.get(key)
            if entry is not None:
                return entry[1], "waited"
            # The builder failed or timed out; fall through and build, rather
            # than returning None to a caller that asked for a value.
            with self._lock:
                self._building.setdefault(key, threading.Event())
                event = self._building[key]

        try:
            value = builder()
        finally:
            with self._lock:
                self._building.pop(key, None)
            event.set()
        with self._lock:
            self._values[key] = (time.time(), value)
            self._prune_locked()
        return value, "built"

    def peek(self, key: Any) -> tuple[Any, float] | None:
        """`(value, age_seconds)` without building. For diagnostics only."""
        with self._lock:
            entry = self._values.get(key)
        if entry is None:
            return None
        return entry[1], time.time() - entry[0]

    def invalidate(self, key: Any) -> None:
        with self._lock:
            self._values.pop(key, None)

class SingleFlight:
    """Coordination WITHOUT storage: the caller keeps its own cache.

    `SingleFlightCache` above owns its values, which is wrong for the call site
    this was written for. `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` is bounded by
    ROW COUNT, not entry count, because `#632` measured it at **37.50 MB while
    obeying its 32-entry cap** -- entry size varies by orders of magnitude with
    slate size, so a cap that cannot see bytes cannot bound them. Replacing that
    store with a generic entry-capped one would reintroduce the exact bug that
    bound was added to fix. So this class coordinates and stores nothing.

    A LEASE, not a lock. The in-flight marker carries a deadline, so a builder
    that dies without calling `finish` delays the key by at most `lease_seconds`
    instead of wedging it forever. That matters because it lets a caller adopt
    this with NO `try/finally` wrapped around a 250-line function body -- the
    smaller the diff someone else has to land in their own file, the likelier it
    is to be landed correctly.
    """

    def __init__(self, *, lease_seconds: float = 60.0) -> None:
        self._lease = float(lease_seconds)
        self._lock = threading.Lock()
        self._inflight: dict[Any, tuple[float, threading.Event]] = {}

    def begin(self, key: Any) -> tuple[bool, threading.Event]:
        """`(mine, event)`. If `mine`, you are the ONE builder for this key.

        If not, wait on `event` (or serve your own stale value instead, which is
        the better move when you have one -- waiting still holds the thread).
        """
        now = time.time()
        with self._lock:
            existing = self._inflight.get(key)
            if existing is not None and existing[0] > now:
                return False, existing[1]
            # Absent, or the lease expired and the previous builder is gone.
            event = threading.Event()
            self._inflight[key] = (now + self._lease, event)
            return True, event

    def finish(self, key: Any) -> None:
        """Release the key and wake every waiter. Safe to call twice."""
        with self._lock:
            entry = self._inflight.pop(key, None)
        if entry is not None:
            entry[1].set()

    def in_flight(self, key: Any) -> bool:
        with self._lock:
            entry = self._inflight.get(key)
            return entry is not None and entry[0] > time.time()
