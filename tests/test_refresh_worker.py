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

            # A league with no committed players/ dir must not get one
            # manufactured out of nothing.
            #
            # This used to name `championship` as the example. That rotted on
            # 2026-08-08 when championship and primeira_liga -- the two leagues
            # that had NO player history anywhere, and so produced empty player
            # props on every otherwise-successful sim -- were finally seeded.
            # The contract is unchanged; only the example was stale, so assert
            # it against the repo instead of against one league name.
            repo_soccer = repo_root / "data" / "soccer_source"
            leagues_with_seeds = {
                d.name for d in repo_soccer.iterdir()
                if d.is_dir() and list((d / "players").glob("players_*.csv"))
            }
            leagues_without_seeds = {
                d.name for d in repo_soccer.iterdir()
                if d.is_dir() and not list((d / "players").glob("players_*.csv"))
            }
            for league in leagues_without_seeds:
                self.assertFalse(
                    (fake_data_root / "soccer_source" / league / "players").exists(),
                    f"{league} has no committed players/ and must not have one manufactured",
                )
            for league in leagues_with_seeds:
                self.assertTrue((fake_data_root / "soccer_source" / league / "players").exists())

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
                module,
                "_soccer_refresh_units",
                return_value=([{"league": "mls", "date": "2026-07-29"}], "league_date"),
            ), patch.object(
                module, "launch_refresh_run", return_value=fake_launch_result
            ) as mocked_launch, patch.object(module.subprocess, "Popen") as mocked_popen:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_launch.assert_called_once()
            called_kwargs = mocked_launch.call_args.kwargs
            self.assertEqual(called_kwargs["sports"], "soccer")
            # #282: the launch must be scoped to ONE league-date, not the whole
            # sport. Asserted on the arguments rather than on "a launch
            # happened", because the pre-#282 code also launched exactly once
            # here -- the outcome is identical and only the scope distinguishes
            # them.
            self.assertEqual(called_kwargs["soccer_leagues"], "mls")
            self.assertEqual(called_kwargs["soccer_date"], "2026-07-29")
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

def test_soccer_history_seed_bootstrap_copies_match_history(tmp_path, monkeypatch):
    """The second stage of the soccer-sim failure, and the one that actually
    kept every non-MLS league silent.

    `build_soccer_artifacts._load_team_ratings` reads per-league match history
    from its --source-root, which on the worker is the runtime disk. The CSVs
    are committed to git for all nine non-MLS leagues and nothing copied them
    across, so the sim raised "no match history under <root>/<league>/history"
    and exited in TWO SECONDS before writing anything.

    Reproduced 2026-08-08 against an empty source root, and verified fixed:
    with history seeded, belgian_pro_league simulated 3 matches / 158 player
    projections in 145s and wrote its recommendations artifact.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rrw", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    )
    rrw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rrw)

    data_root = tmp_path / "runtime"
    data_root.mkdir()
    monkeypatch.setattr(rrw, "_refresh_state_store", lambda: {"data_root": lambda: data_root})

    seeded = rrw._bootstrap_soccer_seed_files(relative_subdir="history", glob_pattern="*.csv")

    assert seeded, "expected the git-tracked history CSVs to be seeded"
    # MLS must NOT be seeded: it has no history/ in git because it sources team
    # history from ASA instead. That asymmetry is exactly why MLS was the one
    # league still producing sims while the other nine went silent.
    assert "mls" not in seeded
    for league in ("belgian_pro_league", "eredivisie", "primeira_liga"):
        assert league in seeded
        assert list((data_root / "soccer_source" / league / "history").glob("*.csv"))


def test_soccer_history_seed_bootstrap_never_overwrites_real_pipeline_output(tmp_path, monkeypatch):
    """Same narrow contract the players/schedule bootstraps hold: only ever
    copies into a subdirectory with NO matching files yet, so it can never
    replace something the real pipeline has written."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "rrw2", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    )
    rrw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rrw)

    data_root = tmp_path / "runtime"
    existing = data_root / "soccer_source" / "eredivisie" / "history"
    existing.mkdir(parents=True)
    (existing / "matches_2025.csv").write_text("REAL PIPELINE OUTPUT\n", encoding="utf-8")
    monkeypatch.setattr(rrw, "_refresh_state_store", lambda: {"data_root": lambda: data_root})

    seeded = rrw._bootstrap_soccer_seed_files(relative_subdir="history", glob_pattern="*.csv")

    assert "eredivisie" not in seeded
    assert (existing / "matches_2025.csv").read_text(encoding="utf-8") == "REAL PIPELINE OUTPUT\n"


