from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RefreshQueueRunnerTests(unittest.TestCase):
    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "run_queued_refresh_job.py"
        spec = importlib.util.spec_from_file_location("test_run_queued_refresh_job", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_claim_external_runner_contract_marks_latest_and_run_manifest_running(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            latest_manifest_path = root / "reports" / "refresh_status" / "latest" / "refresh_status_latest.json"
            manifest_path = root / "reports" / "refresh_status" / "2026-05-22" / "20260522_120000" / "refresh_status_manifest.json"
            run_summary_path = root / "reports" / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "refresh_and_gate_run.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            run_summary_path.parent.mkdir(parents=True, exist_ok=True)

            contract = {
                "kind": "external_runner",
                "queue_state": "queued",
                "runStamp": "20260522_120000",
                "manifestPath": str(manifest_path),
                "latestPath": str(latest_manifest_path),
                "runSummaryPath": str(run_summary_path),
                "jobStatusPath": str(run_summary_path.parent / "refresh_job_status.json"),
                "stdoutPath": str(run_summary_path.parent / "odds_refresh.json"),
                "stderrPath": str(run_summary_path.parent / "odds_refresh.stderr.txt"),
                "command": [sys.executable, "-c", "print('ok')"],
            }
            latest_manifest_path.write_text(
                json.dumps({"state": "pending_external", "externalRunner": contract}),
                encoding="utf-8",
            )
            manifest_path.write_text(json.dumps({"state": "pending_external"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "pending_external"}), encoding="utf-8")

            claimed = module._claim_external_runner_contract(latest_manifest_path=latest_manifest_path)

            self.assertEqual(claimed["runStamp"], "20260522_120000")
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            run_summary_payload = json.loads(run_summary_path.read_text(encoding="utf-8"))
            self.assertEqual(latest_payload["state"], "running")
            self.assertEqual(manifest_payload["state"], "running")
            self.assertEqual(run_summary_payload["state"], "running")
            self.assertEqual(latest_payload["runnerKind"], "external_runner")
            self.assertEqual(claimed["jobStatusPath"], str(run_summary_path.parent / "refresh_job_status.json"))

    def test_claim_external_runner_contract_recovers_stale_running_manifest_without_pid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            latest_manifest_path = root / "reports" / "refresh_status" / "latest" / "refresh_status_latest.json"
            manifest_path = root / "reports" / "refresh_status" / "2026-05-22" / "20260522_120000" / "refresh_status_manifest.json"
            run_summary_path = root / "reports" / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "refresh_and_gate_run.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            run_summary_path.parent.mkdir(parents=True, exist_ok=True)

            contract = {
                "kind": "external_runner",
                "queue_state": "queued",
                "runStamp": "20260522_120000",
                "manifestPath": str(manifest_path),
                "latestPath": str(latest_manifest_path),
                "runSummaryPath": str(run_summary_path),
                "jobStatusPath": str(run_summary_path.parent / "refresh_job_status.json"),
                "stdoutPath": str(run_summary_path.parent / "odds_refresh.json"),
                "stderrPath": str(run_summary_path.parent / "odds_refresh.stderr.txt"),
                "command": [sys.executable, "-c", "print('ok')"],
            }
            latest_manifest_path.write_text(
                json.dumps({"state": "running", "externalRunner": contract}),
                encoding="utf-8",
            )
            manifest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")

            claimed = module._claim_external_runner_contract(latest_manifest_path=latest_manifest_path)
            latest_payload = json.loads(latest_manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(claimed["runStamp"], "20260522_120000")
        self.assertEqual(latest_payload["state"], "running")
        self.assertEqual(latest_payload["runnerKind"], "external_runner")

    def test_build_wrapper_command_uses_persisted_contract_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        contract = {
            "manifestPath": "manifest.json",
            "latestPath": "latest.json",
            "runSummaryPath": "summary.json",
            "jobStatusPath": "job_status.json",
            "stdoutPath": "stdout.json",
            "stderrPath": "stderr.txt",
            "command": [sys.executable, "-m", "unittest", "tests.test_ops"],
        }

        wrapper_command = module._build_wrapper_command(contract)

        self.assertIn(str(repo_root / "scripts" / "run_refresh_odds_job.py"), wrapper_command)
        self.assertIn("--manifest-path", wrapper_command)
        self.assertIn("summary.json", wrapper_command)
        self.assertEqual(wrapper_command[-4:], [sys.executable, "-m", "unittest", "tests.test_ops"])

    def test_main_executes_wrapper_for_latest_queued_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            latest_manifest_path = root / "reports" / "refresh_status" / "latest" / "refresh_status_latest.json"
            manifest_path = root / "reports" / "refresh_status" / "2026-05-22" / "20260522_120000" / "refresh_status_manifest.json"
            run_summary_path = root / "reports" / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000" / "refresh_and_gate_run.json"
            latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            run_summary_path.parent.mkdir(parents=True, exist_ok=True)

            contract = {
                "kind": "external_runner",
                "queue_state": "queued",
                "runStamp": "20260522_120000",
                "manifestPath": str(manifest_path),
                "latestPath": str(latest_manifest_path),
                "runSummaryPath": str(run_summary_path),
                "jobStatusPath": str(run_summary_path.parent / "refresh_job_status.json"),
                "stdoutPath": str(run_summary_path.parent / "odds_refresh.json"),
                "stderrPath": str(run_summary_path.parent / "odds_refresh.stderr.txt"),
                "command": [sys.executable, "-c", "print('ok')"],
            }
            latest_manifest_path.write_text(
                json.dumps({"state": "pending_external", "externalRunner": contract}),
                encoding="utf-8",
            )
            manifest_path.write_text(json.dumps({"state": "pending_external"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "pending_external"}), encoding="utf-8")

            with patch.object(sys, "argv", ["run_queued_refresh_job.py", "--latest-manifest", str(latest_manifest_path)]), patch.object(
                module.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(args=["python"], returncode=0),
            ) as mocked_run:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_run.assert_called_once()
            called_command = mocked_run.call_args.args[0]
            self.assertIn(str(repo_root / "scripts" / "run_refresh_odds_job.py"), called_command)
            self.assertIn("--manifest-path", called_command)


if __name__ == "__main__":
    unittest.main()