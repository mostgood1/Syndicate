"""Automatic `malloc_trim`, gated so it is not paid for on every request. `#632`.

The manual measurement returned **-58.1 MB in 14.2 ms** and **-47.3 MB in
4.1 ms**, with glibc reporting a release and `in_use` unmoved. Repeat calls
returned **~0**, because trim is idempotent until free space rebuilds — which is
precisely why this is gated rather than periodic.

THE ORDER OF THE GATES IS THE COST CONTROL, and these tests pin it:

1. `enabled` — an env read, DEFAULT OFF.
2. `interval` — ONE clock comparison, the path essentially every request takes,
   doing no allocator work at all.
3. `free_in_arena` — only here does anything touch the malloc lock, at most once
   per interval.

So the lock hold lands on ONE request per interval rather than on every request.
There is NO NEW THREAD and no scheduler: it rides the existing
`teardown_request` hook, because `#241` is the precedent where added periodic
worker work caused a production restart loop.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


def _reset():
    MOD._TRIM_AUTO_STATE.update({"last_at": 0.0, "trims": 0, "skipped_interval": 0,
                                 "skipped_threshold": 0, "returned_mb": 0.0})


def _on(**extra):
    env = {"SYNDICATE_MALLOC_TRIM_AUTO": "1"}
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=False)


class DefaultOffTests(unittest.TestCase):

    def setUp(self) -> None:
        _reset()

    tearDown = setUp

    def test_it_is_OFF_unless_explicitly_enabled(self) -> None:
        """A production behaviour change ships inert and is turned on by env with
        a measurement, never by landing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_MALLOC_TRIM_AUTO", None)

            self.assertFalse(MOD.trim_auto_enabled())
            self.assertIsNone(MOD.maybe_trim_after_request())

    def test_a_disabled_run_touches_NOTHING(self) -> None:
        """Off must mean off: no allocator call, not even the cheap one."""
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(MOD, "glibc_mallinfo2") as info, \
                mock.patch.object(MOD, "malloc_trim_now") as trim:
            os.environ.pop("SYNDICATE_MALLOC_TRIM_AUTO", None)
            MOD.maybe_trim_after_request()

        info.assert_not_called()
        trim.assert_not_called()

    def test_only_truthy_values_enable_it(self) -> None:
        for value, expected in (("1", True), ("true", True), ("on", True),
                                ("0", False), ("false", False), ("", False),
                                ("maybe", False)):
            with mock.patch.dict(os.environ,
                                 {"SYNDICATE_MALLOC_TRIM_AUTO": value}, clear=False):
                self.assertEqual(MOD.trim_auto_enabled(), expected, value)