# ---------------------------------------------------------------------------
# #282 -- per-league-date soccer sim scoping.
#
# What these protect, stated as the failure rather than the feature: on
# 2026-08-08 a wedged manifest made `_has_pending_external_contract` re-claim
# and respawn on every 30s poll tick with nothing bounding concurrency, and
# because one soccer job was 10-20 minutes of real work, the overlap reached
# ~31 concurrent jobs and OOM-killed refresh-worker nine times in 82 minutes.
# Splitting the job so one job == one league-date cuts the overlap to
# job_duration/poll_interval on the LONGEST SINGLE LEAGUE.
#
# These tests bound the damage. They do NOT test a concurrency guard, because
# there still isn't one -- that is #279's separate open item.
# ---------------------------------------------------------------------------


def _load_rrw(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingStore:
    """Minimal refresh-state-store double that also COUNTS writes.

    The write count is the point, not incidental: more, smaller jobs means more
    launcher invocations and more manifest churn, on a launcher already firing
    every ~30s. A change that moves cost out of memory and into write volume
    without anyone noticing would be a bad trade made silently.
    """

    def __init__(self, reports_root: Path) -> None:
        self._reports_root = reports_root
        self.files: dict[str, dict] = {}
        self.write_count = 0

    def as_dict(self) -> dict:
        return {
            "read_json_file": lambda path: self.files.get(str(path)),
            "write_json_file": self._write,
            "reports_root": lambda: self._reports_root,
            "data_root": lambda: self._reports_root,
            "assert_refresh_state_backend_ready": lambda **_kwargs: None,
        }

    def _write(self, path, payload) -> None:
        self.write_count += 1
        self.files[str(path)] = payload


def _soccer_launch_harness(tmp_path, monkeypatch, *, units, launch_result=None, launch_error=None):
    rrw = _load_rrw("rrw_282")
    reports_root = tmp_path / "reports"
    store = _RecordingStore(reports_root)
    monkeypatch.setattr(rrw, "_refresh_state_store", store.as_dict)
    monkeypatch.setattr(rrw, "central_today_iso", lambda: "2026-08-09")
    monkeypatch.setattr(rrw, "_soccer_active_for_date", lambda _date: True)
    monkeypatch.setattr(rrw, "_soccer_refresh_units", lambda _date: (list(units), "league_date"))
    monkeypatch.setattr(rrw, "_current_active_job_count", lambda _path: 0)
    monkeypatch.setattr(rrw, "_latest_manifest_payload", lambda _path: {"state": "idle"})
    monkeypatch.setenv("SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN", "true")
    # Spacing of 1s keeps the round-robin observable without sleeping; the
    # spacing gate itself gets its own test below.
    monkeypatch.setenv("SYNDICATE_SOCCER_LEAGUE_LAUNCH_SPACING_SECONDS", "1")

    calls: list[dict] = []

    def fake_launch(**kwargs):
        calls.append(kwargs)
        if launch_error is not None:
            raise launch_error
        return launch_result or {"ok": True, "pid": 777, "state": "running"}

    monkeypatch.setattr(rrw, "launch_refresh_run", fake_launch)
    return rrw, store, calls


def _run_soccer_autorun(rrw, tmp_path):
    return rrw._launch_autorun_soccer_weekly_refresh(
        latest_manifest_path=tmp_path / "latest.json",
        worker_status_path=tmp_path / "worker.json",
        refresh_cycle={"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 0},
    )


def test_soccer_autorun_launches_one_league_date_not_the_whole_sport(tmp_path, monkeypatch):
    units = [
        {"league": "eredivisie", "date": "2026-08-09"},
        {"league": "primeira_liga", "date": "2026-08-09"},
        {"league": "belgian_pro_league", "date": "2026-08-10"},
    ]
    rrw, _store, calls = _soccer_launch_harness(tmp_path, monkeypatch, units=units)

    assert _run_soccer_autorun(rrw, tmp_path) is True
    assert len(calls) == 1
    # ONE league and ONE date -- the whole deliverable. Pre-#282 this call
    # carried neither kwarg and the job covered all ten leagues.
    assert calls[0]["soccer_leagues"] == "eredivisie"
    assert calls[0]["soccer_date"] == "2026-08-09"
    assert calls[0]["sports"] == "soccer"
    assert calls[0]["phase"] == "live"


def test_soccer_autorun_round_robins_across_units_without_repeating(tmp_path, monkeypatch):
    units = [
        {"league": "eredivisie", "date": "2026-08-09"},
        {"league": "primeira_liga", "date": "2026-08-09"},
        {"league": "belgian_pro_league", "date": "2026-08-10"},
    ]
    rrw, _store, calls = _soccer_launch_harness(tmp_path, monkeypatch, units=units)

    launched: list[tuple[str, str]] = []
    for _ in range(len(units)):
        # Spacing is 1s; advance the clock rather than sleeping.
        base = time.time()
        monkeypatch.setattr(rrw.time, "time", lambda base=base, n=len(launched): base + 10.0 * (n + 1))
        assert _run_soccer_autorun(rrw, tmp_path) is True
        launched.append((calls[-1]["soccer_leagues"], calls[-1]["soccer_date"]))

    # Every unit exactly once before any repeats -- a unit must not be starved
    # by ordering, which is why the picker sorts by staleness rather than
    # taking the first due entry.
    assert sorted(launched) == sorted((u["league"], u["date"]) for u in units)


def test_soccer_autorun_spacing_gate_blocks_a_second_launch_in_the_same_window(tmp_path, monkeypatch):
    units = [
        {"league": "eredivisie", "date": "2026-08-09"},
        {"league": "primeira_liga", "date": "2026-08-09"},
    ]
    rrw, _store, calls = _soccer_launch_harness(tmp_path, monkeypatch, units=units)
    monkeypatch.setenv("SYNDICATE_SOCCER_LEAGUE_LAUNCH_SPACING_SECONDS", "3600")

    assert _run_soccer_autorun(rrw, tmp_path) is True
    # Second tick, immediately after: a unit IS due, but it is not its turn.
    # Without this gate the first tick after a deploy finds every unit stale
    # and fires them on consecutive 30s ticks -- rebuilding the overlap this
    # change exists to prevent, by design rather than by accident.
    assert _run_soccer_autorun(rrw, tmp_path) is False
    assert len(calls) == 1


def test_soccer_autorun_does_not_stack_on_an_active_job(tmp_path, monkeypatch):
    units = [{"league": "eredivisie", "date": "2026-08-09"}]
    rrw, _store, calls = _soccer_launch_harness(tmp_path, monkeypatch, units=units)
    monkeypatch.setattr(rrw, "_current_active_job_count", lambda _path: 1)

    assert _run_soccer_autorun(rrw, tmp_path) is False
    assert calls == []


def test_soccer_autorun_stamps_a_failed_unit_so_it_cannot_starve_the_others(tmp_path, monkeypatch):
    units = [
        {"league": "eredivisie", "date": "2026-08-09"},
        {"league": "primeira_liga", "date": "2026-08-09"},
    ]
    rrw, store, calls = _soccer_launch_harness(
        tmp_path, monkeypatch, units=units, launch_error=RuntimeError("boom")
    )

    assert _run_soccer_autorun(rrw, tmp_path) is False
    assert len(calls) == 1
    status = next(payload for path, payload in store.files.items() if "soccer_weekly_autorun_status" in path)
    # A permanently-failing unit that never gets stamped stays the stalest
    # forever, so stalest-first would return it every window and nothing else
    # would ever run. The bug only appears once something is already broken,
    # which is exactly when it is hardest to see.
    assert status["unitEpochs"]["eredivisie|2026-08-09"] > 0
    assert status["error"].startswith("RuntimeError")


def test_soccer_autorun_reports_an_empty_unit_list_rather_than_returning_a_bare_false(tmp_path, monkeypatch, capsys):
    rrw, _store, calls = _soccer_launch_harness(tmp_path, monkeypatch, units=[])

    assert _run_soccer_autorun(rrw, tmp_path) is False
    assert calls == []
    # "No fixtures in the horizon" and "autorun disabled" both return False.
    # They must not look the same from outside.
    assert "SOCCER_UNITS_EMPTY" in capsys.readouterr().out


def test_soccer_autorun_status_write_count_is_one_per_launch(tmp_path, monkeypatch):
    """More jobs must not mean more writes PER job.

    Per-league scoping multiplies the number of launches by the unit count, so
    the per-launch write cost is what decides whether this trades memory
    pressure for write pressure. One status write per launch keeps the added
    volume proportional to launches and nothing worse.
    """
    units = [{"league": "eredivisie", "date": "2026-08-09"}]
    rrw, store, _calls = _soccer_launch_harness(tmp_path, monkeypatch, units=units)

    before = store.write_count
    assert _run_soccer_autorun(rrw, tmp_path) is True
    # One autorun-status write plus one worker-status write.
    assert store.write_count - before == 2


# ---------------------------------------------------------------------------
# #311 -- the active-jobs cap could not fire, for two independent reasons.
#
#   1. `run_refresh_worker.py` computed `active_jobs >= max_active_jobs`, wrote
#      a `throttled` worker status, and then `return`ed only under --run-once.
#      The long-running loop fell through and spawned anyway.
#   2. `_current_active_job_count` returns 0 when the manifest is `running`
#      with no live pid -- exactly the condition `_has_pending_external_contract`
#      requires to re-claim. Mutually exclusive predicates: the cap read zero
#      precisely when the runaway was running.
#
# Fixing only (1) yields a cap that is still structurally unable to fire, which
# would look like a fix and be inert.
# ---------------------------------------------------------------------------


WEDGED_MANIFEST = {
    # The 2026-08-08 signature: claimed, the pid never recorded, contract still
    # queued. `_has_pending_external_contract` says "re-claim me" and
    # `_current_active_job_count` says "nothing is running".
    "state": "running",
    "externalRunner": {
        "kind": "external_runner",
        "queue_state": "queued",
        "runStamp": "20260808_235200",
        "command": ["python", "-c", "pass"],
    },
}


def _run_main_once(rrw, tmp_path, monkeypatch, *, env=None):
    reports_root = tmp_path / "reports"
    latest = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
    worker_status = reports_root / "refresh_status" / "latest" / "refresh_worker_status.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(WEDGED_MANIFEST), encoding="utf-8")

    for key, value in {"SYNDICATE_REPORTS_ROOT": str(reports_root), **(env or {})}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_refresh_worker.py",
            "--latest-manifest", str(latest),
            "--worker-status", str(worker_status),
            "--run-once",
        ],
    )
    spawned: list = []
    monkeypatch.setattr(rrw.subprocess, "Popen", lambda *a, **k: spawned.append(a) or _FakePopen())
    monkeypatch.setattr(rrw, "_run_mlb_sim_tick", lambda: None)
    monkeypatch.setattr(rrw, "_run_mlb_actuals_writer_tick", lambda: None)
    monkeypatch.setattr(rrw, "_run_mlb_betting_day_backfill_tick", lambda: None)
    monkeypatch.setattr(rrw, "_diag_log_all_process_memory", lambda _stage: None)
    exit_code = rrw.main()
    status = json.loads(worker_status.read_text(encoding="utf-8")) if worker_status.exists() else {}
    return exit_code, spawned, status


