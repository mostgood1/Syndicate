"""Per-request attribution excludes this process's own BACKGROUND THREADS (`#632`).

THE RESIDUE THIS CLOSES. `inflight` proves no other REQUEST overlapped a window.
It says nothing about `syndicate/app.py`'s live-refresh and intelligence-state
loops, which run in the SAME process and allocate and free on their own
schedule. Measured 2026-09-04 with per-process attribution already in place, that
residue was large enough to be the whole answer:

    worker 0   process anon +225.9 MB   attributed +395.8 MB   (175%)
    worker 1   process anon +104.9 MB   attributed  +39.3 MB   (37%)
    and a route read -49.46 MB across 252 solo requests

A negative retained total is not a small error; it is a different quantity. So
background work gets the same treatment requests already get: a counter that must
be zero at both ends, and a sequence that must not have moved in between.

WHY BOTH HALVES ARE NEEDED, and it is the case a single counter misses: an
iteration that starts AND finishes inside one request leaves `inflight` at 0 at
both ends, so only the `seq` comparison catches it. There is a test for exactly
that below, because it is the one an obvious implementation gets wrong.

WHERE THE MARKS ARE. The live-refresh loop marks its TICK, not the whole
iteration -- the wait must stay outside, or a mostly-idle loop would exclude every
request and attribution would fall silently to zero. The intelligence-state work
is marked at its THREAD TARGET, because the build runs on a separate
`syndicate-board-state-drain` thread; marking the loop would have marked the
wrong thread.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class _Env:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        self._patch = mock.patch.dict(
            os.environ, {"SYNDICATE_REQUEST_MEMORY_PROFILE": self._value}, clear=False)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class BackgroundGateTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def test_a_request_is_attributed_when_no_background_work_runs(self) -> None:
        """The `off != on` half: the gate must not refuse everything."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 130.0]):
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"][0]["total_mb"], 30.0)
        self.assertEqual(payload["skipped_background"], 0)

    def test_a_request_that_STARTS_while_a_loop_is_running_is_refused(self) -> None:
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=100.0):
            MOD.note_background_work_start()
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)
            MOD.note_background_work_end()

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"], [])
        self.assertEqual(payload["skipped_background"], 1)

    def test_a_loop_that_STARTS_MID_REQUEST_refuses_it(self) -> None:
        """`inflight` is 0 when the request begins, so only the end-check sees it."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 900.0]):
            token = MOD.note_request_start()
            MOD.note_background_work_start()          # a tick begins mid-request
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)
            MOD.note_background_work_end()

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"], [], "800 MB of loop work must not land on a route")
        self.assertEqual(payload["skipped_background"], 1)

    def test_a_loop_that_STARTS_AND_FINISHES_INSIDE_a_request_refuses_it(self) -> None:
        """THE CASE A SINGLE COUNTER MISSES. `inflight` reads 0 at both ends, so
        without the `seq` comparison this window looks clean and the loop's whole
        allocation is charged to the route."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 700.0]):
            token = MOD.note_request_start()
            MOD.note_background_work_start()
            MOD.note_background_work_end()           # entirely inside the request
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"], [])
        self.assertEqual(payload["skipped_background"], 1)

    def test_work_BEFORE_and_AFTER_a_request_does_not_refuse_it(self) -> None:
        """The gate must exclude overlap, not merely the existence of a loop."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 120.0]):
            MOD.note_background_work_start()
            MOD.note_background_work_end()           # finished before the request
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)
            MOD.note_background_work_start()         # begins after it
            MOD.note_background_work_end()

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"][0]["total_mb"], 20.0)
        self.assertEqual(payload["skipped_background"], 0)


class ContextManagerTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def test_background_work_clears_the_counter_on_a_RAISE(self) -> None:
        """A leaked counter makes every later request read as contended and
        attribution falls silently to zero -- the instrument goes blind while
        still emitting. This is why the loops are wrapped, not hand-paired."""
        with self.assertRaises(RuntimeError):
            with MOD.background_work():
                raise RuntimeError("a tick blew up")

        self.assertEqual(MOD._BACKGROUND_MEMORY_STATE["inflight"], 0)
        self.assertEqual(MOD._BACKGROUND_MEMORY_STATE["seq"], 1,
                         "the sequence must still advance -- the work DID happen")

    def test_the_counter_never_goes_negative(self) -> None:
        MOD.note_background_work_end()
        MOD.note_background_work_end()
        self.assertEqual(MOD._BACKGROUND_MEMORY_STATE["inflight"], 0)

    def test_marking_is_NOT_gated_on_the_profile_flag(self) -> None:
        """The flag can flip between a loop's start and its end. A gated pair
        would then decrement a counter it never incremented."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_REQUEST_MEMORY_PROFILE", None)
            with MOD.background_work():
                self.assertEqual(MOD._BACKGROUND_MEMORY_STATE["inflight"], 1)
        self.assertEqual(MOD._BACKGROUND_MEMORY_STATE["inflight"], 0)


class WiringTests(unittest.TestCase):
    """The marks must be on the threads that actually allocate."""

    def test_the_board_drain_thread_target_is_the_MARKED_wrapper(self) -> None:
        import inspect
        from pipeline.intelligence_state import IntelligenceStateService

        self.assertTrue(hasattr(IntelligenceStateService, "_drain_one_watched_board_date_marked"))
        src = inspect.getsource(IntelligenceStateService._drain_one_watched_board_date_async)
        self.assertIn("_drain_one_watched_board_date_marked", src,
                      "the THREAD must run the marked wrapper -- the build happens "
                      "on that thread, not on the loop")

    def test_the_live_refresh_TICK_is_marked_and_the_wait_is_not(self) -> None:
        import inspect
        from syndicate.features.shared import live_refresh_loop as L

        src = inspect.getsource(L._live_refresh_background_loop)
        self.assertIn("background_work()", src)
        tick = src.index("_run_live_refresh_tick()")
        wait = src.index("_LIVE_REFRESH_LOOP_STOP.wait(")
        mark = src.index("with background_work():")
        self.assertLess(mark, tick, "the mark must open before the tick")
        self.assertLess(tick, wait, "and the wait must stay outside it")


if __name__ == "__main__":
    unittest.main()
