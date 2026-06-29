from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.shared import live_refresh_loop
from scripts import run_live_odds_refresh_worker


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
                "SYNDICATE_LIVE_ODDS_REFRESH_MODE": "full",
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
            mode="full",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
        )

    def test_run_tick_defaults_to_manifest_only_on_render(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "RENDER_SERVICE_ID": "svc-test",
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_MODE": "full",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-06-07"), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "pending_external"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once_with(
            date="2026-06-07",
            sports=None,
            phase="live",
            regions="us",
            mode="full",
            execution_mode="source",
            launch_mode="manifest_only",
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
                "SYNDICATE_LIVE_ODDS_REFRESH_MODE": "full",
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
            mode="full",
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

    def test_create_app_starts_shared_live_refresh_loop(self) -> None:
        with patch.dict(os.environ, {"RENDER": "", "RENDER_EXTERNAL_URL": "", "RENDER_SERVICE_ID": ""}, clear=False), patch(
            "syndicate.app.start_live_refresh_background_loop"
        ) as mocked_start, patch("syndicate.app.Flask.before_request", side_effect=lambda func: func()):
            create_app()

        mocked_start.assert_called_once()

    def test_create_app_skips_shared_live_refresh_loop_on_render_web(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "RENDER_SERVICE_ID": "svc-test",
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
            },
            clear=False,
        ), patch("syndicate.app.start_live_refresh_background_loop") as mocked_start, patch(
            "syndicate.app.Flask.before_request", side_effect=lambda func: func()
        ):
            create_app()

        mocked_start.assert_not_called()

    def test_run_live_odds_refresh_worker_run_once_releases_lock(self) -> None:
        with patch.object(run_live_odds_refresh_worker, "_acquire_process_lock", return_value=True) as mocked_acquire, patch.object(
            run_live_odds_refresh_worker,
            "_run_tick",
            return_value=None,
        ) as mocked_tick, patch.object(run_live_odds_refresh_worker, "_release_process_lock") as mocked_release, patch.object(
            run_live_odds_refresh_worker,
            "_live_refresh_loop_interval_seconds",
            return_value=30,
        ), patch.object(run_live_odds_refresh_worker.signal, "signal", side_effect=ValueError("skip signals")), patch.object(
            run_live_odds_refresh_worker.sys,
            "argv",
            ["run_live_odds_refresh_worker.py", "--run-once"],
        ):
            exit_code = run_live_odds_refresh_worker.main()

        self.assertEqual(exit_code, 0)
        mocked_acquire.assert_called_once()
        mocked_tick.assert_called_once()
        mocked_release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