class _FakePopen:
    pid = 4242


def test_311_cap_blocks_the_reclaim_when_a_job_process_is_already_running(tmp_path, monkeypatch):
    """The regression test for the actual defect.

    Manifest says nothing is running (state=running, no pid) AND says
    "re-claim me" (queue_state=queued). One job runner is genuinely alive.
    Pre-fix, `_current_active_job_count` returned 0, the cap was skipped, and
    the worker spawned a SECOND job -- every tick, forever. That is how the
    process count reached 79.
    """
    rrw = _load_rrw("rrw_311_a")
    monkeypatch.setattr(rrw, "_running_job_process_count", lambda: 1)

    exit_code, spawned, status = _run_main_once(
        rrw, tmp_path, monkeypatch, env={"SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS": "1"}
    )

    assert exit_code == 0
    assert spawned == [], "at cap, the worker must not spawn another job runner"
    assert status.get("state") == "throttled"
    assert status.get("refreshCycle", {}).get("skipped_due_to_cap") == 1


def test_311_manifest_alone_still_reads_zero_on_a_wedged_contract(tmp_path, monkeypatch):
    """Pins the defect itself, so the fix cannot be silently undone.

    If someone reverts `_resolve_active_job_count` to the manifest view, this
    is the assertion that explains why the cap stops working.
    """
    rrw = _load_rrw("rrw_311_b")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps(WEDGED_MANIFEST), encoding="utf-8")
    monkeypatch.setattr(rrw, "_refresh_state_store", lambda: {
        "read_json_file": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
        "write_json_file": lambda path, payload: None,
        "reports_root": lambda: tmp_path,
        "data_root": lambda: tmp_path,
        "assert_refresh_state_backend_ready": lambda **_k: None,
    })

    # The two predicates are mutually exclusive -- that IS the bug.
    assert rrw._current_active_job_count(latest) == 0
    assert rrw._has_pending_external_contract(latest) is True

    # And the resolver is what breaks the tie, using the process count.
    monkeypatch.setattr(rrw, "_running_job_process_count", lambda: 2)
    count, source = rrw._resolve_active_job_count(latest)
    assert count == 2
    assert source == "process_and_manifest"


