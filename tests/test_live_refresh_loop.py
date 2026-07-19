from __future__ import annotations

import csv
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-06-07"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
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
            force_refresh=False,
        )

    def test_run_tick_defaults_to_detached_subprocess_on_render(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "RENDER_SERVICE_ID": "svc-test",
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_MODE": "full",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-06-07"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
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
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
            force_refresh=False,
        )

    def test_run_tick_uses_explicit_launch_mode_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_LAUNCH_MODE": "manifest_only",
                "SYNDICATE_LIVE_ODDS_REFRESH_MODE": "full",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-06-07"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
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
            force_refresh=False,
        )

    def test_run_tick_marks_active_refresh_as_skipped(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true", "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false"},
            clear=False,
        ), patch.object(live_refresh_loop, "_should_force_sim_rerun", return_value=False), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            side_effect=ValueError("A refresh run is already active (pid=123). Cancel it before starting a new run."),
        ):
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertIn("already active", payload["error"])

    def test_live_refresh_loop_interval_defaults_to_sixty_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            interval_seconds = live_refresh_loop._live_refresh_loop_interval_seconds()

        self.assertEqual(interval_seconds, 60)

    def test_idle_interval_defaults_to_fifteen_minutes(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            interval_seconds = live_refresh_loop._live_refresh_loop_idle_interval_seconds()

        self.assertEqual(interval_seconds, 900)

    def test_mlb_has_live_game_reads_live_lens_counts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            report_path = data_root / "mlb_source" / "source_artifacts" / "data" / "live_lens" / "live_lens_report_2026_07_13.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({"counts": {"live": 2}}), encoding="utf-8")

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertTrue(live_refresh_loop._mlb_has_live_game("2026-07-13"))

            report_path.write_text(json.dumps({"counts": {"live": 0}}), encoding="utf-8")
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertFalse(live_refresh_loop._mlb_has_live_game("2026-07-13"))

    def test_mlb_has_live_game_false_when_report_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": tmp_dir}, clear=False):
                self.assertFalse(live_refresh_loop._mlb_has_live_game("2026-07-13"))

    def test_wnba_has_live_game_reads_last_jsonl_line(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            state_path = (
                data_root
                / "wnba_source"
                / "source_artifacts"
                / "data"
                / "processed"
                / "live_snapshots"
                / "live_state_2026-07-13.jsonl"
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"payload": {"games": [{"in_progress": False}]}}) + "\n"
                + json.dumps({"payload": {"games": [{"in_progress": True}, {"in_progress": False}]}}) + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertTrue(live_refresh_loop._wnba_has_live_game("2026-07-13"))

    def test_wnba_has_live_game_false_when_no_game_in_progress(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            state_path = (
                data_root
                / "wnba_source"
                / "source_artifacts"
                / "data"
                / "processed"
                / "live_snapshots"
                / "live_state_2026-07-13.jsonl"
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"payload": {"games": [{"in_progress": False}]}}) + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertFalse(live_refresh_loop._wnba_has_live_game("2026-07-13"))

    def test_nba_has_live_game_reads_last_jsonl_line(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            state_path = (
                data_root
                / "nba_source"
                / "source_artifacts"
                / "data"
                / "processed"
                / "live_snapshots"
                / "live_state_2026-07-13.jsonl"
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"payload": {"games": [{"in_progress": False}]}}) + "\n"
                + json.dumps({"payload": {"games": [{"in_progress": True}, {"in_progress": False}]}}) + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertTrue(live_refresh_loop._nba_has_live_game("2026-07-13"))

    def test_nba_has_live_game_false_when_no_game_in_progress(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            state_path = (
                data_root
                / "nba_source"
                / "source_artifacts"
                / "data"
                / "processed"
                / "live_snapshots"
                / "live_state_2026-07-13.jsonl"
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"payload": {"games": [{"in_progress": False}]}}) + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertFalse(live_refresh_loop._nba_has_live_game("2026-07-13"))

    def test_nhl_has_live_game_reads_scoreboard_csv(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            scoreboard_path = (
                data_root
                / "nhl_source"
                / "source_artifacts"
                / "data"
                / "odds"
                / "games"
                / "date=2026-07-13"
                / "scoreboard.csv"
            )
            scoreboard_path.parent.mkdir(parents=True, exist_ok=True)
            with scoreboard_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["gameState"])
                writer.writeheader()
                writer.writerow({"gameState": "OFF"})
                writer.writerow({"gameState": "LIVE"})

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                self.assertTrue(live_refresh_loop._nhl_has_live_game("2026-07-13"))

    def test_nhl_has_live_game_false_when_scoreboard_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": tmp_dir}, clear=False):
                self.assertFalse(live_refresh_loop._nhl_has_live_game("2026-07-13"))

    def test_run_tick_uses_pregame_phase_and_idle_interval_when_nothing_live(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-13"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=False
        ), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_read_last_pregame_launch", return_value={}
        ), patch.object(
            live_refresh_loop, "_record_pregame_launch"
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()
            interval_seconds = live_refresh_loop._live_refresh_loop_interval_for_meta(payload)

        self.assertEqual(payload["phase"], "pregame")
        self.assertFalse(payload["anyLive"])
        self.assertEqual(interval_seconds, 900)
        mocked_launch.assert_called_once_with(
            date="2026-07-13",
            sports=None,
            phase="pregame",
            regions="us",
            mode="fast",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
            force_refresh=False,
        )

    def test_pregame_relaunch_blocked_false_when_no_prior_launch(self) -> None:
        with patch.object(live_refresh_loop, "_read_last_pregame_launch", return_value={}):
            blocked = live_refresh_loop._pregame_relaunch_blocked(now_epoch=1000.0, date_str="2026-07-16")
        self.assertFalse(blocked)

    def test_pregame_relaunch_blocked_true_within_cooldown_window(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LIVE_ODDS_PREGAME_RELAUNCH_COOLDOWN_SECONDS": "1800"}, clear=False
        ), patch.object(
            live_refresh_loop,
            "_read_last_pregame_launch",
            return_value={"epoch": 1000.0, "date": "2026-07-16"},
        ):
            blocked = live_refresh_loop._pregame_relaunch_blocked(now_epoch=1500.0, date_str="2026-07-16")
        self.assertTrue(blocked)

    def test_pregame_relaunch_blocked_false_after_cooldown_expires(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LIVE_ODDS_PREGAME_RELAUNCH_COOLDOWN_SECONDS": "1800"}, clear=False
        ), patch.object(
            live_refresh_loop,
            "_read_last_pregame_launch",
            return_value={"epoch": 1000.0, "date": "2026-07-16"},
        ):
            blocked = live_refresh_loop._pregame_relaunch_blocked(now_epoch=1000.0 + 1801.0, date_str="2026-07-16")
        self.assertFalse(blocked)

    def test_pregame_relaunch_blocked_false_for_different_date(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LIVE_ODDS_PREGAME_RELAUNCH_COOLDOWN_SECONDS": "1800"}, clear=False
        ), patch.object(
            live_refresh_loop,
            "_read_last_pregame_launch",
            return_value={"epoch": 1000.0, "date": "2026-07-15"},
        ):
            blocked = live_refresh_loop._pregame_relaunch_blocked(now_epoch=1500.0, date_str="2026-07-16")
        self.assertFalse(blocked)

    def test_run_tick_skips_pregame_relaunch_within_cooldown(self) -> None:
        # The production incident this guards against: a fixed 60s outer
        # sleep let every tick relaunch the full predict-date + SmartSim
        # pipeline before the previous cold-start attempt (20-30+ minutes)
        # could finish, so game_cards_<date>.csv never got produced. This
        # cooldown blocks a relaunch independently of the outer interval fix
        # and of _assert_no_active_refresh_run's own PID-based guard.
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-16"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=False
        ), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_pregame_relaunch_blocked", return_value=True
        ), patch.object(
            live_refresh_loop, "_record_pregame_launch"
        ) as mocked_record, patch.object(
            live_refresh_loop,
            "launch_refresh_run",
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertIn("cooldown", payload["error"])
        mocked_launch.assert_not_called()
        mocked_record.assert_not_called()

    def test_run_tick_defers_odds_refresh_while_mlb_daily_sim_is_running(self) -> None:
        # Production incident: is_refresh_run_active() only stops a NEW sim
        # from launching on top of an in-flight odds refresh -- it does
        # nothing once a sim IS running, so the live-phase ~60s tick kept
        # relaunching the full odds-refresh pipeline (which can spike WNBA to
        # 1.3-1.5GB RSS) on top of the resident sim process tree for its
        # whole ~45-55min run. ALL_PROCESS_MEMORY snapshots from Render
        # showed the container hitting 2048/2048MB (100%) with both
        # pipelines resident at once. This is the symmetric gate.
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true", "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-18"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertIn("MLB daily sim is still running", payload["error"])
        mocked_launch.assert_not_called()

    def test_run_tick_still_defers_past_starvation_ceiling_when_override_disabled(self) -> None:
        # Reverted 2026-07-18: the starvation-ceiling override ("force the
        # refresh through past N minutes regardless of sim state") was found
        # in production to reintroduce the exact stack-two-heavy-pipelines
        # OOM the sim-mutex gate exists to prevent -- WNBA's refresh leg
        # alone spikes to ~1.3-1.5GB RSS in this 2048MB container, and sims
        # chain back-to-back for hours on a live slate, so "force through"
        # fired into an actually-still-running sim almost every time, not
        # occasionally. The override now defaults OFF: even when
        # _odds_refresh_starved() says the board has gone stale long enough,
        # the tick must still defer unless the override is explicitly
        # enabled.
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true", "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-18"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop, "_odds_refresh_starved", return_value=True
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertIn("MLB daily sim is still running", payload["error"])
        mocked_launch.assert_not_called()

    def test_run_tick_forces_odds_refresh_past_starvation_ceiling_when_override_enabled(self) -> None:
        # The override mechanism itself is kept (not deleted) for deliberate,
        # opt-in future use -- e.g. once paired with an actual
        # memory-headroom check, or once WNBA's own RSS spike is fixed --
        # rather than the blind timer this was originally shipped as.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_STARVATION_OVERRIDE_ENABLED": "true",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-18"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop, "_odds_refresh_starved", return_value=True
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()

    def test_run_tick_uses_live_phase_and_short_interval_when_a_game_is_live(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-13"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=True
        ), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()
            interval_seconds = live_refresh_loop._live_refresh_loop_interval_for_meta(payload)

        self.assertEqual(payload["phase"], "live")
        self.assertTrue(payload["anyLive"])
        self.assertEqual(interval_seconds, 60)
        mocked_launch.assert_called_once_with(
            date="2026-07-13",
            sports=None,
            phase="live",
            regions="us",
            mode="fast",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
            force_refresh=False,
        )

    def test_lineup_check_interval_defaults_to_thirty_minutes(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            interval_seconds = live_refresh_loop._lineup_check_interval_seconds()

        self.assertEqual(interval_seconds, 1800)

    def test_should_force_sim_rerun_false_before_interval_elapses(self) -> None:
        with patch.object(
            live_refresh_loop,
            "_read_last_lineup_check",
            return_value={"epoch": 1000.0, "date": "2026-07-13", "fingerprints": {"nba": "a", "wnba": "b"}},
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False
        ), patch.object(live_refresh_loop, "_fetch_injuries") as mocked_fetch, patch.object(
            live_refresh_loop, "_record_lineup_check"
        ) as mocked_record:
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 60, date_str="2026-07-13")

        self.assertFalse(result)
        mocked_fetch.assert_not_called()
        mocked_record.assert_not_called()

    def test_should_force_sim_rerun_true_on_first_call(self) -> None:
        with patch.object(
            live_refresh_loop, "_read_last_lineup_check", return_value={}
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False
        ), patch.object(live_refresh_loop, "_fetch_injuries", return_value=True), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="a"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="b"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ) as mocked_record:
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0, date_str="2026-07-13")

        self.assertTrue(result)
        mocked_record.assert_called_once_with(1000.0, "2026-07-13", {"nba": "a", "wnba": "b"})

    def test_should_force_sim_rerun_false_when_fingerprints_unchanged(self) -> None:
        with patch.object(
            live_refresh_loop,
            "_read_last_lineup_check",
            return_value={"epoch": 1000.0, "date": "2026-07-13", "fingerprints": {"nba": "a", "wnba": "b"}},
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False
        ), patch.object(live_refresh_loop, "_fetch_injuries", return_value=True), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="a"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="b"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ) as mocked_record:
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 1800, date_str="2026-07-13")

        self.assertFalse(result)
        mocked_record.assert_called_once_with(1000.0 + 1800, "2026-07-13", {"nba": "a", "wnba": "b"})

    def test_should_force_sim_rerun_true_when_a_fingerprint_changed(self) -> None:
        with patch.object(
            live_refresh_loop,
            "_read_last_lineup_check",
            return_value={"epoch": 1000.0, "date": "2026-07-13", "fingerprints": {"nba": "a", "wnba": "b"}},
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False
        ), patch.object(live_refresh_loop, "_fetch_injuries", return_value=True), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="a"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="CHANGED"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ) as mocked_record:
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 1800, date_str="2026-07-13")

        self.assertTrue(result)
        mocked_record.assert_called_once_with(1000.0 + 1800, "2026-07-13", {"nba": "a", "wnba": "CHANGED"})

    def test_should_force_sim_rerun_true_on_new_date_even_if_not_due(self) -> None:
        with patch.object(
            live_refresh_loop,
            "_read_last_lineup_check",
            return_value={"epoch": 1000.0, "date": "2026-07-12", "fingerprints": {"nba": "a", "wnba": "b"}},
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False
        ), patch.object(live_refresh_loop, "_fetch_injuries", return_value=True), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="a"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="b"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ):
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 60, date_str="2026-07-13")

        self.assertTrue(result)

    def test_should_force_sim_rerun_rechecks_within_tip_off_window_even_inside_interval(self) -> None:
        # Even when the normal 30-minute interval throttle would otherwise skip
        # re-checking, a scheduled event within the tip-off force window should
        # still trigger a real fingerprint re-check (not a blind force=True --
        # the actual decision still depends on whether the fingerprint changed).
        with patch.object(
            live_refresh_loop,
            "_read_last_lineup_check",
            return_value={"epoch": 1000.0, "date": "2026-07-13", "fingerprints": {"nba": "a", "wnba": "b"}},
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=True
        ), patch.object(live_refresh_loop, "_fetch_injuries", return_value=True) as mocked_fetch, patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="a"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="CHANGED"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ) as mocked_record:
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 60, date_str="2026-07-13")

        self.assertTrue(mocked_fetch.called)
        self.assertTrue(result)
        mocked_record.assert_called_once_with(1000.0 + 60, "2026-07-13", {"nba": "a", "wnba": "CHANGED"})

    def test_run_tick_uses_full_mode_and_forces_refresh_when_lineup_changed(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-13"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=True
        ), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=True
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["simRerunTriggered"])
        mocked_launch.assert_called_once_with(
            date="2026-07-13",
            sports=None,
            phase="live",
            regions="us",
            mode="full",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
            force_refresh=True,
        )

    def test_run_tick_reports_not_ok_when_launch_fails(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-13"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=True
        ), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=True
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            side_effect=RuntimeError("boom"),
        ):
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])

    def test_look_ahead_target_date_computes_next_day(self) -> None:
        self.assertEqual(live_refresh_loop._look_ahead_target_date("2026-07-15"), "2026-07-16")
        self.assertEqual(live_refresh_loop._look_ahead_target_date("2026-12-31"), "2027-01-01")

    def test_look_ahead_decision_skips_when_disabled(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "false"}, clear=False):
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1000.0, selected_date="2026-07-15", any_live=False)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "disabled")

    def test_look_ahead_decision_skips_when_any_live(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true"}, clear=False):
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1000.0, selected_date="2026-07-15", any_live=True)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "sport_currently_live")

    def test_look_ahead_decision_launches_when_idle_with_scheduled_games(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true"}, clear=False
        ), patch.object(live_refresh_loop, "_read_last_look_ahead_check", return_value={}), patch.object(
            live_refresh_loop, "_record_look_ahead_check"
        ) as mocked_record, patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=[{"id": "401857071"}]
        ):
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1000.0, selected_date="2026-07-15", any_live=False)

        self.assertTrue(decision["launch"])
        self.assertEqual(decision["date"], "2026-07-16")
        self.assertEqual(decision["reason"], "warm_next_day_slate")
        mocked_record.assert_called_once_with(1000.0, "2026-07-16", launched=True)

    def test_look_ahead_decision_skips_when_no_games_scheduled(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true"}, clear=False
        ), patch.object(live_refresh_loop, "_read_last_look_ahead_check", return_value={}), patch.object(
            live_refresh_loop, "_record_look_ahead_check"
        ) as mocked_record, patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=[]
        ):
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1000.0, selected_date="2026-07-15", any_live=False)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "no_games_scheduled")
        mocked_record.assert_called_once_with(1000.0, "2026-07-16", launched=False)

    def test_look_ahead_decision_skips_within_check_interval(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true", "SYNDICATE_LOOK_AHEAD_INTERVAL_SECONDS": "3600"}, clear=False
        ), patch.object(
            live_refresh_loop,
            "_read_last_look_ahead_check",
            return_value={"epoch": 1000.0, "date": "2026-07-16", "launched": True},
        ), patch.object(live_refresh_loop, "fetch_schedule_for_date") as mocked_fetch:
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1500.0, selected_date="2026-07-15", any_live=False)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "within_check_interval")
        mocked_fetch.assert_not_called()

    def test_launch_look_ahead_refresh_calls_launch_refresh_run_with_pregame_phase(self) -> None:
        with patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            result = live_refresh_loop._launch_look_ahead_refresh({"date": "2026-07-16", "reason": "warm_next_day_slate"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["launched"])
        mocked_launch.assert_called_once_with(
            date="2026-07-16",
            sports=None,
            phase="pregame",
            regions="us",
            mode="fast",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
            force_refresh=False,
        )

    def test_launch_look_ahead_refresh_skips_gracefully_on_active_refresh_guard(self) -> None:
        with patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            side_effect=ValueError("A refresh run is already active"),
        ):
            result = live_refresh_loop._launch_look_ahead_refresh({"date": "2026-07-16", "reason": "warm_next_day_slate"})

        self.assertFalse(result["ok"])
        self.assertFalse(result["launched"])
        self.assertTrue(result["skipped"])

    def test_run_tick_launches_look_ahead_refresh_when_enabled_idle_and_games_scheduled(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true", "SYNDICATE_LOOK_AHEAD_ENABLED": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-15"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=False
        ), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_read_last_pregame_launch", return_value={}
        ), patch.object(
            live_refresh_loop, "_record_pregame_launch"
        ), patch.object(
            live_refresh_loop, "_read_last_look_ahead_check", return_value={}
        ), patch.object(
            live_refresh_loop, "_record_look_ahead_check"
        ), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=[{"id": "401857071"}]
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["lookAhead"]["ok"])
        self.assertTrue(payload["lookAhead"]["launched"])
        self.assertEqual(payload["lookAhead"]["date"], "2026-07-16")
        # Today's own tick call plus the look-ahead call for tomorrow.
        self.assertEqual(mocked_launch.call_count, 2)
        mocked_launch.assert_any_call(
            date="2026-07-16",
            sports=None,
            phase="pregame",
            regions="us",
            mode="fast",
            execution_mode="source",
            launch_mode="detached_subprocess",
            skip_mirror=True,
            mirror_only=False,
            dry_run=False,
            force_refresh=False,
        )

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

    def test_create_app_starts_shared_live_refresh_loop_on_render_web(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "RENDER_SERVICE_ID": "svc-test",
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
            },
            clear=False,
        ), patch("syndicate.app.start_live_refresh_background_loop") as mocked_start, patch(
            "syndicate.app.Flask.before_request", side_effect=lambda func: func()
        ):
            create_app()

        mocked_start.assert_called_once()

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

    def test_run_live_odds_refresh_worker_starts_live_lens_loop(self) -> None:
        with patch.object(run_live_odds_refresh_worker, "_acquire_process_lock", return_value=True), patch.object(
            run_live_odds_refresh_worker,
            "_start_live_lens_reports",
            return_value=None,
        ) as mocked_start_reports, patch.object(run_live_odds_refresh_worker, "_run_tick", return_value=None), patch.object(
            run_live_odds_refresh_worker,
            "_live_refresh_loop_interval_seconds",
            return_value=5,
        ), patch.object(run_live_odds_refresh_worker.time, "sleep", return_value=None), patch.object(
            run_live_odds_refresh_worker.signal,
            "signal",
            side_effect=ValueError("skip signals"),
        ), patch.object(run_live_odds_refresh_worker.sys, "argv", ["run_live_odds_refresh_worker.py"]), patch.object(
            run_live_odds_refresh_worker._LIVE_REFRESH_LOOP_STOP,
            "is_set",
            side_effect=[False, True],
        ):
            exit_code = run_live_odds_refresh_worker.main()

        self.assertEqual(exit_code, 0)
        mocked_start_reports.assert_called_once()

    def test_run_live_odds_refresh_worker_sleeps_for_adaptive_idle_interval(self) -> None:
        # A fixed 60s sleep regardless of tick phase meant every pregame tick
        # relaunched the full predict-date + SmartSim pipeline before the
        # previous cold-start attempt (20-30+ minutes) could finish -- each
        # attempt got cut off ~60-70s in as the next tick's launch collided
        # with it, so a cold WNBA/MLB slate could never complete. The loop
        # must use the adaptive interval (900s idle/pregame) computed from
        # the tick's own result, not the fixed base interval.
        pregame_meta = {"phase": "pregame", "adaptive": True, "anyLive": False}
        with patch.object(run_live_odds_refresh_worker, "_acquire_process_lock", return_value=True), patch.object(
            run_live_odds_refresh_worker,
            "_start_live_lens_reports",
            return_value=None,
        ), patch.object(run_live_odds_refresh_worker, "_run_tick", return_value=pregame_meta), patch.object(
            run_live_odds_refresh_worker,
            "_live_refresh_loop_interval_seconds",
            return_value=60,
        ), patch.object(run_live_odds_refresh_worker.time, "sleep", return_value=None) as mocked_sleep, patch.object(
            run_live_odds_refresh_worker.signal,
            "signal",
            side_effect=ValueError("skip signals"),
        ), patch.object(run_live_odds_refresh_worker.sys, "argv", ["run_live_odds_refresh_worker.py"]), patch.object(
            run_live_odds_refresh_worker._LIVE_REFRESH_LOOP_STOP,
            "is_set",
            side_effect=[False, True],
        ):
            exit_code = run_live_odds_refresh_worker.main()

        self.assertEqual(exit_code, 0)
        mocked_sleep.assert_called_once_with(900)

    def test_run_live_odds_refresh_worker_recycles_after_max_uptime(self) -> None:
        # A long-lived worker doing routine multi-sport file I/O every tick
        # accumulates page cache over hours of uptime with no single call to
        # blame (see docs/fix_notes_log.md); it should exit cleanly on its own
        # once max uptime is reached so Render restarts it fresh, rather than
        # relying only on _LIVE_REFRESH_LOOP_STOP ever being set.
        with patch.object(run_live_odds_refresh_worker, "_acquire_process_lock", return_value=True), patch.object(
            run_live_odds_refresh_worker,
            "_start_live_lens_reports",
            return_value=None,
        ), patch.object(run_live_odds_refresh_worker, "_run_tick", return_value=None) as mocked_tick, patch.object(
            run_live_odds_refresh_worker,
            "_live_refresh_loop_interval_seconds",
            return_value=5,
        ), patch.object(run_live_odds_refresh_worker, "_max_uptime_seconds", return_value=0.0), patch.object(
            run_live_odds_refresh_worker.time, "sleep", return_value=None
        ), patch.object(
            run_live_odds_refresh_worker.signal,
            "signal",
            side_effect=ValueError("skip signals"),
        ), patch.object(run_live_odds_refresh_worker.sys, "argv", ["run_live_odds_refresh_worker.py"]), patch.object(
            run_live_odds_refresh_worker._LIVE_REFRESH_LOOP_STOP,
            "is_set",
            return_value=False,
        ) as mocked_is_set, patch.object(run_live_odds_refresh_worker, "_release_process_lock") as mocked_release:
            exit_code = run_live_odds_refresh_worker.main()

        self.assertEqual(exit_code, 0)
        mocked_tick.assert_called_once()
        mocked_release.assert_called_once()
        # Only one is_set() check (the while-loop guard) should have run before
        # the uptime recycle broke out -- proving the stop event was never
        # what ended the loop.
        self.assertEqual(mocked_is_set.call_count, 1)


if __name__ == "__main__":
    unittest.main()
