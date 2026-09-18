"""Today's Layer 2 shortlist is written around a NEXT-DAY board build (lane `layer2-today-next-day-starvation`, option A).

MEASURED on refresh-worker: 18 of 23 gaps over 25 min between today's shortlist writes held a
next-day build (floor 1200 s), and raising the floor to 3600 s left 17 (`deploys.md` 2026-09-18
18:12Z) because each next-day build got longer. These tests pin when the fast path runs around a
next-day build, when it does not, and that the loop calls it on both sides of the build.
"""

from __future__ import annotations

import inspect
import io
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pipeline.intelligence_state as ism
from pipeline.intelligence_state import IntelligenceStateService

TODAY = "2026-09-18"
TOMORROW = "2026-09-19"


class AroundNextDayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IntelligenceStateService()
        patcher = patch.object(ism, "central_today_iso", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, build_date, phase, *, age_s=None, fast_result=None, env=None, drain=None, fast_raises=False):
        if age_s is not None:
            self.service._mark_layer2_fast_refresh(TODAY, time.time() - age_s)
        env = env or {}
        side = RuntimeError("boom") if fast_raises else None
        with patch.object(IntelligenceStateService, "_refresh_layer2_shortlist_only",
                          return_value={"rows": []} if fast_result is None else fast_result, side_effect=side) as fast, \
                patch.dict("os.environ", env, clear=False), \
                patch("syndicate.features.shared.deploy_drain.drain_hold_reason", return_value=drain):
            with redirect_stdout(io.StringIO()) as out:
                ran = self.service._refresh_today_layer2_around_next_day_build(build_date, phase)
        return ran, fast, out.getvalue()

    def test_a_today_build_is_not_a_next_day_build(self) -> None:
        for date in (TODAY, "2026-09-17", "", None):
            ran, fast, out = self._run(date, "after")
            self.assertEqual(ran, "not_next_day")
            fast.assert_not_called()
            self.assertEqual(out, "")

    def test_before_runs_when_today_is_stale_or_never_written(self) -> None:
        for age in (None, 600, 3000):
            self.service = IntelligenceStateService()
            ran, fast, out = self._run(TOMORROW, "before", age_s=age)
            self.assertEqual(ran, "yes")
            fast.assert_called_once_with(TODAY)
            self.assertIn(f"LAYER2_AROUND_NEXT_DAY phase=before today={TODAY} build_date={TOMORROW}", out)
            self.assertIn("ran=yes", out)

    def test_before_skips_when_today_was_just_written(self) -> None:
        ran, fast, out = self._run(TOMORROW, "before", age_s=120)
        self.assertEqual(ran, "skipped")
        fast.assert_not_called()
        self.assertIn("ran=skipped reason=fresh", out)

    def test_the_freshness_floor_is_env_tunable(self) -> None:
        ran, fast, _ = self._run(TOMORROW, "before", age_s=120, env={"SYNDICATE_LAYER2_AROUND_NEXT_DAY_MIN_AGE_SECONDS": "60"})
        self.assertEqual(ran, "yes")
        fast.assert_called_once_with(TODAY)

    def test_after_runs_even_when_today_is_fresh(self) -> None:
        ran, fast, out = self._run(TOMORROW, "after", age_s=120)
        self.assertEqual(ran, "yes")
        fast.assert_called_once_with(TODAY)
        self.assertIn("phase=after", out)

    def test_two_days_out_counts_as_next_day(self) -> None:
        ran, fast, _ = self._run("2026-09-20", "after")
        self.assertEqual(ran, "yes")
        fast.assert_called_once_with(TODAY)

    def test_kill_switch(self) -> None:
        ran, fast, out = self._run(TOMORROW, "after", env={"SYNDICATE_LAYER2_AROUND_NEXT_DAY_ENABLED": "0"})
        self.assertEqual(ran, "skipped")
        fast.assert_not_called()
        self.assertIn("reason=disabled", out)

    def test_a_deploy_drain_holds_it(self) -> None:
        ran, fast, out = self._run(TOMORROW, "after", drain="deploy_pending")
        self.assertEqual(ran, "skipped")
        fast.assert_not_called()
        self.assertIn("reason=drain:deploy_pending", out)

    def test_a_declined_fast_path_reads_no(self) -> None:
        with patch.object(IntelligenceStateService, "_refresh_layer2_shortlist_only", return_value=None), \
                patch("syndicate.features.shared.deploy_drain.drain_hold_reason", return_value=None):
            with redirect_stdout(io.StringIO()) as out:
                ran = self.service._refresh_today_layer2_around_next_day_build(TOMORROW, "after")
        self.assertEqual(ran, "no")
        self.assertIn("ran=no", out.getvalue())

    def test_it_never_raises(self) -> None:
        ran, _, out = self._run(TOMORROW, "after", fast_raises=True)
        self.assertEqual(ran, "no")
        self.assertIn("LAYER2_AROUND_NEXT_DAY_FAILED phase=after", out)


class LoopWiringTests(unittest.TestCase):
    """The loop is not unit-drivable; pin the call order in its source instead."""

    def setUp(self) -> None:
        src = inspect.getsource(IntelligenceStateService._background_loop)
        self.code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))

    def test_before_runs_ahead_of_the_build_and_after_follows_it(self) -> None:
        before = self.code.index('_refresh_today_layer2_around_next_day_build(')
        compute = self.code.index("self._compute_board_publication_response(payload_to_process)")
        after = self.code.index('"after")')
        guard = self.code.index("self._execution_guard.acquire(blocking=False)")
        release = self.code.index("self._execution_guard.release()")
        self.assertIn('"before")', self.code[before:compute])
        self.assertTrue(guard < before < compute < after < release)

    def test_after_is_outside_the_compute_try_so_a_failed_build_still_runs_it(self) -> None:
        after = self.code.index('"after")')
        failed = self.code.index("BOARD_PUBLICATION_FAILED")
        response_date = self.code.index('response_date = str(response.get("selected_date")')
        self.assertTrue(failed < after < response_date)
        line = next(l for l in self.code.splitlines() if '"after")' in l)
        compute_line = next(l for l in self.code.splitlines() if "self._compute_board_publication_response(payload_to_process)" in l)
        self.assertLess(len(line) - len(line.lstrip()), len(compute_line) - len(compute_line.lstrip()))


if __name__ == "__main__":
    unittest.main()
