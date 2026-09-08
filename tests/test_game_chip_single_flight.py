"""`#632`: the chip fan-out must run ONCE per key, not once per concurrent miss.

MEASURED ON PRODUCTION 2026-09-08, which is why this exists.
`/api/board/game-chips` returned `source=inline_artifact_stale` on 5 of 5 probes,
with the worker's artifact **245-304 s old against its own 120 s threshold** and
the age growing monotonically -- i.e. the artifact path is effectively dead and
EVERY request runs `build_game_chips` inline. Observed latency ranged 305 ms (a
30 s TTL cache hit) to 5,113 ms (a real build), and **20% of organic requests to
that route exceeded the 5 s health-check budget**.

The cache could not help, for the same reason `_COMBINED_INTELLIGENCE_RESPONSE_CACHE`
could not: the read and the write were UNGUARDED, so N concurrent misses each ran
the whole per-sport (and, for soccer, per-league x 2 matchday) fan-out.

These tests run REAL THREADS. A single-flight tested sequentially has not been
tested -- the entire failure being fixed is a concurrency failure.
"""

from __future__ import annotations

import threading
import time

import syndicate.features.shared.game_chip_scoreboard as gcs


class _SlowProvider:
    """Stands in for one sport's provider. Counts fan-outs and takes time."""

    def __init__(self, counter, lock, delay):
        self._counter = counter
        self._lock = lock
        self._delay = delay

    def resolve_context(self, requested_date=None):
        class _Ctx:
            context_label = "test"
        return _Ctx()

    def is_active(self, today_value=None, context_label=None):
        return True

    def games(self, context, is_active_today=False, include_upcoming=False):
        with self._lock:
            self._counter["n"] += 1
        time.sleep(self._delay)      # stands in for the real per-sport fan-out
        return [{"game_id": "g1", "away": "AAA", "home": "BBB"}]


def _install(monkeypatch, counter, delay=0.4):
    lock = threading.Lock()
    provider = _SlowProvider(counter, lock, delay)
    monkeypatch.setattr(gcs, "_ensure_sport_data_providers", lambda: None)
    import syndicate.features.shared.sport_data_provider as sdp
    monkeypatch.setattr(sdp, "get_sport_data_provider", lambda slug: provider)
    monkeypatch.setattr(gcs, "build_game_chip", lambda slug, game: {"sport": slug, "id": "g1"})
    # A fresh cache and a fresh flight, or a previous test's entry answers this one.
    with gcs._cache_lock:
        gcs._cache.clear()
    # Reset the flight ONLY if the module has one. Deliberate: without this
    # guard these fail against the pre-fix module with AttributeError, which
    # proves the SYMBOL is missing and NOT that the behaviour is wrong -- and a
    # test that can only fail on a missing name would not catch someone keeping
    # the name and deleting the coalescing. With the guard, the pre-fix module
    # fails on the ASSERTIONS instead: 8 fan-outs where 1 is required.
    if hasattr(gcs, "_CHIP_BUILD_FLIGHT"):
        from syndicate.features.shared.single_flight import SingleFlight
        gcs._CHIP_BUILD_FLIGHT = SingleFlight(lease_seconds=120.0)


def test_concurrent_misses_produce_exactly_ONE_fanout(monkeypatch):
    """THE POINT. Eight threads is web's actual slot count
    (WEB_CONCURRENCY=2 x GUNICORN_THREADS=4). Before this, all eight fanned out."""
    counter = {"n": 0}
    _install(monkeypatch, counter)

    out = []
    threads = [threading.Thread(target=lambda: out.append(
        gcs.build_game_chips("2026-09-08", ["mlb"]))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert counter["n"] == 1, f"expected ONE fan-out across 8 threads, got {counter['n']}"
    assert len(out) == 8
    assert all(c and c[0]["sport"] == "mlb" for c in out), "every caller must get chips"


def test_a_stale_entry_is_served_INSTANTLY_rather_than_waiting(monkeypatch):
    """Serving a slightly older scoreboard beats holding a gunicorn slot for the
    length of the fan-out. The health check does not care whether a thread is
    computing or blocked."""
    counter = {"n": 0}
    _install(monkeypatch, counter, delay=0.6)
    gcs.build_game_chips("2026-09-08", ["mlb"])          # seed
    assert counter["n"] == 1

    # Age it past the TTL but well inside the stale bound (10x TTL).
    with gcs._cache_lock:
        key = next(iter(gcs._cache))
        _ts, value = gcs._cache[key]
        gcs._cache[key] = (time.monotonic() - (gcs._CACHE_TTL_SECONDS + 5.0), value)

    timings = []

    def call():
        t0 = time.time()
        gcs.build_game_chips("2026-09-08", ["mlb"])
        timings.append(time.time() - t0)

    threads = [threading.Thread(target=call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert counter["n"] == 2, f"exactly one REBUILD expected, got {counter['n'] - 1}"
    fast = [t for t in timings if t < 0.3]
    assert len(fast) >= 4, f"stale serves should be instant; timings={[round(t,3) for t in timings]}"


def test_a_cold_key_still_builds_once_and_everyone_gets_chips(monkeypatch):
    # Nothing servable: callers must WAIT for the in-flight build rather than
    # starting competing fan-outs, and must still receive a real scoreboard.
    counter = {"n": 0}
    _install(monkeypatch, counter, delay=0.5)
    out = []
    threads = [threading.Thread(target=lambda: out.append(
        gcs.build_game_chips("2026-09-08", ["nba"]))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert counter["n"] == 1
    assert all(c for c in out), "a waiter must not get an empty scoreboard"


def test_different_keys_do_not_serialise(monkeypatch):
    """A process-wide lock across the fan-out would serialise every date/sport
    combination and recreate the starvation this exists to prevent."""
    counter = {"n": 0}
    _install(monkeypatch, counter, delay=0.5)
    done = []

    def call(sport):
        gcs.build_game_chips("2026-09-08", [sport])
        done.append(sport)

    t0 = time.time()
    threads = [threading.Thread(target=call, args=(s,)) for s in ("mlb", "nba", "nhl")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    elapsed = time.time() - t0
    assert len(done) == 3
    assert elapsed < 1.2, f"three distinct keys serialised: {elapsed:.2f}s for 3x0.5s builds"


def test_a_failing_build_does_not_wedge_the_key(monkeypatch):
    counter = {"n": 0}
    _install(monkeypatch, counter)

    def boom(*_a, **_k):
        raise RuntimeError("provider registry down")

    monkeypatch.setattr(gcs, "_ensure_sport_data_providers", boom)
    for _ in range(2):
        try:
            gcs.build_game_chips("2026-09-08", ["mlb"])
        except RuntimeError:
            pass
    assert hasattr(gcs, "_CHIP_BUILD_FLIGHT"), "the single flight is gone"
    assert not gcs._CHIP_BUILD_FLIGHT.in_flight(("2026-09-08", ("mlb",))), \
        "a failed build must release the key, or every later caller waits on a dead event"
