from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.run_orchestrator_worker as orchestrator_worker


class _FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.pid = 12345

    def communicate(self, timeout: float | None = None):
        return self._stdout, self._stderr

    def poll(self):
        return self.returncode

    def wait(self, timeout: float | None = None):
        return self.returncode

    def kill(self):
        return None


class OrchestratorWorkerTests(unittest.TestCase):
    def test_run_script_reports_child_failure_output(self) -> None:
        fake_process = _FakeProcess(returncode=1, stdout="child stdout", stderr="child stderr")
        with patch("scripts.run_orchestrator_worker.subprocess.Popen", return_value=fake_process) as mocked_popen:
            with patch("scripts.run_orchestrator_worker.print") as mocked_print:
                orchestrator_worker._run_script("run_intelligence_state_worker.py")

        mocked_popen.assert_called_once()
        printed_text = "\n".join(str(call.args[0]) for call in mocked_print.call_args_list if call.args)
        self.assertIn("run_intelligence_state_worker.py EXITED 1", printed_text)
        self.assertIn("run_intelligence_state_worker.py STDOUT:", printed_text)
        self.assertIn("child stdout", printed_text)
        self.assertIn("run_intelligence_state_worker.py STDERR:", printed_text)
        self.assertIn("child stderr", printed_text)


if __name__ == "__main__":
    unittest.main()
