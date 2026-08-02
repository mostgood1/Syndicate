from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import scripts.run_refresh_worker as worker


class SeasonProjectionAutorunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        os.environ.pop("SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN", None)
        self.refresh_cycle: dict[str, int] = {}
        self.latest_manifest_path = Path("fake_manifest.json")
        self.worker_status_path = Path("fake_status.json")
        # _launch_autorun_season_projections now writes a real
        # season_projection_launch_<sport>.json via the "already running"
        # guard added 2026-08-02 -- isolate reports_root so these tests
        # neither pollute the real repo's reports/ dir nor leak launch
        # state across test runs.
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._reports_root_patch = patch(
            "syndicate.features.shared.refresh_state_store.reports_root",
            return_value=Path(self._temp_dir.name),
        )
        self._reports_root_patch.start()
        self.addCleanup(self._reports_root_patch.stop)

    def _call(self):
        return worker._launch_autorun_season_projections(
            latest_manifest_path=self.latest_manifest_path,
            worker_status_path=self.worker_status_path,
            refresh_cycle=self.refresh_cycle,
        )

    def test_env_off_by_default_is_a_noop(self) -> None:
        with patch.object(worker, "_active_sports_for_date", return_value="nfl,ncaaf"), patch("subprocess.Popen") as popen:
            result = self._call()
        self.assertFalse(result)
        popen.assert_not_called()

    def test_out_of_season_is_a_noop(self) -> None:
        os.environ["SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
        with patch.object(worker, "_active_sports_for_date", return_value=""), patch("subprocess.Popen") as popen:
            result = self._call()
        self.assertFalse(result)
        popen.assert_not_called()

    def test_no_target_week_is_a_noop(self) -> None:
        os.environ["SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
        with patch.object(worker, "_active_sports_for_date", return_value="nfl,ncaaf"), patch.object(
            worker, "_season_projection_target_week", return_value=None,
        ), patch("subprocess.Popen") as popen:
            result = self._call()
        self.assertFalse(result)
        popen.assert_not_called()

    def test_fresh_artifact_is_a_noop(self) -> None:
        os.environ["SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
        with patch.object(worker, "_active_sports_for_date", return_value="nfl,ncaaf"), patch.object(
            worker, "_season_projection_target_week", return_value=1,
        ), patch.object(
            worker, "_file_age_seconds", return_value=10.0,
        ), patch("subprocess.Popen") as popen:
            result = self._call()
        self.assertFalse(result)
        popen.assert_not_called()

    def test_stale_artifact_launches_and_claims_one_sport(self) -> None:
        os.environ["SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
        fake_process = type("FakeProcess", (), {"pid": 4242})()
        with patch.object(worker, "_active_sports_for_date", return_value="nfl,ncaaf"), patch.object(
            worker, "_season_projection_target_week", return_value=1,
        ), patch.object(
            worker, "_file_age_seconds", return_value=None,  # missing artifact
        ), patch.object(
            worker, "_write_worker_status",
        ) as write_status, patch(
            "subprocess.Popen", return_value=fake_process,
        ) as popen:
            result = self._call()
        self.assertTrue(result)
        popen.assert_called_once()
        self.assertEqual(self.refresh_cycle.get("claimed_count"), 1)
        write_status.assert_called_once()
        self.assertEqual(write_status.call_args.kwargs["state"], "launched")

    def test_missing_artifact_never_becomes_stale_check_bug(self) -> None:
        # _file_age_seconds returning None (file doesn't exist) must be
        # treated as "needs a refresh," not skipped -- confirms the
        # `age_seconds is not None and age_seconds < interval` guard reads
        # correctly for the missing-file case (the same shape MLB's
        # sibling autorun already uses for the same reason).
        os.environ["SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
        with patch.object(worker, "_active_sports_for_date", return_value="nfl"), patch.object(
            worker, "_season_projection_target_week", return_value=1,
        ), patch.object(
            worker, "_file_age_seconds", return_value=None,
        ), patch.object(
            worker, "_write_worker_status",
        ), patch(
            "subprocess.Popen",
        ) as popen:
            result = self._call()
        self.assertTrue(result)
        popen.assert_called_once()

    def test_already_running_sport_is_not_relaunched(self) -> None:
        # Confirmed live 2026-08-02: with no "already running" guard at all,
        # this autorun piled up 18 -> 56+ concurrent
        # generate_smartsim2_nfl_projections.py processes over ~2 hours
        # (each tick's artifact-staleness check stayed true the whole time a
        # prior run was still in progress, since the artifact's mtime only
        # moves once the run finishes writing it), driving refresh-worker
        # container memory from 31.6% to 53.8% of its 4GB limit and starving
        # a concurrently running MLB Sunday-slate sim of CPU on the same
        # container. This locks in that a still-running sport is skipped
        # rather than relaunched.
        os.environ["SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN"] = "true"
        with patch.object(worker, "_active_sports_for_date", return_value="nfl,ncaaf"), patch.object(
            worker, "_season_projection_target_week", return_value=1,
        ), patch.object(
            worker, "_file_age_seconds", return_value=None,
        ), patch.object(
            worker, "_season_projection_process_still_running", return_value=True,
        ), patch("subprocess.Popen") as popen:
            result = self._call()
        self.assertFalse(result)
        popen.assert_not_called()


class SeasonProjectionProcessStillRunningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._reports_root_patch = patch(
            "syndicate.features.shared.refresh_state_store.reports_root",
            return_value=Path(self._temp_dir.name),
        )
        self._reports_root_patch.start()
        self.addCleanup(self._reports_root_patch.stop)

    def test_no_prior_launch_is_not_running(self) -> None:
        self.assertFalse(worker._season_projection_process_still_running("nfl"))

    def test_recorded_live_pid_is_running(self) -> None:
        worker._record_season_projection_launch("nfl", os.getpid())
        with patch("syndicate.features.shared.live_refresh_loop._process_exists", return_value=True):
            self.assertTrue(worker._season_projection_process_still_running("nfl"))

    def test_recorded_dead_pid_is_not_running(self) -> None:
        worker._record_season_projection_launch("nfl", os.getpid())
        with patch("syndicate.features.shared.live_refresh_loop._process_exists", return_value=False):
            self.assertFalse(worker._season_projection_process_still_running("nfl"))

    def test_sports_are_tracked_independently(self) -> None:
        # nfl and ncaaf must not block each other -- confirmed by keying the
        # launch-state file per sport.
        worker._record_season_projection_launch("nfl", os.getpid())
        with patch("syndicate.features.shared.live_refresh_loop._process_exists", return_value=True):
            self.assertTrue(worker._season_projection_process_still_running("nfl"))
            self.assertFalse(worker._season_projection_process_still_running("ncaaf"))

    def test_hung_process_past_ceiling_is_treated_as_not_running(self) -> None:
        state_path = worker._season_projection_launch_state_path("nfl")
        from syndicate.features.shared.refresh_state_store import write_json_file

        write_json_file(
            state_path,
            {"sport": "nfl", "pid": os.getpid(), "started_at_epoch": 1.0},
        )
        with patch("syndicate.features.shared.live_refresh_loop._process_exists", return_value=True), patch.object(
            worker.os, "kill",
        ) as kill:
            self.assertFalse(worker._season_projection_process_still_running("nfl"))
        kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
