from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.shared import live_refresh_loop


class LiveRefreshLoopTests(unittest.TestCase):
    def tearDown(self) -> None:
        live_refresh_loop._LIVE_REFRESH_LOOP_STOP.set()
        live_refresh_loop._LIVE_REFRESH_LOOP_THREAD = None
        live_refresh_loop._release_process_lock()

    def test_run_tick_launches_live_refresh_with_expected_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_SKIP_MIRROR": "true",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-06-07"), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once_with(
            date="2026-06-07",
            sports=None,
            phase="live",
            regions="us",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
        )

    def test_run_tick_uses_explicit_launch_mode_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_LAUNCH_MODE": "manifest_only",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-06-07"), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once_with(
            date="2026-06-07",
            sports=None,
            phase="live",
            regions="us",
            execution_mode="source",
            launch_mode="manifest_only",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
        )

    def test_run_tick_marks_active_refresh_as_skipped(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"}, clear=False), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            side_effect=ValueError("A refresh run is already active (pid=123). Cancel it before starting a new run."),
        ):
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertIn("already active", payload["error"])

    def test_start_loop_returns_false_when_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            started = live_refresh_loop.start_live_refresh_background_loop()

        self.assertFalse(started)

    def test_create_app_attempts_to_start_shared_live_refresh_loop(self) -> None:
        with patch("syndicate.app.start_live_refresh_background_loop") as mocked_start:
            create_app()

        mocked_start.assert_called_once()


if __name__ == "__main__":
    unittest.main()