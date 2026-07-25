from __future__ import annotations

import csv
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from syndicate.app import create_app
from syndicate.features.shared import live_refresh_loop
from scripts import run_live_odds_refresh_worker


class LiveRefreshLoopTests(unittest.TestCase):
    def tearDown(self) -> None:
        live_refresh_loop._LIVE_REFRESH_LOOP_STOP.set()
        live_refresh_loop._LIVE_REFRESH_LOOP_THREAD = None
        live_refresh_loop._release_process_lock()
        live_refresh_loop._LAST_LINEUP_INJURY_CHANGED_SPORTS = set()
        live_refresh_loop._LAST_WNBA_LINEUP_INJURY_CHANGED_MATCHUPS = None
        live_refresh_loop._MLB_SIM_PROCESS = None
        live_refresh_loop._MLB_SIM_RUN_META = None
        live_refresh_loop._MLB_SIM_LOG_HANDLE = None
        live_refresh_loop._MLB_SIM_LOG_PATH = None

    def test_mlb_sim_still_running_true_when_recent_and_polling_none(self) -> None:
        # A live, recently-launched sim subprocess should still report
        # "running" -- confirms the new staleness ceiling doesn't fire early.
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        live_refresh_loop._MLB_SIM_PROCESS = fake_process
        live_refresh_loop._MLB_SIM_RUN_META = {
            "date": "2026-07-25",
            "run_stamp": "20260724_170613",
            "pid": 156,
            "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        self.assertTrue(live_refresh_loop._mlb_daily_sim_process_still_running())
        fake_process.kill.assert_not_called()
        self.assertIs(live_refresh_loop._MLB_SIM_PROCESS, fake_process)

    def test_mlb_sim_still_running_false_when_hung_past_max_runtime(self) -> None:
        # Reproduces the production incident: a worker-launched sim subprocess
        # whose .poll() never stops returning None (hung, not exited) used to
        # block every future daily-sim tick forever via the fast path, which
        # -- unlike _shared_mlb_sim_still_running's cross-container fallback --
        # had no _MLB_SIM_MAX_RUNTIME_SECONDS ceiling. This confirms the new
        # ceiling now applies to that same-process fast path too.
        fake_process = MagicMock()
        fake_process.poll.return_value = None  # never exits on its own
        live_refresh_loop._MLB_SIM_PROCESS = fake_process
        stale_started_at = datetime.now(timezone.utc) - timedelta(
            seconds=live_refresh_loop._MLB_SIM_MAX_RUNTIME_SECONDS + 60
        )
        live_refresh_loop._MLB_SIM_RUN_META = {
            "date": "2026-07-25",
            "run_stamp": "20260724_170613",
            "pid": 156,
            "started_at": stale_started_at.isoformat().replace("+00:00", "Z"),
        }

        with patch.object(live_refresh_loop, "_persist_finished_mlb_sim_run") as mocked_persist:
            still_running = live_refresh_loop._mlb_daily_sim_process_still_running()

        self.assertFalse(still_running)
        fake_process.kill.assert_called_once()
        mocked_persist.assert_called_once_with(state="timed_out")
        self.assertIsNone(live_refresh_loop._MLB_SIM_PROCESS)

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
            force_refresh_sports=None,
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
            force_refresh_sports=None,
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
            force_refresh_sports=None,
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
            force_refresh_sports=None,
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
        #
        # 2026-07-19: the mutex now only fully defers when WNBA is the ONLY
        # configured sport (nothing left to launch once it's excluded) --
        # see test_run_tick_launches_non_wnba_sports_when_mlb_sim_blocks_wnba
        # for the (now much more common) case where other sports proceed
        # anyway.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "wnba",
            },
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

    def test_run_tick_launches_non_wnba_sports_when_mlb_sim_blocks_wnba(self) -> None:
        # The actual measured OOM risk (WNBA's refresh leg spiking ~1.3-1.5GB
        # RSS) is specific to WNBA, not to refreshing MLB/other sports
        # alongside a resident MLB sim. On a live 16-game MLB slate, some sim
        # can stay resident almost continuously (staggered tip-offs), which
        # previously starved EVERY sport's odds refresh for hours even though
        # only WNBA's leg posed the actual risk. When the mutex would
        # otherwise block the whole tick, everything except WNBA should still
        # launch.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "mlb,wnba",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-19"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        self.assertNotIn("skipped", payload)
        mocked_launch.assert_called_once()
        self.assertEqual(mocked_launch.call_args.kwargs["sports"], "mlb")
        self.assertEqual(payload["oddsRefreshWnbaSkipped"]["reason"], "mlb_daily_sim_still_running")
        self.assertFalse(payload["oddsRefreshWnbaSkipped"]["forcedThrough"])

    def test_run_tick_still_skips_wnba_when_wnba_starvation_override_disabled(self) -> None:
        # 2026-07-19 fix landed WNBA-only exclusion (previous test) but its
        # only escape hatch (_odds_refresh_starved) tracks a GLOBAL
        # last-launch timestamp that keeps getting refreshed by the
        # non-WNBA sports launching successfully -- so it could never detect
        # "WNBA specifically has been skipped for hours," even if enabled.
        # _wnba_odds_refresh_starved is the WNBA-specific equivalent, and
        # it's off by default just like the general override -- being
        # "starved" per that check alone must not force WNBA through.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "mlb,wnba",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-19"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop, "_wnba_odds_refresh_skip_seconds", return_value=99999.0
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertEqual(mocked_launch.call_args.kwargs["sports"], "mlb")
        self.assertFalse(payload["oddsRefreshWnbaSkipped"]["forcedThrough"])

    def test_mlb_refresh_tick_owner_here_defaults_true(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(live_refresh_loop._mlb_refresh_tick_owner_here())

    def test_mlb_refresh_tick_owner_here_respects_env_override(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_MLB_REFRESH_TICK_OWNER": "false"}, clear=False):
            self.assertFalse(live_refresh_loop._mlb_refresh_tick_owner_here())

    def test_run_tick_excludes_mlb_when_not_owner(self) -> None:
        # live-odds-worker's tick and refresh-worker's own MLB autorun
        # (_launch_autorun_mlb_refresh) were both independently deciding "MLB
        # needs a refresh" in the same window. The cross-service lock now
        # makes that collision safe, but ownership removes the redundant
        # decision at the source: with no explicit sports override and
        # ownership set false, mlb must be excluded from what this tick
        # launches even though it's part of the season-active set.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_MLB_REFRESH_TICK_OWNER": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-21"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(
            live_refresh_loop, "_active_sports_for_date", return_value="mlb,nba,wnba"
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertEqual(mocked_launch.call_args.kwargs["sports"], "nba,wnba")

    def test_run_tick_includes_mlb_by_default(self) -> None:
        # Regression: with no ownership override configured, behavior is
        # unchanged -- no explicit sports list is built, and
        # launch_refresh_run resolves the full active-season set itself.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-21"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertIsNone(mocked_launch.call_args.kwargs["sports"])

    def test_run_tick_still_excludes_mlb_when_sim_blocks_refresh_and_not_owner(self) -> None:
        # The sim-blocked branch resolves its own sports_to_launch list
        # independently of the normal-path branch above -- ownership must be
        # respected there too, not just in the unblocked case.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "mlb,nba",
                "SYNDICATE_MLB_REFRESH_TICK_OWNER": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-21"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertEqual(mocked_launch.call_args.kwargs["sports"], "nba")

    def test_run_tick_forces_wnba_through_past_wnba_starvation_ceiling_when_override_enabled(self) -> None:
        # The opt-in path: once explicitly enabled (a human with visibility
        # into current container memory deciding the trade-off is worth it),
        # WNBA specifically gets forced through after being skipped past its
        # own ceiling -- despite the sim still blocking everything else.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "mlb,wnba",
                "SYNDICATE_WNBA_ODDS_REFRESH_STARVATION_OVERRIDE_ENABLED": "true",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-19"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop, "_wnba_odds_refresh_skip_seconds", return_value=99999.0
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        launched_sports = set((mocked_launch.call_args.kwargs["sports"] or "").split(","))
        self.assertEqual(launched_sports, {"mlb", "wnba"})
        self.assertTrue(payload["oddsRefreshWnbaSkipped"]["forcedThrough"])

    def test_wnba_odds_refresh_skip_seconds_measures_gap_since_last_wnba_launch(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.object(
            live_refresh_loop, "_meta_dir", return_value=Path(tmp_dir)
        ):
            # No prior record -- nothing to measure a gap against yet, but
            # this seeds the record so the ceiling has a real anchor.
            self.assertIsNone(live_refresh_loop._wnba_odds_refresh_skip_seconds(now_epoch=1000.0))
            skip_seconds = live_refresh_loop._wnba_odds_refresh_skip_seconds(now_epoch=1000.0 + 1800.0)
            self.assertEqual(skip_seconds, 1800.0)

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
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "wnba",
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

    # -- Memory-headroom-aware odds-refresh/sim overlap ----------------------
    # Replaces guessing (elapsed time, trigger type) with a real measurement:
    # a --only-game-pks-scoped sim CAN have a much smaller footprint than the
    # old whole-slate sim, but not always (a profile with no same-day
    # baseline silently falls back to simulating everything), so only actual
    # measured cgroup headroom can prove it's safe to overlap.

    def test_odds_refresh_memory_headroom_snapshot_none_when_overlap_disabled(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_OVERLAP_ENABLED": "false"}, clear=False):
            snapshot = live_refresh_loop._odds_refresh_memory_headroom_snapshot()
        self.assertIsNone(snapshot)

    def test_odds_refresh_memory_headroom_snapshot_none_when_unmeasurable(self) -> None:
        with patch(
            "syndicate.features.shared.memory_observability._read_container_memory_current_bytes",
            return_value=None,
        ), patch(
            "syndicate.features.shared.memory_observability._read_container_memory_max_bytes",
            return_value=2048 * 1024 * 1024,
        ):
            snapshot = live_refresh_loop._odds_refresh_memory_headroom_snapshot()
        self.assertIsNone(snapshot)

    def test_odds_refresh_memory_headroom_snapshot_reports_insufficient_and_sufficient(self) -> None:
        max_bytes = 2048 * 1024 * 1024
        with patch.dict(os.environ, {"SYNDICATE_LIVE_ODDS_REFRESH_MIN_HEADROOM_MB": "1800"}, clear=False), patch(
            "syndicate.features.shared.memory_observability._read_container_memory_current_bytes",
            return_value=int(1900 * 1024 * 1024),
        ), patch(
            "syndicate.features.shared.memory_observability._read_container_memory_max_bytes",
            return_value=max_bytes,
        ):
            tight = live_refresh_loop._odds_refresh_memory_headroom_snapshot()
        self.assertIsNotNone(tight)
        self.assertFalse(tight["sufficient"])

        with patch.dict(os.environ, {"SYNDICATE_LIVE_ODDS_REFRESH_MIN_HEADROOM_MB": "1800"}, clear=False), patch(
            "syndicate.features.shared.memory_observability._read_container_memory_current_bytes",
            return_value=int(100 * 1024 * 1024),
        ), patch(
            "syndicate.features.shared.memory_observability._read_container_memory_max_bytes",
            return_value=max_bytes,
        ):
            roomy = live_refresh_loop._odds_refresh_memory_headroom_snapshot()
        self.assertIsNotNone(roomy)
        self.assertTrue(roomy["sufficient"])

    def test_run_tick_proceeds_despite_active_sim_when_memory_headroom_sufficient(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true", "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-19"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop,
            "_odds_refresh_memory_headroom_snapshot",
            return_value={"current_mb": 100.0, "max_mb": 2048.0, "headroom_mb": 1948.0, "min_required_mb": 1800.0, "sufficient": True},
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertEqual(payload["oddsRefreshMemoryHeadroom"]["sufficient"], True)

    def test_run_tick_still_defers_despite_active_sim_when_memory_headroom_insufficient(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS": "wnba",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-19"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=True
        ), patch.object(
            live_refresh_loop,
            "_odds_refresh_memory_headroom_snapshot",
            return_value={"current_mb": 1900.0, "max_mb": 2048.0, "headroom_mb": 148.0, "min_required_mb": 1800.0, "sufficient": False},
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])
        mocked_launch.assert_not_called()
        self.assertEqual(payload["oddsRefreshMemoryHeadroom"]["sufficient"], False)

    # -- Per-game MLB sim scoping --------------------------------------------
    # Root fix for the sim-chaining problem above: a lineup/odds/pitcher
    # fingerprint change or a tip-off window used to resim the WHOLE day's
    # slate. These fingerprint/decision/launch functions now scope to just
    # the game(s) actually impacted.

    def test_mlb_sim_input_fingerprint_by_game_isolates_changed_game(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            daily_dir = data_root / "mlb_source" / "source_artifacts" / "data" / "daily"
            daily_dir.mkdir(parents=True, exist_ok=True)
            lineups_path = daily_dir / "lineups_last_known_by_team.json"
            lineups_path.write_text(json.dumps({"144": {"ids": [1, 2, 3]}, "116": {"ids": [4, 5, 6]}}), encoding="utf-8")

            events = [
                live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="Atlanta Braves", away="Detroit Tigers", start_time_utc=None, home_team_id=144, away_team_id=116),
                live_refresh_loop.ScheduleEvent(sport="mlb", event_id="200", home="Boston Red Sox", away="New York Yankees", start_time_utc=None, home_team_id=111, away_team_id=147),
            ]

            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                before = live_refresh_loop._mlb_sim_input_fingerprint_by_game("2026-07-19", events)

            # Only team 144's (game 100's home team) lineup changes.
            lineups_path.write_text(json.dumps({"144": {"ids": [1, 2, 999]}, "116": {"ids": [4, 5, 6]}}), encoding="utf-8")
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                after = live_refresh_loop._mlb_sim_input_fingerprint_by_game("2026-07-19", events)

        self.assertNotEqual(before["100"], after["100"])
        self.assertEqual(before["200"], after["200"])

    def test_mlb_sim_input_fingerprint_by_game_degrades_without_team_ids(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            events = [live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="Atlanta Braves", away="Detroit Tigers", start_time_utc=None)]
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                fingerprints = live_refresh_loop._mlb_sim_input_fingerprint_by_game("2026-07-19", events)

        self.assertIn("100", fingerprints)

    def test_mlb_daily_sim_decision_fingerprint_change_isolates_one_game(self) -> None:
        events = [
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="200", home="C", away="D", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="300", home="E", away="F", start_time_utc=None),
        ]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=[]
        ), patch.object(
            live_refresh_loop, "_read_last_mlb_sim_check", return_value={"epoch": 1000.0, "date": "2026-07-19", "fingerprints": {"100": "aaa", "200": "bbb", "300": "ccc"}}
        ), patch.object(
            live_refresh_loop, "_mlb_sim_input_fingerprint_by_game", return_value={"100": "aaa", "200": "CHANGED", "300": "ccc"}
        ), patch.object(
            live_refresh_loop, "_mlb_join_mismatch_game_pks", return_value=[]
        ), patch.object(
            live_refresh_loop, "_record_mlb_sim_check"
        ) as mocked_record:
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertEqual(decision["reason"], "fingerprint_change")
        self.assertEqual(decision["game_pks"], ["200"])
        mocked_record.assert_called_once_with(2000.0, "2026-07-19", {"100": "aaa", "200": "CHANGED", "300": "ccc"}, launched=True)

    def test_mlb_daily_sim_decision_falls_back_to_full_slate_on_first_ever_check(self) -> None:
        events = [
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="200", home="C", away="D", start_time_utc=None),
        ]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=[]
        ), patch.object(
            live_refresh_loop, "_read_last_mlb_sim_check", return_value={}
        ), patch.object(
            live_refresh_loop, "_mlb_sim_input_fingerprint_by_game", return_value={"100": "aaa", "200": "bbb"}
        ), patch.object(
            live_refresh_loop, "_mlb_join_mismatch_game_pks", return_value=[]
        ), patch.object(live_refresh_loop, "_record_mlb_sim_check"):
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertEqual(decision["reason"], "fingerprint_change")
        self.assertEqual(decision["game_pks"], ["100", "200"])

    def test_mlb_daily_sim_decision_falls_back_to_full_slate_on_old_schema_record(self) -> None:
        # Pre-migration records stored a singular "fingerprint" string, not
        # "fingerprints". Reading .get("fingerprints") on that shape returns
        # None -- must not crash, and must resim the whole slate this once.
        events = [live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None)]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=[]
        ), patch.object(
            live_refresh_loop, "_read_last_mlb_sim_check", return_value={"epoch": 1000.0, "date": "2026-07-19", "fingerprint": "old-style-string"}
        ), patch.object(
            live_refresh_loop, "_mlb_sim_input_fingerprint_by_game", return_value={"100": "aaa"}
        ), patch.object(
            live_refresh_loop, "_mlb_join_mismatch_game_pks", return_value=[]
        ), patch.object(live_refresh_loop, "_record_mlb_sim_check"):
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertEqual(decision["reason"], "fingerprint_change")
        self.assertEqual(decision["game_pks"], ["100"])

    def test_mlb_daily_sim_decision_join_mismatch_forces_resim_without_fingerprint_change(self) -> None:
        # Phase 4 of the Layer 1 plan: the market board's odds<->sim join
        # can detect a needs-resim mismatch (e.g. a probable-pitcher swap)
        # even when the lineups/odds/overrides fingerprint hash hasn't
        # changed -- this must still force a resim for that game.
        events = [
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="200", home="C", away="D", start_time_utc=None),
        ]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=[]
        ), patch.object(
            live_refresh_loop, "_read_last_mlb_sim_check", return_value={"epoch": 1000.0, "date": "2026-07-19", "fingerprints": {"100": "aaa", "200": "bbb"}}
        ), patch.object(
            live_refresh_loop, "_mlb_sim_input_fingerprint_by_game", return_value={"100": "aaa", "200": "bbb"}
        ), patch.object(
            live_refresh_loop, "_mlb_join_mismatch_game_pks", return_value=["200"]
        ), patch.object(
            live_refresh_loop, "_record_mlb_sim_check"
        ) as mocked_record:
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertTrue(decision["force"])
        self.assertEqual(decision["reason"], "join_mismatch_needs_resim")
        self.assertEqual(decision["game_pks"], ["200"])
        self.assertEqual(decision["join_mismatch_game_pks"], ["200"])
        mocked_record.assert_called_once_with(2000.0, "2026-07-19", {"100": "aaa", "200": "bbb"}, launched=True)

    def test_mlb_daily_sim_decision_merges_fingerprint_and_join_mismatch_game_pks(self) -> None:
        events = [
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="200", home="C", away="D", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="300", home="E", away="F", start_time_utc=None),
        ]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=[]
        ), patch.object(
            live_refresh_loop, "_read_last_mlb_sim_check", return_value={"epoch": 1000.0, "date": "2026-07-19", "fingerprints": {"100": "aaa", "200": "bbb", "300": "ccc"}}
        ), patch.object(
            live_refresh_loop, "_mlb_sim_input_fingerprint_by_game", return_value={"100": "aaa", "200": "CHANGED", "300": "ccc"}
        ), patch.object(
            live_refresh_loop, "_mlb_join_mismatch_game_pks", return_value=["300"]
        ), patch.object(live_refresh_loop, "_record_mlb_sim_check"):
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertEqual(decision["reason"], "fingerprint_change")
        self.assertEqual(decision["game_pks"], ["200", "300"])
        self.assertEqual(decision["join_mismatch_game_pks"], ["300"])

    def test_mlb_daily_sim_decision_no_change_when_neither_fingerprint_nor_join_mismatch(self) -> None:
        events = [live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None)]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=[]
        ), patch.object(
            live_refresh_loop, "_read_last_mlb_sim_check", return_value={"epoch": 1000.0, "date": "2026-07-19", "fingerprints": {"100": "aaa"}}
        ), patch.object(
            live_refresh_loop, "_mlb_sim_input_fingerprint_by_game", return_value={"100": "aaa"}
        ), patch.object(
            live_refresh_loop, "_mlb_join_mismatch_game_pks", return_value=[]
        ), patch.object(
            live_refresh_loop, "_record_mlb_sim_check"
        ) as mocked_record:
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertFalse(decision["force"])
        self.assertEqual(decision["reason"], "no_change")
        mocked_record.assert_called_once_with(2000.0, "2026-07-19", {"100": "aaa"}, launched=False)

    def test_mlb_join_mismatch_game_pks_swallows_exceptions(self) -> None:
        # Defensive: this is an additive enhancement on top of the
        # already-working fingerprint trigger -- any failure inside it
        # (missing artifact, bad data shape, etc.) must never propagate and
        # break the existing mechanism.
        with patch("syndicate.features.mlb.cards.mlb_needs_resim_game_pks", side_effect=RuntimeError("boom")):
            result = live_refresh_loop._mlb_join_mismatch_game_pks("2026-07-19")
        self.assertEqual(result, [])

    def test_mlb_daily_sim_decision_tip_off_window_returns_only_starting_soon_game_pks(self) -> None:
        all_events = [
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="mlb", event_id="200", home="C", away="D", start_time_utc=None),
        ]
        starting_soon = [all_events[1]]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=all_events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "events_starting_within", return_value=starting_soon
        ):
            mocked_summary_path.return_value.exists.return_value = True
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertEqual(decision["reason"], "tip_off_window")
        self.assertEqual(decision["game_pks"], ["200"])

    def test_mlb_daily_sim_decision_first_appearance_has_no_game_pks(self) -> None:
        events = [live_refresh_loop.ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None)]
        with patch.dict(os.environ, {"SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER": "true"}, clear=False), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(live_refresh_loop, "is_refresh_run_active", return_value=False), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=events
        ), patch.object(
            live_refresh_loop, "_mlb_daily_summary_path"
        ) as mocked_summary_path, patch.object(
            live_refresh_loop, "_mlb_recent_sim_attempt_within_backoff", return_value=False
        ):
            mocked_summary_path.return_value.exists.return_value = False
            decision = live_refresh_loop._mlb_daily_sim_decision(now_epoch=2000.0, date_str="2026-07-19")

        self.assertEqual(decision["reason"], "first_appearance")
        self.assertNotIn("game_pks", decision)

    def test_launch_mlb_daily_sim_includes_only_game_pks_flag_when_scoped(self) -> None:
        with patch.object(live_refresh_loop.subprocess, "Popen") as mocked_popen:
            mocked_popen.return_value.pid = 4242
            live_refresh_loop._launch_mlb_daily_sim("2026-07-19", {"reason": "fingerprint_change", "game_pks": ["200", "100"]})

        command = mocked_popen.call_args[0][0]
        self.assertIn("--only-game-pks", command)
        self.assertEqual(command[command.index("--only-game-pks") + 1], "100,200")

    def test_launch_mlb_daily_sim_omits_only_game_pks_flag_for_first_appearance(self) -> None:
        with patch.object(live_refresh_loop.subprocess, "Popen") as mocked_popen:
            mocked_popen.return_value.pid = 4242
            live_refresh_loop._launch_mlb_daily_sim("2026-07-19", {"reason": "first_appearance"})

        command = mocked_popen.call_args[0][0]
        self.assertNotIn("--only-game-pks", command)

    def test_launch_mlb_daily_sim_omits_only_game_pks_flag_for_evening_next_day(self) -> None:
        with patch.object(live_refresh_loop.subprocess, "Popen") as mocked_popen:
            mocked_popen.return_value.pid = 4242
            live_refresh_loop._launch_mlb_daily_sim("2026-07-20", {"reason": "evening_next_day_sim", "date": "2026-07-20"})

        command = mocked_popen.call_args[0][0]
        self.assertNotIn("--only-game-pks", command)

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
            force_refresh_sports=None,
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

    def test_should_force_sim_rerun_tracks_only_the_sport_that_actually_changed(self) -> None:
        # An NBA-only fingerprint change must not also mark WNBA as changed --
        # this is what let one sport's injury news force the OTHER sport's
        # refresh script to bypass its cache too.
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
        ):
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 1800, date_str="2026-07-13")

        self.assertTrue(result)
        self.assertEqual(live_refresh_loop._last_lineup_injury_changed_sports(), {"wnba"})

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

    def test_should_force_sim_rerun_records_change_epoch_for_genuinely_changed_sport(self) -> None:
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
        ), patch.object(
            live_refresh_loop, "_record_lineup_injury_change_epochs"
        ) as mocked_record_change:
            live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 1800, date_str="2026-07-13")

        mocked_record_change.assert_called_once_with({"wnba"}, now_epoch=1000.0 + 1800)

    def test_should_force_sim_rerun_does_not_record_change_epoch_on_new_date(self) -> None:
        # A pure date rollover marks every sport "changed" so the resim gets
        # forced, but that isn't a real injury/lineup news event -- it must
        # not feed the board-callout signal, or every sport would get
        # falsely tagged "news-driven" once per day regardless of whether
        # anything actually happened.
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
        ), patch.object(
            live_refresh_loop, "_record_lineup_injury_change_epochs"
        ) as mocked_record_change:
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=1000.0 + 60, date_str="2026-07-13")

        self.assertTrue(result)
        mocked_record_change.assert_not_called()

    def test_lineup_injury_change_epochs_round_trip_and_merge(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.object(live_refresh_loop, "_meta_dir", return_value=Path(tmp_dir)):
            self.assertEqual(live_refresh_loop._read_lineup_injury_change_epochs(), {})
            live_refresh_loop._record_lineup_injury_change_epochs({"wnba"}, now_epoch=1000.0)
            self.assertEqual(live_refresh_loop._read_lineup_injury_change_epochs(), {"wnba": 1000.0})
            # A later call for a different sport must merge, not clobber, the
            # earlier sport's recorded epoch.
            live_refresh_loop._record_lineup_injury_change_epochs({"nba"}, now_epoch=2000.0)
            self.assertEqual(live_refresh_loop._read_lineup_injury_change_epochs(), {"wnba": 1000.0, "nba": 2000.0})

    def test_record_lineup_injury_change_epochs_is_noop_for_empty_set(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.object(live_refresh_loop, "_meta_dir", return_value=Path(tmp_dir)):
            live_refresh_loop._record_lineup_injury_change_epochs(set(), now_epoch=1000.0)
            self.assertEqual(live_refresh_loop._read_lineup_injury_change_epochs(), {})

    def test_sports_with_recent_lineup_injury_change_respects_window(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.object(live_refresh_loop, "_meta_dir", return_value=Path(tmp_dir)):
            live_refresh_loop._record_lineup_injury_change_epochs({"wnba"}, now_epoch=1000.0)
            live_refresh_loop._record_lineup_injury_change_epochs({"nba"}, now_epoch=1000.0 - 10000.0)

            recent = live_refresh_loop.sports_with_recent_lineup_injury_change(now_epoch=1000.0 + 100.0, within_seconds=3600)

        self.assertEqual(recent, {"wnba"})

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
            # _should_force_sim_rerun is mocked here, so the real changed-sport
            # tracking never populated -- falls back to today's original
            # "force every basketball sport" behavior, same as before this fix.
            force_refresh_sports="nba,wnba",
        )

    def test_run_tick_narrows_force_refresh_sports_to_the_sport_that_changed(self) -> None:
        # An NBA-only lineup/injury change must not also force WNBA's
        # refresh script to bypass its cache -- confirmed end-to-end through
        # the real _should_force_sim_rerun call (not mocked), which is what
        # actually populates the changed-sport tracking.
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-13"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=True
        ), patch.object(
            live_refresh_loop,
            "_read_last_lineup_check",
            return_value={"epoch": 0.0, "date": "2026-07-13", "fingerprints": {"nba": "OLD", "wnba": "SAME"}},
        ), patch.object(
            live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False
        ), patch.object(
            live_refresh_loop, "_fetch_injuries", return_value=True
        ), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="CHANGED"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="SAME"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ), patch.object(
            live_refresh_loop,
            "launch_refresh_run",
            return_value={"ok": True, "state": "running"},
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["simRerunTriggered"])
        self.assertEqual(mocked_launch.call_args.kwargs["force_refresh_sports"], "nba")

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
        ), patch.object(live_refresh_loop, "_read_last_look_ahead_check", return_value=({}, True)), patch.object(
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
        ), patch.object(live_refresh_loop, "_read_last_look_ahead_check", return_value=({}, True)), patch.object(
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
            return_value=({"epoch": 1000.0, "date": "2026-07-16", "launched": True}, True),
        ), patch.object(live_refresh_loop, "fetch_schedule_for_date") as mocked_fetch:
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1500.0, selected_date="2026-07-15", any_live=False)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "within_check_interval")
        mocked_fetch.assert_not_called()

    def test_look_ahead_decision_fails_closed_when_state_read_fails(self) -> None:
        # 2026-07-24 fix: a keyvalue-store read failure must never be
        # silently treated as "never checked before" -- that exact defeat of
        # this interval gate let 8 look-ahead relaunches fire for the same
        # target date in 5 hours, some only 6-30 minutes apart, stacking
        # overlapping refresh_odds_sources.py runs that corrupted each
        # other's writes and left that date with zero completed sim/odds
        # rows all day.
        with patch.dict(
            os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true"}, clear=False
        ), patch.object(live_refresh_loop, "_read_last_look_ahead_check", return_value=({}, False)), patch.object(
            live_refresh_loop, "fetch_schedule_for_date"
        ) as mocked_fetch:
            decision = live_refresh_loop._look_ahead_decision(now_epoch=1000.0, selected_date="2026-07-15", any_live=False)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "state_read_failed")
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

    def test_look_ahead_target_date_day2_computes_two_days_ahead(self) -> None:
        self.assertEqual(live_refresh_loop._look_ahead_target_date_day2("2026-07-15"), "2026-07-17")
        self.assertEqual(live_refresh_loop._look_ahead_target_date_day2("2026-12-30"), "2027-01-01")

    def test_look_ahead_decision_day2_launches_when_day1_has_no_games_but_day2_does(self) -> None:
        def fake_schedule(sport, date_str):
            return [] if date_str == "2026-07-16" else [{"id": "401857071"}]

        with patch.dict(
            os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true"}, clear=False
        ), patch.object(live_refresh_loop, "_read_last_look_ahead_check_day2", return_value=({}, True)), patch.object(
            live_refresh_loop, "_record_look_ahead_check_day2"
        ) as mocked_record, patch.object(
            live_refresh_loop, "fetch_schedule_for_date", side_effect=fake_schedule
        ):
            decision = live_refresh_loop._look_ahead_decision_day2(now_epoch=1000.0, selected_date="2026-07-15", any_live=False)

        self.assertTrue(decision["launch"])
        self.assertEqual(decision["date"], "2026-07-17")
        self.assertEqual(decision["reason"], "warm_day_after_next_slate")
        mocked_record.assert_called_once_with(1000.0, "2026-07-17", launched=True)

    def test_look_ahead_decision_day2_skips_when_window_disabled(self) -> None:
        with patch.dict(
            os.environ, {"SYNDICATE_LOOK_AHEAD_ENABLED": "true", "SYNDICATE_LOOK_AHEAD_48H_ENABLED": "false"}, clear=False
        ):
            decision = live_refresh_loop._look_ahead_decision_day2(now_epoch=1000.0, selected_date="2026-07-15", any_live=False)

        self.assertFalse(decision["launch"])
        self.assertEqual(decision["reason"], "disabled")

    def test_run_mlb_sim_tick_skips_day2_when_day1_launches_this_tick(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true", "SYNDICATE_LOOK_AHEAD_ENABLED": "true"},
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-07-15"), patch.object(
            live_refresh_loop, "_any_tracked_sport_game_live", return_value=False
        ), patch.object(
            live_refresh_loop, "_read_last_look_ahead_check", return_value=({}, True)
        ), patch.object(
            live_refresh_loop, "_record_look_ahead_check"
        ), patch.object(
            live_refresh_loop, "fetch_schedule_for_date", return_value=[{"id": "401857071"}]
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "state": "running"}
        ) as mocked_launch:
            meta = live_refresh_loop._run_mlb_sim_tick()

        self.assertTrue(meta["lookAhead"]["launched"])
        self.assertFalse(meta["lookAheadDay2"]["launched"])
        self.assertEqual(meta["lookAheadDay2"]["reason"], "day1_launched_this_tick")
        # Only day 1's look-ahead call -- day 2 must not also launch this tick.
        mocked_launch.assert_called_once()

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
            live_refresh_loop, "_read_last_look_ahead_check", return_value=({}, True)
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


    # -- WNBA per-matchup sim scoping (Phase 2 of the single-game sim -------
    # scoping initiative -- MLB went first via bc614d77, WNBA is the same
    # idea applied via an isolated, WNBA-only side channel so a WNBA-blind
    # code path (NBA, the ~18 existing plain-bool mocks of
    # _should_force_sim_rerun) can't be affected by it.

    def _write_wnba_injury_sources(self, data_root: Path, date_str: str, *, injuries_rows: list[dict], status_rows: list[dict]) -> None:
        raw_dir = data_root / "wnba_source" / "data" / "raw"
        processed_dir = data_root / "wnba_source" / "data" / "processed"
        raw_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)
        with (raw_dir / "injuries.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["team", "player", "status"])
            writer.writeheader()
            writer.writerows(injuries_rows)
        with (processed_dir / f"league_status_{date_str}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["team", "player_name", "playing_today"])
            writer.writeheader()
            writer.writerows(status_rows)

    def test_wnba_lineup_injury_fingerprint_by_game_isolates_changed_matchup(self) -> None:
        events = [
            live_refresh_loop.ScheduleEvent(sport="wnba", event_id="1", home="LVA", away="NYL", start_time_utc=None),
            live_refresh_loop.ScheduleEvent(sport="wnba", event_id="2", home="SEA", away="CHI", start_time_utc=None),
        ]
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            self._write_wnba_injury_sources(
                data_root,
                "2026-07-22",
                injuries_rows=[{"team": "LVA", "player": "A. Wilson", "status": "OUT"}],
                status_rows=[{"team": "SEA", "player_name": "J. Doe", "playing_today": "true"}],
            )
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False), patch.object(
                live_refresh_loop, "fetch_schedule_for_date", return_value=events
            ):
                before = live_refresh_loop._wnba_lineup_injury_fingerprint_by_game("2026-07-22")

            # Only LVA's injury row changes -- SEA-CHI's inputs are untouched.
            self._write_wnba_injury_sources(
                data_root,
                "2026-07-22",
                injuries_rows=[{"team": "LVA", "player": "A. Wilson", "status": "DOUBTFUL"}],
                status_rows=[{"team": "SEA", "player_name": "J. Doe", "playing_today": "true"}],
            )
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False), patch.object(
                live_refresh_loop, "fetch_schedule_for_date", return_value=events
            ):
                after = live_refresh_loop._wnba_lineup_injury_fingerprint_by_game("2026-07-22")

        self.assertNotEqual(before[("LVA", "NYL")], after[("LVA", "NYL")])
        self.assertEqual(before[("SEA", "CHI")], after[("SEA", "CHI")])

    def test_wnba_lineup_injury_fingerprint_by_game_degrades_gracefully_with_no_schedule(self) -> None:
        with patch.object(live_refresh_loop, "fetch_schedule_for_date", return_value=[]):
            fingerprints = live_refresh_loop._wnba_lineup_injury_fingerprint_by_game("2026-07-22")

        self.assertEqual(fingerprints, {})

    def test_wnba_lineup_injury_fingerprint_by_game_degrades_gracefully_on_fetch_error(self) -> None:
        with patch.object(live_refresh_loop, "fetch_schedule_for_date", side_effect=RuntimeError("boom")):
            fingerprints = live_refresh_loop._wnba_lineup_injury_fingerprint_by_game("2026-07-22")

        self.assertEqual(fingerprints, {})

    def test_should_force_sim_rerun_records_wnba_changed_matchups_on_fingerprint_change(self) -> None:
        with patch.object(live_refresh_loop, "_lineup_check_interval_seconds", return_value=0), patch.object(
            live_refresh_loop, "_read_last_lineup_check", return_value={"epoch": 1000.0, "date": "2026-07-22", "fingerprints": {"nba": "n1", "wnba": "w-old"}}
        ), patch.object(live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False), patch.object(
            live_refresh_loop, "_fetch_injuries", return_value=None
        ), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="n1"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="w-new"
        ), patch.object(
            live_refresh_loop,
            "_wnba_lineup_injury_fingerprint_by_game",
            return_value={("LVA", "NYL"): "changed", ("SEA", "CHI"): "same"},
        ), patch.object(
            live_refresh_loop,
            "_read_last_wnba_matchup_lineup_check",
            return_value={"date": "2026-07-22", "fingerprints": {"LVA-NYL": "old", "SEA-CHI": "same"}},
        ), patch.object(
            live_refresh_loop, "_record_wnba_matchup_lineup_check"
        ) as mocked_record_matchup, patch.object(
            live_refresh_loop, "_record_lineup_check"
        ), patch.object(
            live_refresh_loop, "_record_lineup_injury_change_epochs"
        ):
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=2000.0, date_str="2026-07-22")

        self.assertTrue(result)
        self.assertEqual(live_refresh_loop._last_wnba_lineup_injury_changed_matchups(), {("LVA", "NYL")})
        mocked_record_matchup.assert_called_once_with(2000.0, "2026-07-22", {("LVA", "NYL"): "changed", ("SEA", "CHI"): "same"})

    def test_should_force_sim_rerun_returns_none_matchups_on_first_ever_record(self) -> None:
        with patch.object(live_refresh_loop, "_lineup_check_interval_seconds", return_value=0), patch.object(
            live_refresh_loop, "_read_last_lineup_check", return_value={"epoch": 1000.0, "date": "2026-07-22", "fingerprints": {"nba": "n1", "wnba": "w-old"}}
        ), patch.object(live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False), patch.object(
            live_refresh_loop, "_fetch_injuries", return_value=None
        ), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="n1"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="w-new"
        ), patch.object(
            live_refresh_loop,
            "_wnba_lineup_injury_fingerprint_by_game",
            return_value={("LVA", "NYL"): "changed"},
        ), patch.object(
            live_refresh_loop, "_read_last_wnba_matchup_lineup_check", return_value={}
        ), patch.object(
            live_refresh_loop, "_record_wnba_matchup_lineup_check"
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ), patch.object(
            live_refresh_loop, "_record_lineup_injury_change_epochs"
        ):
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=2000.0, date_str="2026-07-22")

        self.assertTrue(result)
        self.assertIsNone(live_refresh_loop._last_wnba_lineup_injury_changed_matchups())

    def test_should_force_sim_rerun_wnba_matchup_tracking_failure_does_not_break_sport_bool(self) -> None:
        with patch.object(live_refresh_loop, "_lineup_check_interval_seconds", return_value=0), patch.object(
            live_refresh_loop, "_read_last_lineup_check", return_value={"epoch": 1000.0, "date": "2026-07-22", "fingerprints": {"nba": "n1", "wnba": "w-old"}}
        ), patch.object(live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False), patch.object(
            live_refresh_loop, "_fetch_injuries", return_value=None
        ), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="n1"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="w-new"
        ), patch.object(
            live_refresh_loop,
            "_wnba_lineup_injury_fingerprint_by_game",
            side_effect=RuntimeError("boom"),
        ), patch.object(
            live_refresh_loop, "_record_lineup_check"
        ), patch.object(
            live_refresh_loop, "_record_lineup_injury_change_epochs"
        ):
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=2000.0, date_str="2026-07-22")

        # The existing plain-bool contract (~18 tests mock this directly)
        # must survive a failure in the new WNBA-only per-matchup code.
        self.assertTrue(result)
        self.assertIsNone(live_refresh_loop._last_wnba_lineup_injury_changed_matchups())

    def test_should_force_sim_rerun_skips_wnba_matchup_tracking_when_wnba_unchanged(self) -> None:
        with patch.object(live_refresh_loop, "_lineup_check_interval_seconds", return_value=0), patch.object(
            live_refresh_loop, "_read_last_lineup_check", return_value={"epoch": 1000.0, "date": "2026-07-22", "fingerprints": {"nba": "n-old", "wnba": "w-same"}}
        ), patch.object(live_refresh_loop, "_any_gated_sport_event_within_force_window", return_value=False), patch.object(
            live_refresh_loop, "_fetch_injuries", return_value=None
        ), patch.object(
            live_refresh_loop, "_nba_lineup_injury_fingerprint", return_value="n-new"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint", return_value="w-same"
        ), patch.object(
            live_refresh_loop, "_wnba_lineup_injury_fingerprint_by_game"
        ) as mocked_by_game, patch.object(
            live_refresh_loop, "_record_lineup_check"
        ), patch.object(
            live_refresh_loop, "_record_lineup_injury_change_epochs"
        ):
            result = live_refresh_loop._should_force_sim_rerun(now_epoch=2000.0, date_str="2026-07-22")

        self.assertTrue(result)
        mocked_by_game.assert_not_called()
        self.assertIsNone(live_refresh_loop._last_wnba_lineup_injury_changed_matchups())

    def test_weekly_sports_refresh_tick_owner_here_defaults_true(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(live_refresh_loop._weekly_sports_refresh_tick_owner_here())

    def test_weekly_sports_refresh_tick_owner_here_respects_env_override(self) -> None:
        with patch.dict(os.environ, {"WEEKLY_SPORTS_REFRESH_TICK_OWNER": "false"}, clear=False):
            self.assertFalse(live_refresh_loop._weekly_sports_refresh_tick_owner_here())

    def test_run_tick_excludes_weekly_sports_when_not_owner(self) -> None:
        # Mirrors test_run_tick_excludes_mlb_when_not_owner: without this
        # ownership split, live-odds-worker's tick and refresh-worker's
        # weekly-sports autorun would both target the identical in-season
        # nfl/ncaaf/ncaab artifacts -- a real write race once those sports
        # are back in season, not just wasted duplicate work like MLB's case.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
                "WEEKLY_SPORTS_REFRESH_TICK_OWNER": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-09-21"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(
            live_refresh_loop, "_active_sports_for_date", return_value="mlb,nfl,ncaaf,ncaab"
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertEqual(mocked_launch.call_args.kwargs["sports"], "mlb")

    def test_run_tick_includes_weekly_sports_by_default(self) -> None:
        # Regression: with no ownership override configured, behavior is
        # unchanged -- no explicit sports list is built for this reason, and
        # launch_refresh_run resolves the full active-season set itself.
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP": "true",
                "SYNDICATE_LIVE_ODDS_REFRESH_ADAPTIVE": "false",
            },
            clear=False,
        ), patch.object(live_refresh_loop, "central_today_iso", return_value="2026-09-21"), patch.object(
            live_refresh_loop, "_should_force_sim_rerun", return_value=False
        ), patch.object(
            live_refresh_loop, "_mlb_daily_sim_process_still_running", return_value=False
        ), patch.object(
            live_refresh_loop, "_active_sports_for_date", return_value="mlb,nfl,ncaaf,ncaab"
        ), patch.object(
            live_refresh_loop, "launch_refresh_run", return_value={"ok": True, "pid": 4242}
        ) as mocked_launch:
            payload = live_refresh_loop._run_live_refresh_tick()

        self.assertTrue(payload["ok"])
        mocked_launch.assert_called_once()
        self.assertIsNone(mocked_launch.call_args.kwargs["sports"])


