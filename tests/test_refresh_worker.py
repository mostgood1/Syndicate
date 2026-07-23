from __future__ import annotations

import importlib.util
import json
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

            with patch.object(
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
            ), patch.object(module, "central_today_iso", return_value="2026-10-15"), patch.object(
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

        self.assertEqual(module._active_weekly_sports_for_date("2026-07-15"), "")
        self.assertEqual(module._active_weekly_sports_for_date("2026-10-15"), "nfl,ncaaf")
        self.assertEqual(module._active_weekly_sports_for_date("2026-12-01"), "nfl,ncaaf,ncaab")

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
            ) as mocked_reconcile:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked_reconcile.call_count, 2)
            called_dates = sorted(call.args[0] for call in mocked_reconcile.call_args_list)
            self.assertEqual(called_dates, ["2026-07-14", "2026-07-15"])
            worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
            self.assertEqual(worker_status["state"], "launched")
            self.assertTrue(worker_status["ranJob"])

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