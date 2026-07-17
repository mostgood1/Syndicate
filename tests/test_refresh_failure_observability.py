"""Failure observability for the odds refresh pipeline.

Render launches run_refresh_odds_job.py with stdout/stderr DEVNULL'd, so the
only diagnostics that survive a failed cycle are (a) the child's emitted JSON
and (b) the job-status payload written through the shared refresh-state store.
These tests pin the pieces that make a worker-side failure diagnosable:
- refresh_odds_sources keeps a bounded stderr tail on FAILED steps,
- run_refresh_odds_job extracts a compact per-sport failure summary and keeps
  the child's full parsed result in the failure payload.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(script_name: str, module_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class CompactStepResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module("refresh_odds_sources.py", "test_obs_refresh_odds_sources")

    def test_failed_step_keeps_bounded_stderr_tail(self) -> None:
        step = {"name": "mlb_oddsapi_refresh", "ok": False, "return_code": 1, "stdout": "x" * 10, "stderr": "boom " * 1000}
        self.module._compact_step_result(step)
        self.assertEqual(step["stdout"], "")
        self.assertEqual(step["stderr"], "")
        self.assertLessEqual(len(step["stderr_tail"]), self.module._FAILED_STEP_STDERR_TAIL_CHARS)
        self.assertIn("boom", step["stderr_tail"])

    def test_successful_step_drops_streams_entirely(self) -> None:
        step = {"name": "mlb_oddsapi_refresh", "ok": True, "return_code": 0, "stdout": "big", "stderr": "noise"}
        self.module._compact_step_result(step)
        self.assertEqual(step["stdout"], "")
        self.assertEqual(step["stderr"], "")
        self.assertNotIn("stderr_tail", step)

    def test_compact_view_carries_stderr_tail_for_failed_steps(self) -> None:
        step = {"name": "s", "ok": False, "return_code": 1, "stderr_tail": "Traceback: ValueError"}
        view = self.module._compact_step_result_view(step)
        self.assertEqual(view["stderr_tail"], "Traceback: ValueError")
        ok_view = self.module._compact_step_result_view({"name": "s", "ok": True, "return_code": 0})
        self.assertNotIn("stderr_tail", ok_view)


class FailureSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module("run_refresh_odds_job.py", "test_obs_run_refresh_odds_job")

    def test_summary_extracts_failing_sport_step_and_post_refresh(self) -> None:
        payload = {
            "ok": False,
            "results": [
                {
                    "sport": "wnba",
                    "ok": True,
                    "refresh_steps": [{"name": "wnba_job", "ok": True, "return_code": 0}],
                },
                {
                    "sport": "mlb",
                    "ok": False,
                    "refresh_steps": [
                        {"name": "mlb_oddsapi_refresh", "ok": False, "return_code": 1, "stderr_tail": "OddsApiLiveFetchError: quota"}
                    ],
                    "generation": {"steps": [{"name": "mlb_oddsapi_refresh", "ok": False, "return_code": 1}]},
                    "post_refresh": {
                        "name": "mlb_post_refresh_tracking_sync",
                        "ok": False,
                        "dry_run": False,
                        "meta": {"ok": False, "error": "MemoryError: odds_history read"},
                    },
                },
            ],
        }
        summary = self.module._failure_summary_from_result(payload)
        self.assertEqual(len(summary), 1)
        entry = summary[0]
        self.assertEqual(entry["sport"], "mlb")
        self.assertEqual(len(entry["failing_steps"]), 1)  # deduped across refresh/generation groups
        self.assertEqual(entry["failing_steps"][0]["name"], "mlb_oddsapi_refresh")
        self.assertIn("OddsApiLiveFetchError", entry["failing_steps"][0]["stderr_tail"])
        self.assertIn("MemoryError", entry["post_refresh_error"])

    def test_summary_empty_for_success_or_malformed(self) -> None:
        self.assertEqual(self.module._failure_summary_from_result({"ok": True, "results": []}), [])
        self.assertEqual(self.module._failure_summary_from_result({}), [])
        self.assertEqual(self.module._failure_summary_from_result({"results": "nope"}), [])


if __name__ == "__main__":
    unittest.main()
