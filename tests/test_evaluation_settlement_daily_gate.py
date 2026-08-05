"""Settlement's daily Central-morning gate.

Was purely interval-since-last-run with no time-of-day concept, so "when it
runs" was an accident of when it last happened to fire. Reported live
2026-08-05: last run 21:01 CDT on 08-04 meant the next 24h-default run
wasn't due until ~21:01 CT the FOLLOWING night -- hours after that
morning's grading had already produced fresh rows for yesterday's slate,
and long after the day's board had been in use without them.
"""

from __future__ import annotations

import importlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

run_refresh_worker = importlib.import_module("scripts.run_refresh_worker")


def _epoch(year: int, month: int, day: int, hour: int, minute: int = 0, *, utc_offset_hours: int) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=utc_offset_hours))).timestamp()


class SettlementDailyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        for key in ("EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL", "EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS"):
            os.environ.pop(key, None)

    def test_the_reported_incident_now_runs(self) -> None:
        # last run 21:01 CDT 08-04, checked 9:52am CDT 08-05.
        last = _epoch(2026, 8, 4, 21, 1, utc_offset_hours=-5)
        now = _epoch(2026, 8, 5, 9, 52, utc_offset_hours=-5)
        self.assertTrue(run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=last))

    def test_before_target_hour_on_a_new_day_waits(self) -> None:
        last = _epoch(2026, 8, 4, 21, 1, utc_offset_hours=-5)
        before_six = _epoch(2026, 8, 5, 5, 0, utc_offset_hours=-5)
        self.assertFalse(run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=before_six, last_epoch=last))

    def test_exactly_at_target_hour_runs(self) -> None:
        last = _epoch(2026, 8, 4, 21, 1, utc_offset_hours=-5)
        at_six = _epoch(2026, 8, 5, 6, 0, utc_offset_hours=-5)
        self.assertTrue(run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=at_six, last_epoch=last))

    def test_will_not_run_twice_in_one_central_day(self) -> None:
        last = _epoch(2026, 8, 5, 6, 30, utc_offset_hours=-5)
        later_same_day = _epoch(2026, 8, 5, 20, 0, utc_offset_hours=-5)
        self.assertFalse(run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=later_same_day, last_epoch=last))

    def test_first_run_ever_does_not_wait_for_a_window(self) -> None:
        self.assertTrue(
            run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=_epoch(2026, 8, 5, 3, 0, utc_offset_hours=-5), last_epoch=0.0)
        )

    def test_self_catches_up_after_worker_downtime(self) -> None:
        # Worker was down at 6am, comes up at 9am having never run today.
        last = _epoch(2026, 8, 4, 21, 1, utc_offset_hours=-5)
        now = _epoch(2026, 8, 5, 9, 0, utc_offset_hours=-5)
        self.assertTrue(run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=last))

    def test_dst_boundary_uses_the_real_timezone_not_a_fixed_offset(self) -> None:
        # Winter is CST (UTC-6), not CDT (UTC-5) -- a fixed-offset bug would
        # misjudge the target hour by an hour for roughly half the year.
        last = _epoch(2026, 1, 4, 21, 1, utc_offset_hours=-6)
        now = _epoch(2026, 1, 5, 6, 30, utc_offset_hours=-6)
        self.assertTrue(run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=now, last_epoch=last))

    def test_explicit_interval_env_var_overrides_the_daily_gate(self) -> None:
        # Kept for the diagnostic use this already had: forcing a fast cycle
        # to confirm a fix, which the once-a-day gate cannot do quickly.
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS": "3600"}):
            last = _epoch(2026, 8, 4, 21, 1, utc_offset_hours=-5)
            self.assertFalse(
                run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=_epoch(2026, 8, 4, 21, 31, utc_offset_hours=-5), last_epoch=last)
            )
            self.assertTrue(
                run_refresh_worker._evaluation_settlement_should_run_now(now_epoch=_epoch(2026, 8, 4, 22, 2, utc_offset_hours=-5), last_epoch=last)
            )

    def test_target_hour_is_configurable_and_bounded(self) -> None:
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL": "4"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_target_hour_central(), 4)
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL": "99"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_target_hour_central(), 23)
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL": "-5"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_target_hour_central(), 0)
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL": "garbage"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_target_hour_central(), 6)

    def test_default_target_hour_is_6am(self) -> None:
        self.assertEqual(run_refresh_worker._evaluation_settlement_target_hour_central(), 6)


if __name__ == "__main__":
    unittest.main()
