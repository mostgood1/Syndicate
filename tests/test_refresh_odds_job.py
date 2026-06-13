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
                "run",
                return_value=subprocess.CompletedProcess(args=["python"], returncode=0, stdout="ok\n", stderr=""),
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status_payload["state"], "finished")
            self.assertEqual(status_payload["exitCode"], 0)
            self.assertIn("startedAt", status_payload)
            self.assertIn("finishedAt", status_payload)
            self.assertEqual(status_payload["manifestPath"], str(manifest_path))


if __name__ == "__main__":
    unittest.main()