from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RefreshWorkerTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "run_refresh_worker.py"
        spec = importlib.util.spec_from_file_location("test_run_refresh_worker", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_bootstrap_soccer_player_seed_files_backfills_missing_leagues_only(self) -> None:
        # #145. Root cause confirmed live 2026-07-30: build_soccer_artifacts.py's
        # simulate_props() ran "successfully" every cycle (real match-level
        # sims present) but produced zero player projections for every
        # league, because refresh-worker's own disk never received the
        # git-committed players_{season}.csv roster seed files -- unlike web
        # (syndicate/app.py's _bootstrap_render_data), refresh-worker never
        # ran any bootstrap sync from git at all.
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            fake_data_root = Path(tmp_dir) / "data_root"
            fake_data_root.mkdir(parents=True)

            with patch.object(module, "_refresh_state_store", return_value={"data_root": lambda: fake_data_root}):
                module._bootstrap_soccer_player_seed_files()

            mls_dest = fake_data_root / "soccer_source" / "mls" / "players" / "players_2026.csv"
            self.assertTrue(mls_dest.exists())
            source_mls = repo_root / "data" / "soccer_source" / "mls" / "players" / "players_2026.csv"
            self.assertEqual(mls_dest.read_bytes(), source_mls.read_bytes())

            epl_dest = fake_data_root / "soccer_source" / "epl" / "players"
            self.assertEqual(
                sorted(p.name for p in epl_dest.glob("players_*.csv")),
                ["players_2024.csv", "players_2025.csv"],
            )

            # A league with no committed players/ dir at all (e.g.
            # championship) must not get one manufactured out of nothing.
            self.assertFalse((fake_data_root / "soccer_source" / "championship" / "players").exists())

            # Never overwrites anything already on disk -- rerunning after a
            # league already has real, freshly-generated data must be a
            # complete no-op for that league.
            mls_dest.write_text("SENTINEL-DO-NOT-OVERWRITE", encoding="utf-8")
            with patch.object(module, "_refresh_state_store", return_value={"data_root": lambda: fake_data_root}):
                module._bootstrap_soccer_player_seed_files()
            self.assertEqual(mls_dest.read_text(encoding="utf-8"), "SENTINEL-DO-NOT-OVERWRITE")

    def test_bootstrap_soccer_schedule_seed_files_backfills_missing_leagues_only(self) -> None:
        # #170 follow-up. Root-caused live 2026-08-01: a missing
        # schedule_{season}.json on refresh-worker's own disk makes
        # default_week() fall back to week 1 (always in the past), so
        # week_date_list() returns an empty date list and the entire
        # player-props pipeline silently produces zero rank cards --
        # regardless of how correct the picks/recommendations data is. Same
        # missing-bootstrap shape as #145/#146, just for schedule instead of
        # player rosters, and schedule_2026.json has no date suffix so
        # pull_hot_artifacts's per-cycle date-scoped pull can never reach it
        # either.
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            fake_data_root = Path(tmp_dir) / "data_root"
            fake_data_root.mkdir(parents=True)

            with patch.object(module, "_refresh_state_store", return_value={"data_root": lambda: fake_data_root}):
                module._bootstrap_soccer_schedule_seed_files()

            mls_dest = fake_data_root / "soccer_source" / "mls" / "api" / "schedule" / "schedule_2026.json"
            self.assertTrue(mls_dest.exists())
            source_mls = repo_root / "data" / "soccer_source" / "mls" / "api" / "schedule" / "schedule_2026.json"
            self.assertEqual(mls_dest.read_bytes(), source_mls.read_bytes())

            # Never overwrites anything already on disk.
            mls_dest.write_text("SENTINEL-DO-NOT-OVERWRITE", encoding="utf-8")
            with patch.object(module, "_refresh_state_store", return_value={"data_root": lambda: fake_data_root}):
                module._bootstrap_soccer_schedule_seed_files()
            self.assertEqual(mls_dest.read_text(encoding="utf-8"), "SENTINEL-DO-NOT-OVERWRITE")

    def test_has_pending_external_contract_requires_pending_state_and_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            latest_manifest_path.write_text(
                json.dumps({"state": "pending_external", "externalRunner": {"kind": "external_runner"}}),
                encoding="utf-8",
            )
            self.assertTrue(module._has_pending_external_contract(latest_manifest_path))

            latest_manifest_path.write_text(json.dumps({"state": "running", "externalRunner": {}}), encoding="utf-8")
            self.assertFalse(module._has_pending_external_contract(latest_manifest_path))

            latest_manifest_path.write_text(json.dumps({"state": "claimed", "externalRunner": {"kind": "external_runner"}}), encoding="utf-8")
            self.assertFalse(module._has_pending_external_contract(latest_manifest_path))

            latest_manifest_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "externalRunner": {"kind": "external_runner", "queue_state": "queued", "runStamp": "20260522_120000", "command": ["python"]},
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(module._has_pending_external_contract(latest_manifest_path))

    def test_main_run_once_executes_runner_when_pending(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            latest_manifest_path.write_text(
                json.dumps({"state": "pending_external", "externalRunner": {"kind": "external_runner"}}),
                encoding="utf-8",
            )

            fake_process = unittest.mock.MagicMock()
            fake_process.pid = 4321
            fake_process.poll.return_value = 0

            with patch.object(
                sys,
                "argv",
                ["run_refresh_worker.py", "--latest-manifest", str(latest_manifest_path), "--run-once"],
            ), patch.object(
                module.subprocess,
                "Popen",
                return_value=fake_process,
            ) as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_popen.assert_called_once()
            called_command = mocked_popen.call_args.args[0]
            self.assertIn(str(repo_root / "scripts" / "run_queued_refresh_job.py"), called_command)
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest_payload["state"], "claimed")

    def test_main_starts_intelligence_state_background_loop(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            # main() only calls start_intelligence_state_background_loop when
            # SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP is set --
            # refresh-worker is the one service that owns this loop in
            # production (see render.yaml), but nothing in the test
            # environment sets it, so without this the call this test
            # asserts on never happens.
            with patch.dict(os.environ, {"SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP": "true"}), patch.object(
                sys,
                "argv",
                ["run_refresh_worker.py", "--latest-manifest", str(latest_manifest_path), "--run-once"],
            ), patch.object(module, "start_intelligence_state_background_loop") as mocked_start_loop:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_start_loop.assert_called_once()

    def test_main_run_once_skips_runner_when_nothing_is_pending(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            with patch.dict(module.os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=True), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"),
                    "--run-once",
                ],
            ), patch.object(module.subprocess, "run") as mocked_run:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_run.assert_not_called()
            worker_status = json.loads((reports_root / "refresh_status" / "latest" / "refresh_worker_status.json").read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "idle")
            self.assertFalse(worker_status["ranJob"])

    def test_main_run_once_autolaunches_stale_mlb_refresh_when_enabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            data_root = Path(tmp_dir) / "data"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            stale_report_path = data_root / "mlb_source" / "source_artifacts" / "data" / "live_lens" / "live_lens_report_2026_07_01.json"
            stale_report_path.parent.mkdir(parents=True, exist_ok=True)
            stale_report_path.write_text(json.dumps({"generatedAt": "2026-07-01T07:42:15Z", "games": []}), encoding="utf-8")
            stale_at = time.time() - 600.0
            stale_times = (stale_at, stale_at)
            stale_report_path.touch()
            import os

            os.utime(stale_report_path, stale_times)

            fake_launch_result = {"ok": True, "pid": 9876, "state": "running"}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "MLB_ENABLE_REFRESH_WORKER_AUTORUN": "1",
                    "MLB_LIVE_ODDSAPI_REFRESH_INTERVAL_SECONDS": "60",
                },
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "launch_refresh_run", return_value=fake_launch_result) as mocked_launch, patch.object(
                module.subprocess,
                "Popen",
            ) as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_launch.assert_called_once()
            called_kwargs = mocked_launch.call_args.kwargs
            self.assertEqual(called_kwargs["sports"], "mlb")
            self.assertEqual(called_kwargs["phase"], "live")
            self.assertEqual(called_kwargs["launch_mode"], "web_process")
            mocked_popen.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertTrue(worker_status["ranJob"])
            self.assertEqual(worker_status["launchPid"], 9876)

    def test_main_run_once_autolaunches_weekly_sports_refresh_when_in_season_and_enabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            fake_launch_result = {"ok": True, "pid": 4242, "state": "running"}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "central_today_iso", return_value="2026-10-15"), patch(
                # Patched, not live: the predicate calls ESPN, and this test is
                # about the autorun's launch shape, not about whether a real
                # game falls on the fixture date. False = fast tick claims
                # nothing, so the autorun still owns both sports.
                "syndicate.features.shared.live_refresh_loop._weekly_sport_claimed_by_fast_tick",
                return_value=False,
            ), patch.object(
                module, "launch_refresh_run", return_value=fake_launch_result
            ) as mocked_launch, patch.object(module.subprocess, "Popen") as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_launch.assert_called_once()
            called_kwargs = mocked_launch.call_args.kwargs
            self.assertEqual(called_kwargs["sports"], "nfl,ncaaf")
            self.assertEqual(called_kwargs["phase"], "live")
            self.assertEqual(called_kwargs["launch_mode"], "web_process")
            mocked_popen.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertTrue(worker_status["ranJob"])
            self.assertEqual(worker_status["launchPid"], 4242)

    def test_main_run_once_skips_weekly_sports_refresh_when_out_of_season(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "central_today_iso", return_value="2026-07-15"), patch.object(
                module, "launch_refresh_run"
            ) as mocked_launch:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_launch.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "idle")

    def test_active_weekly_sports_for_date_filters_to_in_season_weekly_sports(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        # Season filtering, with the fast tick claiming nothing. The predicate is
        # patched because it calls ESPN, and this assertion is about season
        # windows, not about whether a real game happens to fall on the date.
        with patch(
            "syndicate.features.shared.live_refresh_loop._weekly_sport_claimed_by_fast_tick",
            return_value=False,
        ):
            self.assertEqual(module._active_weekly_sports_for_date("2026-07-15"), "")
            self.assertEqual(module._active_weekly_sports_for_date("2026-10-15"), "nfl,ncaaf")
            self.assertEqual(module._active_weekly_sports_for_date("2026-12-01"), "nfl,ncaaf,ncaab")

    def test_active_weekly_sports_for_date_yields_sports_the_fast_tick_claims(self) -> None:
        # The other half of the ownership partition. A sport with games in the
        # horizon belongs to the fast odds tick (a 6-hourly autorun left the NFL
        # board 24h stale), so this autorun must drop it -- otherwise both write
        # the same non-date-partitioned football artifacts.
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with patch(
            "syndicate.features.shared.live_refresh_loop._weekly_sport_claimed_by_fast_tick",
            side_effect=lambda sport, _date: sport == "nfl",
        ):
            self.assertEqual(module._active_weekly_sports_for_date("2026-10-15"), "ncaaf")

    def test_active_weekly_sports_for_date_yields_when_ownership_unresolvable(self) -> None:
        # Asymmetric on purpose: the fast tick CLAIMS on unknown, so this must
        # YIELD on unknown. Both claiming corrupts a shared artifact silently;
        # neither claiming is a stale board, which is visible and which
        # audit_slate_coverage.py (#264) exists to catch.
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with patch(
            "syndicate.features.shared.live_refresh_loop._weekly_sport_claimed_by_fast_tick",
            side_effect=RuntimeError("cannot resolve ownership"),
        ):
            self.assertEqual(module._active_weekly_sports_for_date("2026-10-15"), "")

    # 2026-07-29 follow-up: soccer's pregame pipeline (schedule/odds/props/
    # picks) is phases=("pregame",)-only (refresh_odds_sources.py's
    # _build_soccer_steps), but live-odds-worker -- the only service with
    # the live-odds refresh loop enabled -- is pinned to phase=live, so
    # those steps never ran anywhere in production. Confirmed live via
    # /soccer/mls/api/cards: this week's Saturday fixtures all carried
    # is_unsimulated_placeholder=True while earlier-week fixtures did not.
    # Deliberately a SEPARATE autorun/flag from weekly-sports (NFL/NCAAF/
    # NCAAB) per explicit user direction, so fixing soccer doesn't
    # side-effect-activate that currently-dark path for those three sports.
    def test_main_run_once_autolaunches_soccer_weekly_refresh_when_in_season_and_enabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            fake_launch_result = {"ok": True, "pid": 4343, "state": "running"}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "central_today_iso", return_value="2026-07-29"), patch.object(
                module, "launch_refresh_run", return_value=fake_launch_result
            ) as mocked_launch, patch.object(module.subprocess, "Popen") as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_launch.assert_called_once()
            called_kwargs = mocked_launch.call_args.kwargs
            self.assertEqual(called_kwargs["sports"], "soccer")
            # #148: was "all" -- ran soccer's odds/props/schedule steps
            # directly from refresh-worker, a second direct OddsAPI caller
            # for soccer alongside live-odds-worker (same violation class
            # fixed for MLB in #139/#144). "live" keeps this autorun's real
            # job (the sim, soccer_{league}_artifacts, phases=("pregame","live"))
            # while dropping the pregame-only odds/props/schedule steps,
            # which _launch_autorun_soccer_pregame_refresh
            # (run_live_odds_refresh_worker.py) now owns instead.
            self.assertEqual(called_kwargs["phase"], "live")
            self.assertEqual(called_kwargs["launch_mode"], "web_process")
            mocked_popen.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertTrue(worker_status["ranJob"])
            self.assertEqual(worker_status["launchPid"], 4343)

    def test_main_run_once_skips_soccer_weekly_refresh_when_disabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            with patch.dict(
                module.os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "central_today_iso", return_value="2026-07-29"), patch.object(
                module, "launch_refresh_run"
            ) as mocked_launch:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_launch.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "idle")

    def test_main_run_once_autoruns_reconciliation_when_enabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            fake_summary = {"date": "placeholder", "predictions": 0, "resolved": 0, "skipped": 0, "result_files": []}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "central_today_iso", return_value="2026-07-15"), patch(
                "syndicate.features.prediction_reconciliation.reconcile_prediction_results_for_date",
                return_value={"ok": True, "summary": fake_summary},
            ) as mocked_reconcile, patch(
                # No stale pending dates in this case -- verifies the
                # yesterday/today behavior is unchanged when
                # pending_prediction_dates() has nothing extra to add.
                "syndicate.features.prediction_reconciliation.pending_prediction_dates",
                return_value=[],
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked_reconcile.call_count, 2)
            called_dates = sorted(call.args[0] for call in mocked_reconcile.call_args_list)
            self.assertEqual(called_dates, ["2026-07-14", "2026-07-15"])
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertTrue(worker_status["ranJob"])

    def test_main_run_once_reconciles_stale_pending_dates_too(self) -> None:
        # #147 follow-up: predictions dated outside the yesterday/today
        # window (worker downtime, autorun flag not live yet when logged,
        # an advance bet) previously could never be retried again, no
        # matter how long the app kept running. pending_prediction_dates()
        # must widen the reconciled date set to include them.
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            fake_summary = {"date": "placeholder", "predictions": 0, "resolved": 0, "skipped": 0, "result_files": []}

            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN": "1",
                },
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "central_today_iso", return_value="2026-07-15"), patch(
                "syndicate.features.prediction_reconciliation.reconcile_prediction_results_for_date",
                return_value={"ok": True, "summary": fake_summary},
            ) as mocked_reconcile, patch(
                "syndicate.features.prediction_reconciliation.pending_prediction_dates",
                return_value=["2026-06-23"],
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            called_dates = sorted(call.args[0] for call in mocked_reconcile.call_args_list)
            self.assertEqual(called_dates, ["2026-06-23", "2026-07-14", "2026-07-15"])

    def test_main_run_once_skips_reconciliation_when_disabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(json.dumps({"state": "idle"}), encoding="utf-8")

            with patch.dict(
                module.os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=True,
            ), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch(
                "syndicate.features.prediction_reconciliation.reconcile_prediction_results_for_date"
            ) as mocked_reconcile:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_reconcile.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "idle")

    def test_mlb_actuals_writer_tick_skipped_when_disabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")},
            clear=True,
        ):
            self.assertIsNone(module._run_mlb_actuals_writer_tick())

    def test_mlb_actuals_writer_tick_runs_for_pending_and_recent_dates(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            data_root = Path(tmp_dir) / "data"
            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "RECONCILIATION_ENABLE_MLB_ACTUALS_WRITER": "1",
                },
                clear=True,
            ), patch.object(module, "central_today_iso", return_value="2026-07-15"), patch(
                "scripts.build_mlb_actuals.write_mlb_actuals_for_date",
                return_value={"summary": {"resolved": 0}},
            ) as mocked_writer, patch(
                "syndicate.features.prediction_reconciliation.pending_prediction_dates",
                return_value=["2026-06-23"],
            ):
                status = module._run_mlb_actuals_writer_tick()

            self.assertIsNotNone(status)
            called_dates = sorted(call.args[0] for call in mocked_writer.call_args_list)
            self.assertEqual(called_dates, ["2026-06-23", "2026-07-14", "2026-07-15"])

    def test_betting_day_backfill_tick_is_a_no_op_without_a_target_date(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)
        with TemporaryDirectory() as tmp_dir, patch.dict(
            module.os.environ,
            {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")},
            clear=True,
        ):
            self.assertIsNone(module._run_mlb_betting_day_backfill_tick())

    def test_betting_day_backfill_tick_invokes_the_manifest_builder_with_scoped_args(self) -> None:
        # 2026-08-04. Narrow by design: --date must be passed (so the
        # vendored script's full_publish path, which touches the
        # season-wide manifest/recap, never engages) and --out/--recap-md
        # must point at a scratch path (so the real season-wide manifest
        # is never overwritten with a single-day version).
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            data_root = Path(tmp_dir) / "data"
            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "MLB_BETTING_DAY_BACKFILL_DATE": "2026-08-03",
                },
                clear=True,
            ), patch.object(module.subprocess, "run") as mocked_run:
                mocked_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
                status = module._run_mlb_betting_day_backfill_tick()

            self.assertIsNotNone(status)
            self.assertTrue(status["ok"])
            self.assertEqual(status["date"], "2026-08-03")
            mocked_run.assert_called_once()
            call_args = mocked_run.call_args
            command = call_args.args[0]
            self.assertIn("--season", command)
            self.assertEqual(command[command.index("--season") + 1], "2026")
            self.assertIn("--date", command)
            self.assertEqual(command[command.index("--date") + 1], "2026-08-03")
            self.assertIn("--profile-name", command)
            self.assertEqual(command[command.index("--profile-name") + 1], "retuned")
            # --out/--recap-md are the scratch-path guard -- must exist and
            # must NOT point at the real season-wide manifest/recap files.
            out_value = command[command.index("--out") + 1]
            recap_value = command[command.index("--recap-md") + 1]
            self.assertIn("2026-08-03", out_value)
            self.assertIn("2026-08-03", recap_value)
            self.assertNotIn("season_betting_cards_manifest.json", out_value)
            # --day-payload-dir/--cards-dir are the REAL production paths --
            # this is what's actually meant to be fixed.
            day_payload_dir = command[command.index("--day-payload-dir") + 1]
            cards_dir = command[command.index("--cards-dir") + 1]
            self.assertIn("betting_day_payloads_retuned", day_payload_dir)
            self.assertIn("locked_cards_retuned", cards_dir)

    def test_betting_day_backfill_tick_self_disables_after_success_for_the_same_date(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            data_root = Path(tmp_dir) / "data"
            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "MLB_BETTING_DAY_BACKFILL_DATE": "2026-08-03",
                },
                clear=True,
            ), patch.object(module.subprocess, "run") as mocked_run:
                mocked_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
                first = module._run_mlb_betting_day_backfill_tick()
                second = module._run_mlb_betting_day_backfill_tick()

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            mocked_run.assert_called_once()

    def test_betting_day_backfill_tick_retries_after_a_failed_attempt(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            data_root = Path(tmp_dir) / "data"
            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "MLB_BETTING_DAY_BACKFILL_DATE": "2026-08-03",
                },
                clear=True,
            ), patch.object(module.subprocess, "run") as mocked_run:
                mocked_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
                first = module._run_mlb_betting_day_backfill_tick()
                second = module._run_mlb_betting_day_backfill_tick()

            self.assertFalse(first["ok"])
            # A failed attempt must NOT self-disable -- the next tick should
            # try again, not silently stay broken forever.
            self.assertIsNotNone(second)
            self.assertEqual(mocked_run.call_count, 2)

    def test_betting_day_backfill_tick_reports_an_unparseable_date_without_running_the_subprocess(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            with patch.dict(
                module.os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "MLB_BETTING_DAY_BACKFILL_DATE": "not-a-date"},
                clear=True,
            ), patch.object(module.subprocess, "run") as mocked_run:
                status = module._run_mlb_betting_day_backfill_tick()

            self.assertFalse(status["ok"])
            self.assertIn("error", status)
            mocked_run.assert_not_called()

    def test_main_run_once_marks_worker_status_claimed_when_pending(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(
                json.dumps({"state": "pending_external", "externalRunner": {"kind": "external_runner"}}),
                encoding="utf-8",
            )
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"

            fake_process = unittest.mock.MagicMock()
            fake_process.pid = 4321
            fake_process.poll.return_value = 0

            with patch.dict(module.os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=True), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module.subprocess, "Popen", return_value=fake_process) as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_popen.assert_called_once()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertTrue(worker_status["ranJob"])
            self.assertEqual(worker_status["launchPid"], 4321)
            self.assertEqual(worker_status["refreshCycle"], {"claimed_count": 1, "reclaimed_count": 0, "skipped_due_to_cap": 0})

    def test_main_run_once_rejects_claimed_state_as_pending(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            latest_manifest_path.write_text(
                json.dumps({"state": "claimed", "externalRunner": {"kind": "external_runner"}}),
                encoding="utf-8",
            )

            self.assertFalse(module._has_pending_external_contract(latest_manifest_path))

    def test_main_run_once_throttles_when_active_job_is_running(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(
                json.dumps({"state": "launched", "launchPid": 4321, "externalRunner": {"kind": "external_runner"}}),
                encoding="utf-8",
            )

            with patch.dict(module.os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=True), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module.subprocess, "Popen") as mocked_popen, patch.object(
                module,
                "_pid_is_running",
                return_value=True,
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_popen.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "throttled")
            self.assertIn("configured limit", worker_status["detail"])
            self.assertEqual(worker_status["refreshCycle"], {"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 1})

    def test_main_run_once_recovers_dead_running_contract_before_cap_check(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(
                json.dumps({"state": "running", "pid": 4321, "externalRunner": {"kind": "external_runner", "queue_state": "queued"}}),
                encoding="utf-8",
            )

            with patch.dict(module.os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=True), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module, "_pid_is_running", return_value=False), patch.object(module.subprocess, "Popen") as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_popen.assert_not_called()
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertNotEqual(worker_status["state"], "throttled")
            self.assertEqual(worker_status["state"], "idle")
            self.assertFalse(worker_status["ranJob"])
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest_payload["state"], "failed")
            self.assertNotIn("pid", latest_payload)
            self.assertIn("workerRecoveredAt", latest_payload)
            self.assertEqual(latest_payload["workerRecoveryReason"], "dead_refresh_process")

    def test_recover_dead_active_contract_defers_when_job_status_is_recently_running(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            run_summary_path = Path(tmp_dir) / "migration_runs" / "2026-07-06" / "odds_refresh_20260706_211933" / "refresh_and_gate_run.json"
            job_status_path = run_summary_path.parent / "refresh_job_status.json"
            run_summary_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "pid": 4321,
                        "runSummaryPath": str(run_summary_path),
                        "oddsRefreshPath": str(run_summary_path.parent / "odds_refresh.json"),
                        "externalRunner": {
                            "kind": "external_runner",
                            "queue_state": "queued",
                            "runSummaryPath": str(run_summary_path),
                            "stdoutPath": str(run_summary_path.parent / "odds_refresh.json"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            recent_updated_at = (datetime.utcnow() - timedelta(seconds=30)).isoformat(timespec="seconds") + "Z"
            job_status_path.write_text(json.dumps({"state": "running", "updatedAt": recent_updated_at}), encoding="utf-8")

            with patch.object(module, "_pid_is_running", return_value=False):
                recovered = module._recover_dead_active_contract(latest_manifest_path)

            self.assertFalse(recovered)
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest_payload["state"], "running")

    def test_recover_dead_active_contract_defers_when_completed_artifacts_exist(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            run_summary_path = Path(tmp_dir) / "migration_runs" / "2026-07-06" / "odds_refresh_20260706_211933" / "refresh_and_gate_run.json"
            odds_refresh_path = run_summary_path.parent / "odds_refresh.json"
            job_status_path = run_summary_path.parent / "refresh_job_status.json"
            run_summary_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "pid": 4321,
                        "runSummaryPath": str(run_summary_path),
                        "oddsRefreshPath": str(odds_refresh_path),
                        "externalRunner": {
                            "kind": "external_runner",
                            "queue_state": "queued",
                            "runSummaryPath": str(run_summary_path),
                            "stdoutPath": str(odds_refresh_path),
                        },
                    }
                ),
                encoding="utf-8",
            )
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            job_status_path.write_text(json.dumps({"state": "running", "updatedAt": (datetime.utcnow() - timedelta(minutes=10)).isoformat(timespec="seconds") + "Z"}), encoding="utf-8")
            odds_refresh_path.write_text(json.dumps({"ok": True, "returnCode": 0}), encoding="utf-8")

            with patch.object(module, "_pid_is_running", return_value=False):
                recovered = module._recover_dead_active_contract(latest_manifest_path)

            self.assertFalse(recovered)
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest_payload["state"], "running")

    def test_recover_dead_active_contract_marks_failed_for_stale_running_status_without_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            latest_manifest_path = Path(tmp_dir) / "refresh_status_latest.json"
            run_summary_path = Path(tmp_dir) / "migration_runs" / "2026-07-06" / "odds_refresh_20260706_211933" / "refresh_and_gate_run.json"
            job_status_path = run_summary_path.parent / "refresh_job_status.json"
            run_summary_path.parent.mkdir(parents=True, exist_ok=True)
            latest_manifest_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "pid": 4321,
                        "runSummaryPath": str(run_summary_path),
                        "oddsRefreshPath": str(run_summary_path.parent / "odds_refresh.json"),
                        "externalRunner": {
                            "kind": "external_runner",
                            "queue_state": "queued",
                            "runSummaryPath": str(run_summary_path),
                            "stdoutPath": str(run_summary_path.parent / "odds_refresh.json"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            stale_updated_at = (datetime.utcnow() - timedelta(minutes=10)).isoformat(timespec="seconds") + "Z"
            job_status_path.write_text(json.dumps({"state": "running", "updatedAt": stale_updated_at}), encoding="utf-8")

            with patch.object(module, "_pid_is_running", return_value=False):
                recovered = module._recover_dead_active_contract(latest_manifest_path)

            self.assertTrue(recovered)
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest_payload["state"], "failed")
            self.assertEqual(latest_payload["workerRecoveryReason"], "dead_refresh_process")
            self.assertIn("workerRecoveredAt", latest_payload)

    def test_main_run_once_recovers_stuck_claim_before_launch(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            worker_status_path = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            stale_claimed_at = (datetime.utcnow() - timedelta(minutes=30)).isoformat(timespec="seconds") + "Z"
            latest_manifest_path.write_text(
                json.dumps(
                    {
                        "state": "claimed",
                        "workerClaimedAt": stale_claimed_at,
                        "externalRunner": {
                            "kind": "external_runner",
                            "queue_state": "queued",
                            "runStamp": "20260522_120000",
                            "manifestPath": str(reports_root / "refresh_status" / "2026-05-22" / "20260522_120000" / "refresh_status_manifest.json"),
                            "latestPath": str(latest_manifest_path),
                            "runSummaryPath": str(reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "refresh_and_gate_run.json"),
                            "jobStatusPath": str(reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "refresh_job_status.json"),
                            "stdoutPath": str(reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "odds_refresh.json"),
                            "stderrPath": str(reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "odds_refresh.stderr.txt"),
                            "command": [sys.executable, "-c", "print('ok')"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            fake_process = unittest.mock.MagicMock()
            fake_process.pid = 4321
            fake_process.poll.return_value = 0

            with patch.dict(module.os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=True), patch.object(
                sys,
                "argv",
                [
                    "run_refresh_worker.py",
                    "--latest-manifest",
                    str(latest_manifest_path),
                    "--worker-status",
                    str(worker_status_path),
                    "--run-once",
                ],
            ), patch.object(module.subprocess, "Popen", return_value=fake_process) as mocked_popen, patch.object(
                module,
                "_pid_is_running",
                return_value=False,
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_popen.assert_called_once()
            refreshed_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(refreshed_payload["state"], "claimed")
            self.assertIn("workerRecoveredAt", refreshed_payload)
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertEqual(worker_status["launchPid"], 4321)
            self.assertEqual(worker_status["refreshCycle"], {"claimed_count": 1, "reclaimed_count": 1, "skipped_due_to_cap": 0})

    def test_default_poll_seconds_is_thirty(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with patch.dict(module.os.environ, {}, clear=True):
            self.assertEqual(module._default_poll_seconds(), 30.0)

    def test_default_latest_manifest_path_uses_refresh_worker_lane_when_enabled(self) -> None:
        # This poll loop only ever runs on refresh-worker and is the only
        # process that claims queued/external-runner contracts, so its
        # manifest must always be refresh-worker's own lane -- matching the
        # same hardcoded lane launch_refresh_run resolves external-runner
        # launches to, regardless of which service enqueued the job.
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                module.os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": tmp_dir,
                    "SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES": "true",
                },
                clear=False,
            ):
                path = module._default_latest_manifest_path()
        self.assertEqual(path.name, "refresh_status_latest__refresh-worker.json")

    def test_default_latest_manifest_path_is_legacy_when_lanes_disabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                module.os.environ,
                {"SYNDICATE_REPORTS_ROOT": tmp_dir},
                clear=False,
            ):
                module.os.environ.pop("SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES", None)
                path = module._default_latest_manifest_path()
        self.assertEqual(path.name, "refresh_status_latest.json")


if __name__ == "__main__":
    unittest.main()