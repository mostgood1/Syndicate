from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class RefreshOddsJobTests(unittest.TestCase):
    class _FakeProcess:
        def __init__(self, *, pid: int = 4321, stdout_text: str = "", stderr_text: str = "", returncode: int = 0):
            self.pid = pid
            self._stdout_text = stdout_text
            self._stderr_text = stderr_text
            self.returncode = returncode

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return self._stdout_text, self._stderr_text

    @staticmethod
    def _load_module(repo_root: Path):
        script_path = repo_root / "scripts" / "run_refresh_odds_job.py"
        spec = importlib.util.spec_from_file_location("test_run_refresh_odds_job", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_main_writes_terminal_job_status_artifact(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "manifest.json"
            latest_path = root / "latest.json"
            run_summary_path = root / "summary.json"
            status_path = root / "job_status.json"
            stdout_path = root / "stdout.txt"
            stderr_path = root / "stderr.txt"

            manifest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            latest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_refresh_odds_job.py",
                    "--manifest-path",
                    str(manifest_path),
                    "--latest-path",
                    str(latest_path),
                    "--run-summary-path",
                    str(run_summary_path),
                    "--status-path",
                    str(status_path),
                    "--stdout-path",
                    str(stdout_path),
                    "--stderr-path",
                    str(stderr_path),
                    "--",
                    sys.executable,
                    "-c",
                    "print('ok')",
                ],
            ), patch.object(
                module.subprocess,
                "Popen",
                return_value=self._FakeProcess(stdout_text="ok\n", stderr_text="", returncode=0),
            ), patch.object(module, "print") as mocked_print:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_payload["state"], "finished")
            self.assertEqual(status_payload["exitCode"], 0)
            self.assertIn("startedAt", status_payload)
            self.assertIn("finishedAt", status_payload)
            self.assertEqual(status_payload["manifestPath"], str(manifest_path))
            printed = " ".join(" ".join(str(part) for part in call.args) for call in mocked_print.call_args_list)
            self.assertIn("SNAPSHOT_WRITTEN", printed)
            self.assertIn("ODDS_REFRESH_SUCCESS", printed)

    def test_main_persists_stderr_tail_into_job_status(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "manifest.json"
            latest_path = root / "latest.json"
            run_summary_path = root / "summary.json"
            status_path = root / "job_status.json"
            stdout_path = root / "stdout.txt"
            stderr_path = root / "stderr.txt"

            manifest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            latest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")

            stderr_text = "line-" + "x" * 2200 + "-tail"
            with patch.object(
                sys,
                "argv",
                [
                    "run_refresh_odds_job.py",
                    "--manifest-path",
                    str(manifest_path),
                    "--latest-path",
                    str(latest_path),
                    "--run-summary-path",
                    str(run_summary_path),
                    "--status-path",
                    str(status_path),
                    "--stdout-path",
                    str(stdout_path),
                    "--stderr-path",
                    str(stderr_path),
                    "--",
                    sys.executable,
                    "-c",
                    "print('ok')",
                ],
            ), patch.object(
                module.subprocess,
                "Popen",
                return_value=self._FakeProcess(stdout_text="ok\n", stderr_text=stderr_text, returncode=0),
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertIn("stderrTail", status_payload)
            self.assertEqual(status_payload["stderrBufferLen"], len(stderr_text))
            self.assertEqual(status_payload["stderrTail"], stderr_text[-2000:])

    def test_main_queues_intelligence_refresh_after_success(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "manifest.json"
            latest_path = root / "latest.json"
            run_summary_path = root / "summary.json"
            status_path = root / "job_status.json"
            stdout_path = root / "stdout.txt"
            stderr_path = root / "stderr.txt"

            manifest_path.write_text(json.dumps({"state": "running", "date": "2026-07-06"}), encoding="utf-8")
            latest_path.write_text(json.dumps({"state": "running", "date": "2026-07-06"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "running", "date": "2026-07-06"}), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_refresh_odds_job.py",
                    "--manifest-path",
                    str(manifest_path),
                    "--latest-path",
                    str(latest_path),
                    "--run-summary-path",
                    str(run_summary_path),
                    "--status-path",
                    str(status_path),
                    "--stdout-path",
                    str(stdout_path),
                    "--stderr-path",
                    str(stderr_path),
                    "--",
                    sys.executable,
                    "-c",
                    "print('ok')",
                ],
            ), patch.object(
                module.subprocess,
                "Popen",
                return_value=self._FakeProcess(stdout_text="ok\n", stderr_text="", returncode=0),
            ), patch.object(
                module,
                "_queue_intelligence_snapshot_refresh",
                return_value=("queued-key", {"date": "2026-07-06", "force_refresh": True}),
            ) as mocked_queue, patch.object(module, "print") as mocked_print:
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            mocked_queue.assert_called_once()
            queued_args = mocked_queue.call_args.kwargs
            self.assertEqual(str(queued_args["run_summary_path"]), str(run_summary_path))
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_payload["state"], "finished")
            printed = " ".join(" ".join(str(part) for part in call.args) for call in mocked_print.call_args_list)
            self.assertIn("INTELLIGENCE_REFRESH_ENQUEUED", printed)

    def test_main_writes_failure_payload_when_command_cannot_start(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "manifest.json"
            latest_path = root / "latest.json"
            run_summary_path = root / "summary.json"
            status_path = root / "job_status.json"
            stdout_path = root / "stdout.txt"
            stderr_path = root / "stderr.txt"

            manifest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            latest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_refresh_odds_job.py",
                    "--manifest-path",
                    str(manifest_path),
                    "--latest-path",
                    str(latest_path),
                    "--run-summary-path",
                    str(run_summary_path),
                    "--status-path",
                    str(status_path),
                    "--stdout-path",
                    str(stdout_path),
                    "--stderr-path",
                    str(stderr_path),
                    "--",
                    sys.executable,
                    "-c",
                    "print('ok')",
                ],
            ), patch.object(module.subprocess, "Popen", side_effect=OSError("spawn failed")):
                exit_code = module.main()

            self.assertEqual(exit_code, 1)
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_payload["state"], "failed")
            self.assertEqual(status_payload["exitCode"], 1)
            stdout_payload = json.loads(stdout_path.read_text(encoding="utf-8"))
            self.assertFalse(stdout_payload["ok"])
            self.assertIn("spawn failed", stdout_payload["error"])
            self.assertIn("spawn failed", stderr_path.read_text(encoding="utf-8"))

    def test_main_writes_traceback_when_backend_guard_fails(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module = self._load_module(repo_root)

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / "manifest.json"
            latest_path = root / "latest.json"
            run_summary_path = root / "summary.json"
            status_path = root / "job_status.json"
            stdout_path = root / "stdout.txt"
            stderr_path = root / "stderr.txt"

            manifest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            latest_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                [
                    "run_refresh_odds_job.py",
                    "--manifest-path",
                    str(manifest_path),
                    "--latest-path",
                    str(latest_path),
                    "--run-summary-path",
                    str(run_summary_path),
                    "--status-path",
                    str(status_path),
                    "--stdout-path",
                    str(stdout_path),
                    "--stderr-path",
                    str(stderr_path),
                    "--",
                    sys.executable,
                    "-c",
                    "print('ok')",
                ],
            ), patch.object(
                module,
                "_refresh_state_store",
                return_value={
                    "assert_refresh_state_backend_ready": lambda **kwargs: (_ for _ in ()).throw(RuntimeError("guard failed")),
                    "read_json_file": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
                    "write_json_file": lambda path, payload: Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8"),
                    "write_text_file": lambda path, payload: Path(path).write_text(str(payload), encoding="utf-8"),
                },
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 1)
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_payload["state"], "failed")
            self.assertEqual(status_payload["exitCode"], 1)
            self.assertIn("guard failed", stdout_path.read_text(encoding="utf-8"))
            self.assertIn("guard failed", stderr_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()