"""`#389`. A missing artifact is UNKNOWN age, not zero age.

MEASURED 2026-08-12 on refresh-worker: `generate_smartsim2_nfl_projections.py
--season 2026 --week 1` ran 83 times in 43.2h and the preseason variant 72
times -- a median of **5 minutes** between episode starts, ~3 min each, against
a `SEASON_PROJECTION_REFRESH_INTERVAL_SECONDS` default of **86400**. ~90
launches/day and ~4.5 process-hours/day against an expectation of two, on the
4GB worker that also runs MLB sims and whose memory headroom gates them.

The guard mapped an unknown onto its permissive branch:

    age_seconds = _file_age_seconds(artifact_path)
    if age_seconds is not None and age_seconds < interval:
        continue

`_file_age_seconds` returns None when `path.stat()` raises -- when the artifact
is MISSING -- so an artifact that never appears makes the sport permanently
stale forever.

The tension these tests pin down: the fix must NOT simply refuse to launch when
the artifact is absent, because a genuine first run has no artifact either.
Replacing a busy loop with a dead loop is not a fix.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "run_refresh_worker_for_tests", REPO_ROOT / "scripts" / "run_refresh_worker.py"
)
worker = importlib.util.module_from_spec(_spec)
sys.modules["run_refresh_worker_for_tests"] = worker
_spec.loader.exec_module(worker)

INTERVAL = 86400
SPORT = "nfl"
SEASON = 2026
WEEK = 1


class SeasonProjectionStalenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.artifact = self.root / f"smartsim2_projections_{SEASON}_wk{WEEK}.csv"
        self._marker: dict | None = None

        interval_patch = patch.object(worker, "_season_projection_refresh_interval_seconds", return_value=INTERVAL)
        interval_patch.start()
        self.addCleanup(interval_patch.stop)

        store = {
            "read_json_file": lambda _path: self._marker,
            "write_json_file": self._write_marker,
            "reports_root": lambda: self.root,
        }
        store_patch = patch.object(worker, "_refresh_state_store", return_value=store)
        store_patch.start()
        self.addCleanup(store_patch.stop)

        worker._LAST_SEASON_PROJECTION_MISSING_LOG.clear()

    def _write_marker(self, _path, payload) -> None:
        self._marker = payload

    def _decide(self, *, season: int = SEASON, week: int = WEEK) -> tuple[bool, str]:
        return worker._season_projection_should_launch(SPORT, self.artifact, season=season, week=week)

    def _touch_artifact(self, age_seconds: float) -> None:
        self.artifact.write_text("x", encoding="utf-8")
        stamp = time.time() - age_seconds
        import os

        os.utime(self.artifact, (stamp, stamp))

    # -- the measured bug -------------------------------------------------

    def test_missing_artifact_after_a_recent_launch_does_not_relaunch(self) -> None:
        """THE bug: artifact absent + we launched 5 minutes ago. Old code
        relaunched; ~90 times a day."""
        worker._record_season_projection_launch(SPORT, 4242, season=SEASON, week=WEEK)
        self._marker["started_at_epoch"] = time.time() - 300

        should_launch, reason = self._decide()

        self.assertFalse(should_launch)
        self.assertTrue(reason.startswith("artifact_missing_after_launch"), reason)

    def test_the_condition_is_logged_and_rate_limited(self) -> None:
        """It was silent for the entire life of the bug -- but it is evaluated
        every ~30s tick, so it must not become 2,880 lines/day either."""
        worker._record_season_projection_launch(SPORT, 4242, season=SEASON, week=WEEK)
        self._marker["started_at_epoch"] = time.time() - 300
        _, reason = self._decide()

        with patch("builtins.print") as mocked_print:
            for _ in range(5):
                worker._log_season_projection_skip(SPORT, reason)

        self.assertEqual(mocked_print.call_count, 1)
        self.assertIn("SEASON_PROJECTION_ARTIFACT_MISSING", mocked_print.call_args[0][0])

    def test_healthy_steady_state_is_not_logged(self) -> None:
        """`artifact_fresh` every 30s would drown the line that matters."""
        with patch("builtins.print") as mocked_print:
            worker._log_season_projection_skip(SPORT, "artifact_fresh age_seconds=10 interval_seconds=86400")
        mocked_print.assert_not_called()

    # -- the fix must not become a dead loop ------------------------------

    def test_first_ever_run_still_launches(self) -> None:
        """No artifact and no prior launch is exactly a cold start. Refusing
        here would replace a busy loop with a dead one."""
        should_launch, reason = self._decide()
        self.assertTrue(should_launch)
        self.assertTrue(reason.startswith("artifact_missing_no_prior_launch"), reason)

    def test_missing_artifact_retries_after_the_interval(self) -> None:
        """Backoff, not abandonment."""
        worker._record_season_projection_launch(SPORT, 4242, season=SEASON, week=WEEK)
        self._marker["started_at_epoch"] = time.time() - (INTERVAL + 60)

        should_launch, reason = self._decide()

        self.assertTrue(should_launch)
        self.assertTrue(reason.startswith("artifact_missing_retry"), reason)

    def test_a_new_week_is_not_suppressed_by_last_weeks_launch(self) -> None:
        """The regression the season/week fields exist to prevent: a marker from
        week 1 must not read as 'already tried' for week 2, or the new week's
        first run is suppressed for a full interval."""
        worker._record_season_projection_launch(SPORT, 4242, season=SEASON, week=WEEK)
        self._marker["started_at_epoch"] = time.time() - 300

        should_launch, reason = self._decide(week=WEEK + 1)

        self.assertTrue(should_launch)
        self.assertTrue(reason.startswith("artifact_missing_no_prior_launch"), reason)

    def test_a_pre_389_marker_without_week_fields_does_not_suppress(self) -> None:
        """Markers written before this change carry no season/week. Unknown must
        not map onto the suppressing branch -- that is the same defect class."""
        self._marker = {"sport": SPORT, "pid": 1, "started_at_epoch": time.time() - 60}

        should_launch, reason = self._decide()

        self.assertTrue(should_launch)
        self.assertTrue(reason.startswith("artifact_missing_no_prior_launch"), reason)

    # -- the artifact-age path still works --------------------------------

    def test_fresh_artifact_does_not_relaunch(self) -> None:
        self._touch_artifact(60)
        should_launch, reason = self._decide()
        self.assertFalse(should_launch)
        self.assertTrue(reason.startswith("artifact_fresh"), reason)

    def test_stale_artifact_relaunches(self) -> None:
        self._touch_artifact(INTERVAL + 60)
        should_launch, reason = self._decide()
        self.assertTrue(should_launch)
        self.assertTrue(reason.startswith("artifact_stale"), reason)

    def test_a_present_artifact_ignores_the_launch_marker(self) -> None:
        """A fresh artifact is the direct answer; a recent launch must not
        override it, and a stale launch must not force a relaunch."""
        self._touch_artifact(60)
        worker._record_season_projection_launch(SPORT, 4242, season=SEASON, week=WEEK)
        self._marker["started_at_epoch"] = time.time() - (INTERVAL * 3)

        should_launch, _ = self._decide()

        self.assertFalse(should_launch)


class SeasonProjectionAutorunWiringTests(unittest.TestCase):
    """The decision above is worthless if the autorun does not consult it.

    Every test in the class above drives `_season_projection_should_launch`
    directly, so all of them fail against `HEAD` merely because the function
    does not exist there -- that proves the helper is new, NOT that it changed
    behaviour. These tests drive the **real** `_launch_autorun_season_projections`
    and assert on whether a subprocess is actually spawned, which is the only
    thing that distinguishes a wired-in fix from an inert one. `#382` and `#388`
    are both on the list because a correct branch was never reached.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.artifact = self.root / "artifact.csv"
        self._marker: dict | None = None

        for name, value in [
            ("_season_projection_auto_refresh_enabled", True),
            ("_season_projection_process_still_running", False),
            ("_season_projection_target_week", WEEK),
        ]:
            p = patch.object(worker, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

        for name, value in [
            ("_active_sports_for_date", SPORT),
            ("_season_projection_artifact_path", self.artifact),
            ("_season_projection_script_args", ["python", "-c", "pass"]),
        ]:
            p = patch.object(worker, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

        sports_patch = patch.object(worker, "_SEASON_PROJECTION_SPORTS", (SPORT,))
        sports_patch.start()
        self.addCleanup(sports_patch.stop)

        interval_patch = patch.object(worker, "_season_projection_refresh_interval_seconds", return_value=INTERVAL)
        interval_patch.start()
        self.addCleanup(interval_patch.stop)

        store = {
            "read_json_file": lambda _path: self._marker,
            "write_json_file": self._write_marker,
            "reports_root": lambda: self.root,
        }
        store_patch = patch.object(worker, "_refresh_state_store", return_value=store)
        store_patch.start()
        self.addCleanup(store_patch.stop)

        status_patch = patch.object(worker, "_write_worker_status")
        status_patch.start()
        self.addCleanup(status_patch.stop)

        # getattr, not attribute access: this global does not exist on the
        # pre-`#389` module, and setUp blowing up there would make these
        # tests 'fail' for the wrong reason -- masking whether the autorun
        # actually spawns, which is the only thing they exist to check.
        getattr(worker, "_LAST_SEASON_PROJECTION_MISSING_LOG", {}).clear()

    def _write_marker(self, _path, payload) -> None:
        self._marker = payload

    def _run(self):
        with patch.object(worker.subprocess, "Popen") as mocked_popen:
            mocked_popen.return_value.pid = 4242
            worker._launch_autorun_season_projections(
                latest_manifest_path=self.root / "manifest.json",
                worker_status_path=self.root / "status.json",
                refresh_cycle={},
            )
        return mocked_popen

    def test_autorun_does_not_spawn_when_artifact_missing_after_recent_launch(self) -> None:
        """The measured bug, at the call site: ~90 launches/day became this."""
        self._marker = {
            "sport": SPORT, "pid": 1, "season": SEASON, "week": WEEK,
            "started_at_epoch": time.time() - 300,
        }

        mocked_popen = self._run()

        mocked_popen.assert_not_called()

    def test_autorun_still_spawns_on_a_cold_start(self) -> None:
        """And the fix must not have turned the busy loop into a dead one."""
        self._marker = None

        mocked_popen = self._run()

        mocked_popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