def test_311_unknown_process_count_is_labelled_not_silently_zero(tmp_path, monkeypatch):
    """Unknown must not render as a verified zero.

    A container we cannot enumerate is exactly the case where handing the
    permissive branch to the unknown is how the cap failed originally. The
    count may fall back to the manifest, but the SOURCE must say so.
    """
    rrw = _load_rrw("rrw_311_c")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"state": "idle"}), encoding="utf-8")
    monkeypatch.setattr(rrw, "_refresh_state_store", lambda: {
        "read_json_file": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
        "write_json_file": lambda path, payload: None,
        "reports_root": lambda: tmp_path,
        "data_root": lambda: tmp_path,
        "assert_refresh_state_backend_ready": lambda **_k: None,
    })
    monkeypatch.setattr(rrw, "_running_job_process_count", lambda: None)

    count, source = rrw._resolve_active_job_count(latest)
    assert source == "manifest_only_process_enum_unavailable"
    assert count == 0  # the manifest's answer, but never presented as verified


def test_311_resolver_takes_the_max_because_both_instruments_read_low(tmp_path, monkeypatch):
    """Manifest misses a job whose pid it never recorded; process enumeration
    misses a job claimed but not yet spawned. Either alone reads low, and low
    is the direction that spawns."""
    rrw = _load_rrw("rrw_311_d")
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps({"state": "running", "pid": os.getpid(), "externalRunner": {"kind": "external_runner"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rrw, "_refresh_state_store", lambda: {
        "read_json_file": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
        "write_json_file": lambda path, payload: None,
        "reports_root": lambda: tmp_path,
        "data_root": lambda: tmp_path,
        "assert_refresh_state_backend_ready": lambda **_k: None,
    })

    # Manifest sees 1 (live pid), processes see 0 (not spawned / not visible).
    monkeypatch.setattr(rrw, "_running_job_process_count", lambda: 0)
    assert rrw._resolve_active_job_count(latest)[0] == 1


def test_311_process_counter_returns_none_rather_than_zero_when_blind(monkeypatch):
    """`None` is the contract for "could not enumerate". Returning 0 here would
    push the permissive answer up into the cap."""
    rrw = _load_rrw("rrw_311_e")
    monkeypatch.setattr(rrw, "Path", _NoProcPath)
    monkeypatch.setitem(sys.modules, "psutil", None)

    assert rrw._running_job_process_count() is None


class _NoProcPath(Path):
    """A Path whose /proc does not exist, to simulate a non-Linux container."""

    _flavour = getattr(Path(), "_flavour", None)

    def is_dir(self):  # type: ignore[override]
        return False