class GateOrderTests(unittest.TestCase):

    def setUp(self) -> None:
        _reset()

    tearDown = setUp

    def test_the_INTERVAL_gate_runs_BEFORE_any_allocator_call(self) -> None:
        """THE cost control. Inside the interval the request must pay one clock
        comparison and nothing else -- `mallinfo2` takes the malloc lock, so
        calling it per request would defeat the point."""
        MOD._TRIM_AUTO_STATE["last_at"] = time.monotonic()

        with _on(), mock.patch.object(MOD, "glibc_mallinfo2") as info, \
                mock.patch.object(MOD, "malloc_trim_now") as trim:
            self.assertIsNone(MOD.maybe_trim_after_request())

        info.assert_not_called()
        trim.assert_not_called()
        self.assertEqual(MOD._TRIM_AUTO_STATE["skipped_interval"], 1)

    def test_past_the_interval_it_CHECKS_free_space_before_trimming(self) -> None:
        """Repeat trims return ~0, so an unconditional periodic trim is waste."""
        with _on(SYNDICATE_MALLOC_TRIM_MIN_FREE_MB="64"), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  return_value={"available": True,
                                                "free_in_arena_mb": 10.0}), \
                mock.patch.object(MOD, "malloc_trim_now") as trim:
            self.assertIsNone(MOD.maybe_trim_after_request())

        trim.assert_not_called()
        self.assertEqual(MOD._TRIM_AUTO_STATE["skipped_threshold"], 1)

    def test_enough_free_space_TRIMS_and_records_it(self) -> None:
        with _on(SYNDICATE_MALLOC_TRIM_MIN_FREE_MB="64"), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  return_value={"available": True,
                                                "free_in_arena_mb": 150.0}), \
                mock.patch.object(MOD, "malloc_trim_now",
                                  return_value={"available": True, "pid": 7,
                                                "proc_token": "abc", "anon_delta_mb": -58.1,
                                                "anon_before_mb": 354.2, "anon_after_mb": 296.1,
                                                "duration_ms": 14.2, "malloc_trim_returned": 1,
                                                "in_use_stable": True}):
            result = MOD.maybe_trim_after_request()

        self.assertIsNotNone(result)
        self.assertEqual(MOD._TRIM_AUTO_STATE["trims"], 1)
        self.assertAlmostEqual(MOD._TRIM_AUTO_STATE["returned_mb"], -58.1, places=1)

    def test_the_interval_slot_is_claimed_BEFORE_the_expensive_work(self) -> None:
        """Two threads reaching teardown together must not both trim. The slot is
        taken before `mallinfo2`, so the loser exits on the interval gate."""
        calls = []

        def slow_info():
            calls.append(1)
            return {"available": True, "free_in_arena_mb": 150.0}

        with _on(), mock.patch.object(MOD, "glibc_mallinfo2", slow_info), \
                mock.patch.object(MOD, "malloc_trim_now",
                                  return_value={"available": True, "anon_delta_mb": -1.0}):
            MOD.maybe_trim_after_request()
            MOD.maybe_trim_after_request()      # same interval -- must be refused

        self.assertEqual(len(calls), 1)


class SafetyTests(unittest.TestCase):

    def setUp(self) -> None:
        _reset()

    tearDown = setUp

    def test_an_exception_NEVER_escapes_into_the_request(self) -> None:
        """This runs in `teardown_request`. A memory diagnostic must not be able
        to fail a request."""
        with _on(), mock.patch.object(MOD, "glibc_mallinfo2",
                                      side_effect=RuntimeError("boom")):
            self.assertIsNone(MOD.maybe_trim_after_request())

    def test_an_unavailable_allocator_is_a_no_op(self) -> None:
        with _on(), mock.patch.object(MOD, "glibc_mallinfo2",
                                      return_value={"available": False, "why": "nope"}), \
                mock.patch.object(MOD, "malloc_trim_now") as trim:
            self.assertIsNone(MOD.maybe_trim_after_request())

        trim.assert_not_called()

    def test_an_unparseable_interval_falls_back_to_the_DEFAULT(self) -> None:
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_MALLOC_TRIM_INTERVAL_S": "soon"}, clear=False):
            self.assertEqual(
                MOD._trim_auto_float("SYNDICATE_MALLOC_TRIM_INTERVAL_S",
                                     MOD._TRIM_AUTO_INTERVAL_S_DEFAULT),
                MOD._TRIM_AUTO_INTERVAL_S_DEFAULT)

    def test_a_zero_interval_falls_back_rather_than_trimming_every_request(self) -> None:
        """`0` must not read as "trim always" -- that would put a 14 ms lock hold
        on every request, which is the failure this design exists to avoid."""
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_MALLOC_TRIM_INTERVAL_S": "0"}, clear=False):
            self.assertEqual(
                MOD._trim_auto_float("SYNDICATE_MALLOC_TRIM_INTERVAL_S",
                                     MOD._TRIM_AUTO_INTERVAL_S_DEFAULT),
                MOD._TRIM_AUTO_INTERVAL_S_DEFAULT)


if __name__ == "__main__":
    unittest.main()
