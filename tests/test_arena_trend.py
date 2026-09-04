"""An arena TIME SERIES for `#632` -- the question the per-request probes cannot ask.

FOUR PER-REQUEST EXPLANATIONS ARE NOW RULED OUT BY MEASUREMENT: cross-worker
cgroup scope (confirmed, fixed), background loops (falsified -- neither runs on
web), GC timing (excluded -- the sole gen-2-overlapping request read +32.344 MB
while the non-overlapping group swung to -30.108 MB), and `LAST_RESULT`
reassignment (excluded -- 0.0 MB both halves).

That last zero reframed the whole question. **CPython returns freed objects to
pymalloc's ARENAS, not to the OS.** So "which request freed it" is unanswerable
in principle: an in-Python free cannot move `Anonymous:` at all. What can is an
arena being RETURNED, and an arena is only returned when it is COMPLETELY empty
-- one surviving object pins the whole megabyte.

So the quantity worth a time series is `arena_mb` against
`bytes_in_allocated_blocks_mb`. **If arenas climb while live bytes stay flat, the
~173 MB/h is FRAGMENTATION, not retention** -- a different defect, with different
fixes, and no amount of freeing objects will return it.

`log_pymalloc_arena_stats` already reports both halves. What it lacked was a
budget that permits repeated sampling: its cap of 3 exists for an ALARM census
fired by the watchdog when anon is already critical. Spending those on routine
trend sampling would leave the one census that matters with nothing left, so the
trend gets its own counter and the two never share.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class BudgetSeparationTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD._ARENA_TREND_STATE.update({"count": 0, "last": None})
        MOD._PYMALLOC_STATS_STATE["count"] = 0

    tearDown = setUp

    def test_the_trend_does_NOT_spend_the_watchdog_alarm_budget(self) -> None:
        """The whole reason for a second counter. If the trend ate the alarm
        budget, the census that fires when anon is already critical would find
        it gone."""
        MOD.sample_arena_trend("trend-1")
        MOD.sample_arena_trend("trend-2")

        self.assertEqual(MOD._ARENA_TREND_STATE["count"], 2)
        self.assertEqual(MOD._PYMALLOC_STATS_STATE["count"], 0,
                         "the watchdog's 3 must be untouched")

    def test_the_watchdog_path_still_uses_its_OWN_budget(self) -> None:
        MOD.log_pymalloc_arena_stats("alarm")

        self.assertEqual(MOD._PYMALLOC_STATS_STATE["count"], 1)
        self.assertEqual(MOD._ARENA_TREND_STATE["count"], 0)

    def test_the_trend_budget_is_ENFORCED(self) -> None:
        """Periodic work is never free -- `#241`. This walks every arena and
        briefly repoints fd 2, so it must stop."""
        with mock.patch.dict(os.environ, {"SYNDICATE_ARENA_TREND_SAMPLES": "2"}, clear=False):
            self.assertIsNotNone(MOD.sample_arena_trend("a"))
            self.assertIsNotNone(MOD.sample_arena_trend("b"))
            self.assertIsNone(MOD.sample_arena_trend("c"), "past the budget it must refuse")
        self.assertEqual(MOD._ARENA_TREND_STATE["count"], 2)

    def test_an_unparseable_budget_falls_back_to_the_DEFAULT_not_to_unlimited(self) -> None:
        with mock.patch.dict(os.environ, {"SYNDICATE_ARENA_TREND_SAMPLES": "many"}, clear=False):
            self.assertEqual(MOD._arena_trend_budget(), MOD._ARENA_TREND_MAX_DEFAULT)


class TrendContentTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD._ARENA_TREND_STATE.update({"count": 0, "last": None})

    tearDown = setUp

    def test_it_records_the_two_halves_and_their_GAP(self) -> None:
        """The gap IS the finding: memory the OS gave us that Python is not
        using and cannot hand back."""
        MOD.sample_arena_trend("check")

        last = MOD._ARENA_TREND_STATE["last"]
        self.assertIsNotNone(last)
        self.assertIsInstance(last["arenas"], int)
        self.assertGreater(last["arena_mb"], 0)
        self.assertGreater(last["live_mb"], 0)
        self.assertAlmostEqual(last["fragmentation_mb"],
                               round(last["arena_mb"] - last["live_mb"], 3), places=3)

    def test_arenas_are_never_SMALLER_than_the_live_bytes_in_them(self) -> None:
        """A negative gap would mean the parse mapped the wrong two lines."""
        MOD.sample_arena_trend("check")

        last = MOD._ARENA_TREND_STATE["last"]
        self.assertGreaterEqual(last["arena_mb"], last["live_mb"])
        self.assertGreaterEqual(last["fragmentation_mb"], 0.0)

    def test_the_attribution_payload_carries_the_latest_reading(self) -> None:
        MOD.reset_request_memory_attribution()
        MOD._ARENA_TREND_STATE.update({"count": 0, "last": None})
        MOD.sample_arena_trend("check")

        payload = MOD.request_memory_attribution_payload()
        self.assertIn("arena_trend", payload)
        self.assertEqual(payload["arena_trend_samples"], 1)
        self.assertIn("fragmentation_mb", payload["arena_trend"])

    def test_an_absent_reading_publishes_an_empty_dict_not_a_crash(self) -> None:
        MOD.reset_request_memory_attribution()
        MOD._ARENA_TREND_STATE.update({"count": 0, "last": None})

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["arena_trend"], {})
        self.assertEqual(payload["arena_trend_samples"], 0)


if __name__ == "__main__":
    unittest.main()
