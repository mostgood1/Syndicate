from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaaf.smartsim2_trial_monitoring import read_monitoring_log
from syndicate.features.ncaaf.smartsim2_trial_monitoring import record_trial_page_view


class TrialMonitoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.log_path = Path(self._tmpdir.name) / "monitoring.jsonl"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_no_op_on_empty_scoreboards(self) -> None:
        result = record_trial_page_view(route="/ncaaf/cards", season=2025, week=1, scoreboards=[], log_path=self.log_path)
        self.assertIsNone(result)
        self.assertFalse(self.log_path.exists())

    def test_records_rates_correctly(self) -> None:
        scoreboards = [
            {"smartsim2_available": True, "projection_sources_mode": "public_trial"},
            {"smartsim2_available": True, "projection_sources_mode": None},
            {"smartsim2_available": False, "projection_sources_mode": None},
            {"smartsim2_available": False, "projection_sources_mode": "public_trial"},  # a would-be fallback
        ]
        record = record_trial_page_view(route="/ncaaf/cards", season=2025, week=1, scoreboards=scoreboards, log_path=self.log_path)
        self.assertIsNotNone(record)
        self.assertEqual(record["total_games"], 4)
        self.assertEqual(record["projection_availability_rate"], 0.5)
        self.assertEqual(record["smartsim2_visibility_rate"], 0.5)
        self.assertEqual(record["fallback_rate"], 0.25)
        self.assertEqual(record["visibility_mode"], "public_trial")

    def test_appends_multiple_records_and_reads_them_back(self) -> None:
        record_trial_page_view(route="/ncaaf/cards", season=2025, week=1, scoreboards=[{"smartsim2_available": True}], log_path=self.log_path)
        record_trial_page_view(route="/ncaaf/picks", season=2025, week=1, scoreboards=[{"smartsim2_available": False}], log_path=self.log_path)
        records = read_monitoring_log(log_path=self.log_path)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["route"], "/ncaaf/cards")
        self.assertEqual(records[1]["route"], "/ncaaf/picks")

    def test_read_returns_empty_list_when_log_missing(self) -> None:
        missing_path = Path(self._tmpdir.name) / "does_not_exist.jsonl"
        self.assertEqual(read_monitoring_log(log_path=missing_path), [])

    def test_logging_failure_does_not_raise(self) -> None:
        # A directory that cannot be created (parent is itself a file) should
        # be swallowed, not raised -- monitoring must never break a page render.
        blocked_parent = Path(self._tmpdir.name) / "not_a_directory"
        blocked_parent.write_text("this is a file, not a directory", encoding="utf-8")
        bad_path = blocked_parent / "monitoring.jsonl"
        result = record_trial_page_view(route="/ncaaf/cards", season=2025, week=1, scoreboards=[{"smartsim2_available": True}], log_path=bad_path)
        self.assertIsInstance(result, dict)  # record is still returned even if the write failed


if __name__ == "__main__":
    unittest.main()
