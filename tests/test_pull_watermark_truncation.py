"""A truncated export must not move the pull watermark past what it did not deliver.

MEASURED 2026-09-16 (lane `web-export-timeout`). Web's bulk export stops at its
byte budget and says so with `truncated: true` in an HTTP 200. The pull read the
200 as success and recorded its watermark at its own START time, so every file
the budget cut was below the floor from then on and was never requested again.
The repair pass cannot recover them: it fetches files missing OUTRIGHT, never
ones present and stale. Before the per-file cap, a 30-minute window delivered
4 of 133 changed files and silently dropped the rest.

The fix has two halves, and these tests pin the client's:

- the server fills a `since` read OLDEST-FIRST and returns `next_since`, the
  mtime of the first file that did not fit (`tests/test_artifact_export_oversize.py`);
- the pull records that cursor instead of its start time, and HOLDS its floor
  when a truncated response carries no cursor.

Refusing to advance is not enough on its own, and was rejected for that reason:
the server used to cut in arbitrary walk order, so re-reading the same window
returned the same first budget-worth forever.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import artifact_publisher
from syndicate.features.shared.artifact_publisher import _PullOutcome, _pull_watermark_after


NOW = 1789574400.0          # 2026-09-16T16:00:00Z, a pull's start
FLOOR = NOW - 1800.0         # its previous watermark, 30 minutes back
CUT = NOW - 1200.0           # where the server says a truncated read must resume


class PullWatermarkDecisionTests(unittest.TestCase):
    """`_pull_watermark_after` is the whole decision; each case is one outcome shape."""

    def _after(self, *outcomes: _PullOutcome):
        return _pull_watermark_after(list(outcomes), pull_started_epoch=NOW, since_epoch=FLOOR, scope="2026-09-16")

    def test_nothing_truncated_records_the_start_time_exactly_as_before(self) -> None:
        self.assertEqual(self._after(_PullOutcome(True, 12, False, None), _PullOutcome(True, 3, False, None)), NOW)

    def test_a_truncated_read_records_the_CURSOR_not_the_start_time(self) -> None:
        """THE DEFECT: this used to return NOW, and everything in (CUT, NOW] was lost."""
        self.assertEqual(self._after(_PullOutcome(True, 95, True, CUT)), CUT)

    def test_one_complete_pattern_does_not_let_the_other_skip(self) -> None:
        """Two date patterns share ONE floor. The complete one would happily record
        NOW; the truncated one must win, or its tail is skipped."""
        self.assertEqual(self._after(_PullOutcome(True, 20, False, None), _PullOutcome(True, 77, True, CUT)), CUT)

    def test_two_truncated_patterns_resume_at_the_EARLIER_cursor(self) -> None:
        self.assertEqual(
            self._after(_PullOutcome(True, 50, True, CUT + 300.0), _PullOutcome(True, 50, True, CUT)),
            CUT,
        )

    def test_truncated_WITHOUT_a_cursor_HOLDS_the_floor(self) -> None:
        """An older web sends no `next_since`, and a server that judges a resume
        cannot progress withholds it. Recording NOW there would reintroduce the skip;
        None tells the caller to write nothing and re-read the window."""
        self.assertIsNone(self._after(_PullOutcome(True, 95, True, None)))

    def test_a_missing_cursor_on_ONE_pattern_holds_the_whole_floor(self) -> None:
        self.assertIsNone(self._after(_PullOutcome(True, 50, True, CUT), _PullOutcome(True, 50, True, None)))


class _Store:
    """In-memory stand-in for the keyvalue-backed read/write pair."""

    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def read(self, path: Path):
        return self.data.get(str(path))

    def write(self, path: Path, payload: dict) -> None:
        self.data[str(path)] = dict(payload)


class PullHotArtifactsReachabilityTests(unittest.TestCase):
    """Drives the REAL `pull_hot_artifacts`, so the decision above is proven wired in.

    A decision function nobody calls passes all of its own tests; this repo has
    shipped four of those. Only the network edge is mocked.
    """

    DATE = "2026-09-16"

    def setUp(self) -> None:
        self.store = _Store()
        self._patches = [
            patch("syndicate.features.shared.refresh_state_store.read_json_file", side_effect=self.store.read),
            patch("syndicate.features.shared.refresh_state_store.write_json_file", side_effect=self.store.write),
            patch.dict("os.environ", {
                "RENDER_SERVICE_NAME": "refresh-worker",
                "SYNDICATE_REFRESH_LANE": "",
                "SYNDICATE_WEB_PUBLISH_URL": "http://web/api/ops/artifacts/publish",
            }, clear=False),
            patch.object(artifact_publisher, "_admin_token", return_value="t"),
            patch.object(artifact_publisher, "_missing_required_artifact_relative_paths", return_value=[]),
            patch.object(artifact_publisher, "_pull_hot_artifacts_request", return_value=(True, 0)),
            patch.object(artifact_publisher.time, "time", return_value=NOW),
        ]
        for p in self._patches:
            p.start()
        artifact_publisher._record_hot_artifact_pull_watermark(FLOOR, date_str=self.DATE)

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _floor(self) -> float | None:
        payload = self.store.read(artifact_publisher._hot_artifact_pull_watermark_path(self.DATE))
        return float(payload["epoch"]) if payload else None

    def _pull_with(self, *outcomes: _PullOutcome) -> None:
        with patch.object(artifact_publisher, "_pull_hot_artifacts_request_outcome", side_effect=list(outcomes)):
            artifact_publisher.pull_hot_artifacts(date_str=self.DATE)

    def test_a_truncated_pull_records_the_servers_cursor(self) -> None:
        self._pull_with(_PullOutcome(True, 95, True, CUT), _PullOutcome(True, 4, False, None))
        self.assertEqual(self._floor(), CUT, "the watermark advanced past what the truncated read did not deliver")

    def test_a_complete_pull_still_records_its_start_time(self) -> None:
        self._pull_with(_PullOutcome(True, 20, False, None), _PullOutcome(True, 4, False, None))
        self.assertEqual(self._floor(), NOW)

    def test_a_truncated_pull_with_no_cursor_leaves_the_floor_where_it_was(self) -> None:
        self._pull_with(_PullOutcome(True, 95, True, None), _PullOutcome(True, 4, False, None))
        self.assertEqual(self._floor(), FLOOR, "a cursorless truncation moved the floor")

    def test_a_FAILED_pull_still_does_not_advance(self) -> None:
        """The pre-existing guarantee, kept: a transport failure moves nothing."""
        self._pull_with(_PullOutcome(False, 0, False, None), _PullOutcome(True, 4, False, None))
        self.assertEqual(self._floor(), FLOOR)


class PullWindowClampTests(unittest.TestCase):
    """The window clamp, per scope (lane `pull-window-dated-scope`, 2026-09-17).

    MEASURED on production over the 24 h to 2026-09-17 12:13Z: refresh-worker's 2 h
    clamp fired 3 times on `scope=2026-09-17`, skipping 3.9, 36.7 and 47.0 minutes
    of tomorrow's changes; and the first request of every NEW date scope looked
    back exactly 2.00 h, so anything written for that date earlier was never
    asked for. The clamp exists for the 2026-07-25 OOM (an unbounded response
    held in memory on two services). A DATED request is now bounded without it:
    the date prefilter, the 48 MB budget, the 8 MB per-file cap and the
    `next_since` resume. So a dated scope reaches back 24 h, and an undated one
    keeps 2 h.
    """

    DAY = 24 * 3600.0

    def setUp(self) -> None:
        self.store = _Store()
        self._patches = [
            patch("syndicate.features.shared.refresh_state_store.read_json_file", side_effect=self.store.read),
            patch("syndicate.features.shared.refresh_state_store.write_json_file", side_effect=self.store.write),
            patch.dict("os.environ", {"RENDER_SERVICE_NAME": "refresh-worker", "SYNDICATE_REFRESH_LANE": ""}, clear=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _since(self, date_str, printed=None):
        return artifact_publisher._hot_artifact_pull_since_epoch(pull_started_epoch=NOW, date_str=date_str)

    @staticmethod
    def _clamped(printed) -> bool:
        return any("PULL_WINDOW_CLAMPED" in str(c.args[0]) for c in printed.call_args_list if c.args)

    def test_the_dated_cap_is_24_hours(self) -> None:
        self.assertEqual(getattr(artifact_publisher, "_MAX_DATED_PULL_WINDOW_SECONDS", None), self.DAY)

    def test_a_dated_floor_3_hours_old_is_NOT_jumped(self) -> None:
        """THE DEFECT: this returned NOW - 2 h, and the hour before it was never pulled."""
        artifact_publisher._record_hot_artifact_pull_watermark(NOW - 3 * 3600.0, date_str="2026-09-16")
        with patch("builtins.print") as printed:
            since = self._since("2026-09-16")
        self.assertEqual(since, NOW - 3 * 3600.0)
        self.assertFalse(self._clamped(printed))

    def test_a_NEW_dated_scope_looks_back_24_hours(self) -> None:
        """No watermark yet for this date: the first pull used to see only 2 h."""
        self.assertEqual(self._since("2026-09-18"), NOW - self.DAY)

    def test_a_dated_floor_older_than_24_hours_is_clamped_and_LOUD(self) -> None:
        artifact_publisher._record_hot_artifact_pull_watermark(NOW - 30 * 3600.0, date_str="2026-09-16")
        with patch("builtins.print") as printed:
            since = self._since("2026-09-16")
        self.assertEqual(since, NOW - self.DAY)
        self.assertTrue(self._clamped(printed), "a clamp that skips changes must say so")

    def test_an_UNDATED_scope_keeps_the_2_hour_clamp(self) -> None:
        """No date filter bounds an undated request, so the 07-25 guard stays."""
        self.assertEqual(self._since(None), NOW - 2 * 3600.0)
        artifact_publisher._record_hot_artifact_pull_watermark(NOW - 3 * 3600.0, date_str=None)
        with patch("builtins.print") as printed:
            since = self._since(None)
        self.assertEqual(since, NOW - 2 * 3600.0)
        self.assertTrue(self._clamped(printed))

    def test_the_clamp_is_quiet_when_it_changes_nothing(self) -> None:
        artifact_publisher._record_hot_artifact_pull_watermark(NOW - 600.0, date_str="2026-09-16")
        with patch("builtins.print") as printed:
            since = self._since("2026-09-16")
        self.assertEqual(since, NOW - 600.0)
        self.assertFalse(self._clamped(printed))


if __name__ == "__main__":
    unittest.main()
