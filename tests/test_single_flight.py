"""`#632`: one rebuild at a time, and serve stale rather than pile up.

`/api/intelligence/query` runs a 5 s median and 18 s max. Its cache cannot help,
for two compounding reasons measured in the code: the read and the write are
UNGUARDED, so N concurrent misses each start their own rebuild; and the TTL
defaults to 15 s while the rebuild costs 5-18 s, so past ~15 s the entry is stale
the moment it is written and every request rebuilds.

These tests run REAL THREADS. A single-flight cache that is only tested
sequentially has not been tested at all -- the entire failure being fixed is a
concurrency failure.
"""

from __future__ import annotations

import threading
import time

from syndicate.features.shared.single_flight import SingleFlightCache


def test_a_fresh_value_is_served_without_building():
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return "v1"

    c = SingleFlightCache(ttl_seconds=60)
    assert c.get_or_build("k", build) == ("v1", "built")
    assert c.get_or_build("k", build)[1] == "hit"
    assert calls["n"] == 1


def test_concurrent_misses_produce_exactly_ONE_rebuild():
    """THE POINT. Eight threads is web's actual slot count
    (WEB_CONCURRENCY=2 x GUNICORN_THREADS=4). Today all eight would rebuild."""
    calls = {"n": 0}
    started = threading.Event()

    def build():
        calls["n"] += 1
        started.set()
        time.sleep(0.4)          # stands in for the 5-18 second rebuild
        return "value"

    c = SingleFlightCache(ttl_seconds=60)
    # Seed a value so the others have something stale to serve.
    c.get_or_build("k", lambda: "old")
    time.sleep(0.01)
    # Stale relative to the TTL (60 s) but INSIDE max_stale (10x TTL = 600 s),
    # so it is servable. My first version aged it 999 s, past that bound -- the
    # cache correctly refused to serve it and every caller waited instead, which
    # is the bound working, not the single-flight failing.
    c._values["k"] = (time.time() - 120, "old")

    results = []
    threads = [threading.Thread(target=lambda: results.append(c.get_or_build("k", build)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert calls["n"] == 1, f"expected ONE rebuild across 8 threads, got {calls['n']}"
    assert len(results) == 8
    # Seven got the stale value instantly; one did the work.
    assert sum(1 for _v, src in results if src == "stale") >= 6
    assert sum(1 for _v, src in results if src == "built") == 1


def test_a_cold_key_waits_rather_than_duplicating_the_work():
    # With nothing servable, a second caller must WAIT for the in-flight build,
    # not start a competing one -- serving stale is impossible when there is no
    # stale value.
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        time.sleep(0.3)
        return "cold"

    c = SingleFlightCache(ttl_seconds=60)
    out = []
    threads = [threading.Thread(target=lambda: out.append(c.get_or_build("cold", build)))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert calls["n"] == 1, f"a cold key must still build once, got {calls['n']}"
    assert all(v == "cold" for v, _s in out)
    assert sum(1 for _v, s in out if s == "waited") == 3


def test_stale_is_bounded_so_nothing_arbitrarily_old_is_served():
    c = SingleFlightCache(ttl_seconds=1, max_stale_seconds=2)
    c.get_or_build("k", lambda: "old")
    c._values["k"] = (time.time() - 60, "old")      # far past max_stale

    def build():
        time.sleep(0.2)
        return "new"

    # Mark a rebuild in flight, as a concurrent caller would.
    c._building["k"] = threading.Event()
    t = threading.Thread(target=lambda: (time.sleep(0.05), c._building.pop("k", None),
                                         c._values.__setitem__("k", (time.time(), "new"))))
    t.start()
    value, source = c.get_or_build("k", build)
    t.join(timeout=5)
    # It must NOT have served the 60-second-old value.
    assert source != "stale", "a value past max_stale must not be served"
    assert value == "new"


def test_the_builder_runs_outside_the_lock():
    """Holding a process-wide lock across a 5-18 second rebuild would serialise
    every key and recreate the starvation this exists to prevent."""
    c = SingleFlightCache(ttl_seconds=60)
    other_key_done = threading.Event()

    def slow_build():
        # While THIS is building, a different key must still be servable.
        t = threading.Thread(target=lambda: (c.get_or_build("other", lambda: "b"),
                                             other_key_done.set()))
        t.start()
        t.join(timeout=5)
        return "a"

    c.get_or_build("a", slow_build)
    assert other_key_done.is_set(), "a second key blocked behind the first key's build"


def test_a_failing_builder_does_not_wedge_the_key():
    c = SingleFlightCache(ttl_seconds=60)
    boom = {"n": 0}

    def bad():
        boom["n"] += 1
        raise RuntimeError("upstream down")

    for _ in range(2):
        try:
            c.get_or_build("k", bad)
        except RuntimeError:
            pass
    # The in-flight marker must be cleared, or every later caller waits forever
    # on an event that will never be set.
    assert "k" not in c._building
    assert boom["n"] == 2, "a failed build must not leave the key permanently locked"


def test_entries_are_bounded():
    c = SingleFlightCache(ttl_seconds=60, max_entries=4)
    for i in range(12):
        c.get_or_build(f"k{i}", lambda i=i: i)
    assert len(c._values) <= 4


def test_stats_distinguish_the_branches():
    # A reader must be able to tell a real hit from a stale serve; without that
    # split, "the cache is working" is unfalsifiable.
    c = SingleFlightCache(ttl_seconds=60)
    c.get_or_build("k", lambda: 1)
    c.get_or_build("k", lambda: 1)
    assert c.stats["miss"] == 1 and c.stats["hit"] == 1


def test_peek_reports_age_without_building():
    c = SingleFlightCache(ttl_seconds=60)
    assert c.peek("k") is None
    c.get_or_build("k", lambda: "v")
    value, age = c.peek("k")
    assert value == "v" and age < 5


# --- SingleFlight: coordination without storage ------------------------------
# This is the variant the intelligence call site needs, because that cache is
# bounded by ROW COUNT (`#632` measured it at 37.50 MB while obeying its
# 32-entry cap) and must keep its own store.

def test_exactly_one_caller_owns_the_key():
    from syndicate.features.shared.single_flight import SingleFlight
    sf = SingleFlight(lease_seconds=60)
    owners = []
    threads = [threading.Thread(target=lambda: owners.append(sf.begin("k")[0]))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert sum(1 for m in owners if m) == 1, f"expected ONE owner, got {sum(owners)}"


def test_non_owners_all_wait_on_the_SAME_event():
    # Distinct events would mean `finish` wakes only one of them.
    from syndicate.features.shared.single_flight import SingleFlight
    sf = SingleFlight(lease_seconds=60)
    mine, first = sf.begin("k")
    assert mine
    events = {id(sf.begin("k")[1]) for _ in range(5)}
    assert events == {id(first)}


def test_finish_wakes_every_waiter():
    from syndicate.features.shared.single_flight import SingleFlight
    sf = SingleFlight(lease_seconds=60)
    sf.begin("k")
    woke = []
    _, event = sf.begin("k")
    threads = [threading.Thread(target=lambda: woke.append(event.wait(timeout=5)))
               for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    sf.finish("k")
    for t in threads:
        t.join(timeout=5)
    assert woke == [True] * 4
    assert not sf.in_flight("k")


def test_an_EXPIRED_lease_is_adopted_rather_than_wedging_the_key():
    """THE REASON THIS IS A LEASE. A builder that dies without calling `finish`
    must delay the key, not kill it -- that is what lets a caller adopt this
    without wrapping a 250-line body in try/finally."""
    from syndicate.features.shared.single_flight import SingleFlight
    sf = SingleFlight(lease_seconds=0.2)
    mine, _ = sf.begin("k")
    assert mine
    assert sf.begin("k")[0] is False, "the lease must hold while it is valid"
    time.sleep(0.3)
    assert sf.begin("k")[0] is True, "an expired lease must be adoptable"


def test_finish_is_safe_to_call_twice_and_on_an_unknown_key():
    from syndicate.features.shared.single_flight import SingleFlight
    sf = SingleFlight(lease_seconds=60)
    sf.begin("k")
    sf.finish("k")
    sf.finish("k")
    sf.finish("never-seen")


def test_keys_are_independent():
    from syndicate.features.shared.single_flight import SingleFlight
    sf = SingleFlight(lease_seconds=60)
    assert sf.begin("a")[0] is True
    assert sf.begin("b")[0] is True, "a second key must not block behind the first"