if __name__ == "__main__":
    unittest.main()


class SoccerJoinMismatchResimTriggerTests(unittest.TestCase):
    """Soccer had NO event-driven resim path of any kind: it is absent from
    _LINEUP_INJURY_FETCH_PACKAGES, and only MLB consumed the shared
    needs-resim join status. 428 MLS prop rows sat suppressed
    (is_eligible false) on 2026-07-25 with nothing able to clear them.

    This trigger reuses the existing force_refresh_sports path rather than
    adding a second subprocess launcher, because soccer's sim rebuild is
    already a step inside the odds refresh.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self._reports_root = Path(self._tmp.name)
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(self._reports_root)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: os.environ.pop("SYNDICATE_REPORTS_ROOT", None))
        for key in (
            "SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER",
            "SYNDICATE_SOCCER_RESIM_TICK_OWNER",
            "SYNDICATE_SOCCER_RESIM_CHECK_INTERVAL_SECONDS",
        ):
            os.environ.pop(key, None)
            self.addCleanup(lambda k=key: os.environ.pop(k, None))

    def _enable(self) -> None:
        os.environ["SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER"] = "true"

    def _headroom(self, sufficient: bool = True):
        return patch.object(
            live_refresh_loop, "_mlb_sim_memory_headroom_snapshot", return_value={"sufficient": sufficient}
        )

    def test_disabled_by_default_does_not_even_look(self) -> None:
        # Ships dark: this puts a market-board build on the tick path, the
        # same shape of call that OOM-killed the container on 2026-07-25.
        with patch.object(live_refresh_loop, "_mlb_sim_memory_headroom_snapshot") as headroom:
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), []
            )
            headroom.assert_not_called()

    def test_returns_leagues_with_a_needs_resim_mismatch(self) -> None:
        self._enable()
        with self._headroom(), patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls", "epl"]
        ), patch(
            "syndicate.features.soccer.market_board.soccer_needs_resim_event_ids",
            side_effect=lambda league, date_str: ["222"] if league == "mls" else [],
        ):
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), ["mls"]
            )

    def test_skips_when_memory_headroom_insufficient(self) -> None:
        self._enable()
        with self._headroom(sufficient=False), patch(
            "syndicate.features.soccer.market_board.soccer_needs_resim_event_ids"
        ) as needs_resim:
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), []
            )
            needs_resim.assert_not_called()

    def test_unmeasurable_headroom_is_treated_as_insufficient(self) -> None:
        self._enable()
        with patch.object(live_refresh_loop, "_mlb_sim_memory_headroom_snapshot", return_value=None), patch(
            "syndicate.features.soccer.market_board.soccer_needs_resim_event_ids"
        ) as needs_resim:
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), []
            )
            needs_resim.assert_not_called()

    def test_respects_check_interval_between_ticks(self) -> None:
        self._enable()
        with self._headroom(), patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch(
            "syndicate.features.soccer.market_board.soccer_needs_resim_event_ids", return_value=["222"]
        ) as needs_resim:
            first = live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25")
            self.assertEqual(first, ["mls"])
            # Well inside the 900s default -- must not rebuild boards again.
            second = live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1060.0, date_str="2026-07-25")
            self.assertEqual(second, [])
            self.assertEqual(needs_resim.call_count, 1)

    def test_rechecks_after_interval_elapses(self) -> None:
        self._enable()
        with self._headroom(), patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch("syndicate.features.soccer.market_board.soccer_needs_resim_event_ids", return_value=["222"]):
            live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25")
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0 + 901.0, date_str="2026-07-25"),
                ["mls"],
            )

    def test_not_this_services_lane_returns_empty(self) -> None:
        self._enable()
        os.environ["SYNDICATE_SOCCER_RESIM_TICK_OWNER"] = "false"
        with patch("syndicate.features.soccer.market_board.soccer_needs_resim_event_ids") as needs_resim:
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), []
            )
            needs_resim.assert_not_called()

    def test_one_bad_league_does_not_lose_the_others(self) -> None:
        self._enable()

        def _flaky(league, date_str):
            if league == "epl":
                raise RuntimeError("boom")
            return ["222"]

        with self._headroom(), patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["epl", "mls"]
        ), patch("syndicate.features.soccer.market_board.soccer_needs_resim_event_ids", side_effect=_flaky):
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), ["mls"]
            )

    def test_never_raises_into_the_tick(self) -> None:
        self._enable()
        with self._headroom(), patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", side_effect=RuntimeError("boom")
        ):
            self.assertEqual(
                live_refresh_loop._soccer_join_mismatch_leagues(now_epoch=1000.0, date_str="2026-07-25"), []
            )
