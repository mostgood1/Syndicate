"""Per-request anonymous-memory attribution (`#632`).

Every test here pins something that would otherwise fail SILENTLY:

  * DEFAULT OFF has to mean "does not read the cgroup", not "reads it and
    discards the answer". This service is already being OOM-killed and `#241` is
    the precedent for periodic work assumed free, so the test asserts the READ
    HELPER IS NEVER CALLED rather than asserting the return value is None.
  * CONCURRENCY MUST REFUSE, NOT GUESS. Web is 1 gunicorn worker with
    `GUNICORN_THREADS=4`, so a delta measured around overlapping requests
    includes the other three. A wrong attribution names a route; a refused one
    names nothing, which is the honest outcome.
  * THE IN-FLIGHT COUNTER MUST NOT LEAK. If `note_request_end` skips the
    decrement on any path, every later request reads as contended and the whole
    instrument goes blind while still emitting a table.
  * ANON, NOT CURRENT. Attributing `memory_current_mb` would rebuild `#566`'s
    page-cache mistake one layer down.


`#632` NOTE: these patch `_process_anon_mb`, not `_anon_mb`. Attribution moved
from the CONTAINER cgroup to THIS PROCESS's own anon, because `inflight` is
per-worker module state and the cgroup is per-container -- at
`WEB_CONCURRENCY=2` the guarantee and the measurement covered different scopes,
which produced an attributed share of 61-150% (above 100% being impossible for a
true partition). The behaviour asserted below is unchanged; only the reading's
source is.
"""
from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class _Env:
    """Set/restore the profile key without leaking into sibling tests."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        import os

        self._prev = os.environ.get("SYNDICATE_REQUEST_MEMORY_PROFILE")
        if self.value is None:
            os.environ.pop("SYNDICATE_REQUEST_MEMORY_PROFILE", None)
        else:
            os.environ["SYNDICATE_REQUEST_MEMORY_PROFILE"] = self.value
        return self

    def __exit__(self, *a):
        import os

        if self._prev is None:
            os.environ.pop("SYNDICATE_REQUEST_MEMORY_PROFILE", None)
        else:
            os.environ["SYNDICATE_REQUEST_MEMORY_PROFILE"] = self._prev
        return False


class DefaultOffTests(unittest.TestCase):
    def setUp(self):
        MOD.reset_request_memory_attribution()

    def test_absent_key_is_off(self):
        with _Env(None):
            self.assertFalse(MOD.request_memory_profile_enabled())

    def test_unrecognised_value_is_off_not_on(self):
        """Unknown must not land on the permissive branch: an unreadable setting
        must not switch on new per-request work on a dying service."""
        for value in ("", "maybe", "0", "off", "false", "no", "ON_LATER"):
            with _Env(value):
                self.assertFalse(MOD.request_memory_profile_enabled(), value)

    def test_recognised_truthy_values_are_on(self):
        for value in ("on", "1", "true", "yes", "  ON  ", "True"):
            with _Env(value):
                self.assertTrue(MOD.request_memory_profile_enabled(), value)

    def test_when_off_it_does_not_read_the_cgroup_at_all(self):
        """THE load-bearing one. Returning None while still paying for the read
        would be indistinguishable from this in every log, and would be exactly
        the cost this key exists to withhold."""
        with _Env(None), mock.patch.object(MOD, "_read_container_memory_stat") as read:
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards")
        self.assertIsNone(token)
        read.assert_not_called()


class ConcurrencyTests(unittest.TestCase):
    """1 worker x 4 threads: overlapping requests are the normal case."""

    def setUp(self):
        MOD.reset_request_memory_attribution()

    def test_a_solo_request_is_attributed(self):
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 140.0]):
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)
        payload = MOD.request_memory_attribution_payload()
        rows = {r["route"]: r for r in payload["routes"]}
        self.assertEqual(rows["/mlb/api/cards"]["solo_n"], 1)
        self.assertAlmostEqual(rows["/mlb/api/cards"]["total_mb"], 40.0, places=3)
        self.assertEqual(payload["skipped_concurrent"], 0)

    def test_an_overlapping_request_is_REFUSED_not_guessed(self):
        """B starts while A is in flight. Neither may be attributed: the delta
        around either one contains the other's allocations."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=100.0):
            a = MOD.note_request_start()
            b = MOD.note_request_start()
            self.assertIsNone(b, "the second concurrent request must not attribute")
            MOD.note_request_end(b, "/b", emit_every=10_000)
            MOD.note_request_end(a, "/a", emit_every=10_000)
        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"], [])
        self.assertGreaterEqual(payload["skipped_concurrent"], 1)

    def test_a_request_joined_midway_is_refused_even_though_it_started_alone(self):
        """A starts alone, B joins, B finishes, A finishes. A's window still
        contains B's allocations, so A must be refused too."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=100.0):
            a = MOD.note_request_start()
            self.assertIsNotNone(a)
            b = MOD.note_request_start()
            MOD.note_request_end(b, "/b", emit_every=10_000)
            MOD.note_request_end(a, "/a", emit_every=10_000)
        self.assertEqual(MOD.request_memory_attribution_payload()["routes"], [])

    def test_the_inflight_counter_returns_to_zero_on_every_path(self):
        """A leaked counter makes every later request read as contended, and the
        instrument goes blind while still printing a table."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=100.0):
            for _ in range(3):
                t = MOD.note_request_start()
                MOD.note_request_end(t, "/x", emit_every=10_000)
            a = MOD.note_request_start()
            b = MOD.note_request_start()
            MOD.note_request_end(b, "/b", emit_every=10_000)
            MOD.note_request_end(a, "/a", emit_every=10_000)
        self.assertEqual(MOD._REQUEST_MEMORY_STATE["inflight"], 0)

    def test_an_unreadable_cgroup_refuses_and_is_counted(self):
        """Absence is reported, not folded into a 0.0 MB attribution."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=None):
            t = MOD.note_request_start()
            MOD.note_request_end(t, "/x", emit_every=10_000)
        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"], [])
        self.assertGreaterEqual(payload["unreadable"], 1)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        MOD.reset_request_memory_attribution()

    def test_it_reads_anon_not_current(self):
        """`memory_current_mb` includes page cache; attributing it would rebuild
        `#566`'s mistake one layer down."""
        with mock.patch.object(MOD, "_read_container_memory_stat",
                               return_value={"anon": 5 * 1024 * 1024,
                                             "inactive_file": 900 * 1024 * 1024}):
            self.assertAlmostEqual(MOD._anon_mb(), 5.0, places=3)

    def test_ranking_is_by_total_retained_not_by_peak(self):
        """The question is which route accounts for the most UNRETURNED memory
        over a shift; a single fat call that gets freed is not this defect."""
        with _Env("on"):
            for anon_pair, route in (((0.0, 5.0), "/steady"), ((0.0, 5.0), "/steady"),
                                     ((0.0, 5.0), "/steady"), ((0.0, 9.0), "/spike")):
                with mock.patch.object(MOD, "_process_anon_mb", side_effect=list(anon_pair)):
                    t = MOD.note_request_start()
                    MOD.note_request_end(t, route, emit_every=10_000)
        routes = [r["route"] for r in MOD.request_memory_attribution_payload()["routes"]]
        self.assertEqual(routes[0], "/steady", "15 MB across 3 calls outranks one 9 MB call")

    def test_the_payload_carries_its_own_denominator(self):
        """A top-routes table with no denominator invites reading the solo
        sample as the whole service. On a busy box most rows are refused."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=100.0):
            a = MOD.note_request_start()
            b = MOD.note_request_start()
            MOD.note_request_end(b, "/b", emit_every=10_000)
            MOD.note_request_end(a, "/a", emit_every=10_000)
        payload = MOD.request_memory_attribution_payload()
        for key in ("solo_attributed", "skipped_concurrent", "unreadable", "distinct_routes"):
            self.assertIn(key, payload)

    def test_it_emits_only_every_nth_request(self):
        """One line per request would flood the log the instrument is read in."""
        emitted = []
        # 6 requests x 2 reads PLUS one per emit -- the payload reads anon once
        # more for `anon_mb_now`. A short list raises StopIteration inside the
        # hook, which production would swallow in the caller's except.
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", side_effect=[float(n) for n in range(40)]), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: emitted.append(a)):
            for _ in range(6):
                t = MOD.note_request_start()
                MOD.note_request_end(t, "/x", emit_every=3)
        self.assertEqual(len(emitted), 2, "6 solo requests at emit_every=3 -> 2 lines")


if __name__ == "__main__":
    unittest.main()
