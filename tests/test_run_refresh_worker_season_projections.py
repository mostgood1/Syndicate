from __future__ import annotations

import os
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
