from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()