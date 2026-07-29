from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from syndicate.features.mlb import live_lens


class MlbLiveLensSnapshotReaderTests(unittest.TestCase):
    def test_read_latest_live_lens_snapshot_uses_keyvalue_aware_reader(self) -> None:
        # Regression: the background live_lens_loop writes snapshots via
        # refresh_state_store.write_json_file(), which goes to the shared
        # keyvalue store when SYNDICATE_REFRESH_STATE_BACKEND=keyvalue. The
        # read side must use the matching keyvalue-aware read_json_file(),
        # not a plain local-filesystem read, or the loop's writes are
        # invisible to whichever service serves the request.
        snapshot = {"date": "2026-07-13", "games": []}
        with patch.object(live_lens, "read_json_file", return_value=snapshot) as mocked_read:
            result = live_lens.read_latest_live_lens_snapshot()

        self.assertEqual(result, snapshot)
        mocked_read.assert_called_once_with(live_lens.live_lens_snapshot_path())


class LiveLensSnapshotNeedsRefreshTests(unittest.TestCase):
    """#124: a real, correctly-read snapshot (from the shared keyvalue store,
    written by live-odds-worker's dedicated live-lens loop with genuine
    liveProps) was being discarded and replaced with a thinner local
    recompute on almost every refresh-worker cycle. The cause:
    _live_lens_snapshot_needs_refresh deferred to _live_lens_report_needs_refresh,
    which measures a DIFFERENT file's mtime on THIS process's own disk (reset
    every time pull_hot_artifacts re-fetches it) rather than the snapshot's
    own actual generation time -- with a 60s max-age tighter than a real
    candidate-pool cycle interval, that check was true almost every time.
    Confirmed live: refresh-worker's independent recompute had
    prop_row_counts=[0]*9 across 9 real live games while web's own direct
    read had 24/18/16 real rows for 3 of them.
    """

    def _today_iso(self) -> str:
        return datetime.now().astimezone().date().isoformat()

    def test_fresh_snapshot_generated_at_wins_even_when_report_file_looks_stale(self) -> None:
        recent = (datetime.now().astimezone() - timedelta(seconds=5)).isoformat(timespec="seconds")
        snapshot = {"games": [{"gamePk": 1}], "generatedAt": recent}
        # The old behavior (deferring to this) would say "stale" -- proving
        # it is never even consulted when a usable generatedAt exists.
        with patch.object(live_lens, "_live_lens_report_needs_refresh", return_value=True) as mocked_report_check:
            needs_refresh = live_lens._live_lens_snapshot_needs_refresh(self._today_iso(), snapshot)
        self.assertFalse(needs_refresh)
        mocked_report_check.assert_not_called()

    def test_stale_snapshot_generated_at_still_triggers_refresh(self) -> None:
        old = (datetime.now().astimezone() - timedelta(seconds=120)).isoformat(timespec="seconds")
        snapshot = {"games": [{"gamePk": 1}], "generatedAt": old}
        needs_refresh = live_lens._live_lens_snapshot_needs_refresh(self._today_iso(), snapshot)
        self.assertTrue(needs_refresh)

    def test_missing_generated_at_falls_back_to_the_report_file_check(self) -> None:
        snapshot = {"games": [{"gamePk": 1}]}
        with patch.object(live_lens, "_live_lens_report_needs_refresh", return_value=True) as mocked_report_check:
            needs_refresh = live_lens._live_lens_snapshot_needs_refresh(self._today_iso(), snapshot)
        self.assertTrue(needs_refresh)
        mocked_report_check.assert_called_once_with(self._today_iso())

        with patch.object(live_lens, "_live_lens_report_needs_refresh", return_value=False):
            self.assertFalse(live_lens._live_lens_snapshot_needs_refresh(self._today_iso(), snapshot))

    def test_empty_snapshot_always_needs_refresh_regardless_of_generated_at(self) -> None:
        recent = datetime.now().astimezone().isoformat(timespec="seconds")
        self.assertTrue(live_lens._live_lens_snapshot_needs_refresh(self._today_iso(), {"games": [], "generatedAt": recent}))
        self.assertTrue(live_lens._live_lens_snapshot_needs_refresh(self._today_iso(), None))

    def test_non_today_date_never_needs_refresh(self) -> None:
        yesterday = (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()
        self.assertFalse(live_lens._live_lens_snapshot_needs_refresh(yesterday, None))
        self.assertFalse(live_lens._live_lens_snapshot_needs_refresh(yesterday, {"games": []}))


class SnapshotGeneratedAtAgeSecondsTests(unittest.TestCase):
    def test_parses_aware_iso_timestamp(self) -> None:
        five_seconds_ago = (datetime.now().astimezone() - timedelta(seconds=5)).isoformat(timespec="seconds")
        age = live_lens._snapshot_generated_at_age_seconds({"generatedAt": five_seconds_ago})
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 0.0)
        self.assertLess(age, 30.0)

    def test_missing_field_returns_none(self) -> None:
        self.assertIsNone(live_lens._snapshot_generated_at_age_seconds({}))
        self.assertIsNone(live_lens._snapshot_generated_at_age_seconds(None))

    def test_unparseable_value_returns_none(self) -> None:
        self.assertIsNone(live_lens._snapshot_generated_at_age_seconds({"generatedAt": "not-a-timestamp"}))


if __name__ == "__main__":
    unittest.main()
