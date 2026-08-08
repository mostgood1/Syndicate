"""Failure observability for the odds refresh pipeline.

The pieces that make a worker-side failure diagnosable:
- refresh_odds_sources keeps a bounded stderr tail on FAILED steps,
- run_refresh_odds_job extracts a compact per-sport failure summary and keeps
  the child's full parsed result in the failure payload.

The docstring here used to open "Render launches run_refresh_odds_job.py with
stdout/stderr DEVNULL'd". That is true of ops_refresh.py's detached launch and
NOT of the path production takes: refresh-worker's Render logs carry this
wrapper's own RETURN_CODE / SNAPSHOT_WRITTEN / LAUNCH_COMMAND lines (confirmed
2026-08-08 via the Render logs API). The belief that the channel was dead is
why the real defects below went unexamined for so long -- both of them are in
what gets written to a channel that works.
"""

from __future__ import annotations

import importlib.util
import json
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


# One PROCESS_TREE_MEMORY line as the child actually emits it. Measured on
# refresh-worker 2026-08-08T21:40:55Z at over 3,000 characters, because it
# embeds every process's full cmdline -- which is more than the 1600-char
# manifest budget can hold, so a raw tail could not fit even ONE of these.
_NOISE_LINE = 'PROCESS_TREE_MEMORY {"child_count": 0, "children": [], "self_rss_mb": 120.332, "pad": "' + ("x" * 3000) + '"}'

_REAL_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "/opt/render/project/src/scripts/build_soccer_artifacts.py", line 118, in main\n'
    "    raise SystemExit(f\"No fixtures for week {week}\")\n"
    "SystemExit: No fixtures for week 19"
)


class DiagnosticTailTests(unittest.TestCase):
    """The tail must carry the traceback, not the atexit memory dump.

    This is the defect that made seven days of failures unreadable: the signal
    was written, captured and echoed, and then windowed out by a [-N:] whose
    budget was smaller than one line of trailing noise.
    """

    def setUp(self) -> None:
        from syndicate.features.shared.refresh_log_tail import diagnostic_tail

        self.diagnostic_tail = diagnostic_tail

    def test_traceback_survives_a_trailing_memory_dump(self) -> None:
        stderr = "\n".join([_REAL_TRACEBACK, _NOISE_LINE, _NOISE_LINE, _NOISE_LINE])
        # The precondition, stated as a measurement rather than assumed: a raw
        # tail of this exact input contains no traceback at all.
        self.assertNotIn("SystemExit", stderr[-1600:])
        tail = self.diagnostic_tail(stderr, limit=1600)
        self.assertIn("SystemExit: No fixtures for week 19", tail)
        self.assertNotIn("PROCESS_TREE_MEMORY", tail)

    def test_the_budget_is_a_hard_bound(self) -> None:
        """It rides through the keyvalue store, which was at 194MB of 256MB."""
        for limit in (200, 1600, 4000):
            tail = self.diagnostic_tail("Traceback (most recent call last):\n" + ("e" * 50_000), limit=limit)
            self.assertLessEqual(len(tail), limit, limit)

    def test_the_exception_end_of_a_traceback_is_what_is_kept(self) -> None:
        """A traceback's most useful line is its LAST, so an over-long one must
        be truncated from the front, not the back."""
        long_frames = "\n".join(f'  File "f{i}.py", line {i}, in fn{i}' for i in range(400))
        stderr = f"Traceback (most recent call last):\n{long_frames}\nValueError: the actual cause"
        tail = self.diagnostic_tail(stderr, limit=400)
        self.assertIn("ValueError: the actual cause", tail)

    def test_unrecognised_lines_are_kept(self) -> None:
        """A filter that dropped unfamiliar output would be worse than the raw
        tail it replaces."""
        tail = self.diagnostic_tail("SOCCER_PLAYER_ROWS_MISSING league=championship\n" + _NOISE_LINE, limit=1600)
        self.assertIn("SOCCER_PLAYER_ROWS_MISSING", tail)

    def test_all_noise_falls_back_to_the_raw_tail(self) -> None:
        """Nothing to promote is not a reason to return nothing."""
        tail = self.diagnostic_tail("\n".join([_NOISE_LINE, _NOISE_LINE]), limit=300)
        self.assertTrue(tail.strip())
        self.assertLessEqual(len(tail), 300)

    def test_the_prefixed_and_bare_spellings_are_both_noise(self) -> None:
        stderr = "\n".join(
            [
                "RealError: keep me",
                "[refresh_odds_sources] RUNTIME_SNAPSHOT label=atexit ts=2026-08-08T21:40:55+00:00",
                "CHILD_PROCESS_EXIT ts=2026-08-08T21:40:55+00:00 pid=864",
            ]
        )
        tail = self.diagnostic_tail(stderr, limit=1600)
        self.assertIn("RealError: keep me", tail)
        self.assertNotIn("RUNTIME_SNAPSHOT", tail)
        self.assertNotIn("CHILD_PROCESS_EXIT", tail)

    def test_empty_and_malformed_input_never_raise(self) -> None:
        self.assertEqual(self.diagnostic_tail("", limit=100), "")
        self.assertEqual(self.diagnostic_tail(None, limit=100), "")
        self.assertEqual(self.diagnostic_tail("x", limit=0), "")


class ResultPayloadFromStdoutTests(unittest.TestCase):
    """The wrapper must find the child's JSON despite the lines printed before it.

    `json.loads(stdout_text)` failed on EVERY real run: refresh_odds_sources
    prints a serial_gate line plus one START and one END per step to stdout
    before its `--json` document. Reproduced locally 2026-08-08 on a one-sport
    dry run -- 264 characters of preamble, whole-stream parse raises, parse from
    the first brace succeeds.
    """

    def setUp(self) -> None:
        self.module = _load_module("run_refresh_odds_job.py", "test_obs_run_refresh_odds_job_stdout")

    def _stdout_as_the_child_writes_it(self, summary: dict) -> str:
        import json as _json

        return (
            "[refresh_odds_sources] serial_gate raw=None enabled=False selected=['soccer'] max_workers=1\n"
            "[refresh_odds_sources] START step=soccer_artifacts cwd=/opt/render/project/src\n"
            "[refresh_odds_sources] END step=soccer_artifacts return_code=1 timeout_seconds=1800\n"
        ) + _json.dumps(summary, indent=2)

    def test_the_real_stdout_shape_parses(self) -> None:
        summary = {"ok": False, "results": [{"sport": "soccer", "ok": False}]}
        raw = self._stdout_as_the_child_writes_it(summary)
        # State the precondition as a measurement, so this test still means
        # something if the child ever stops printing the preamble. Pinned to
        # JSONDecodeError specifically: assertRaises(Exception) here passes on a
        # NameError too, which is exactly how this assertion first went green
        # while asserting nothing.
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw)
        self.assertEqual(self.module._result_payload_from_stdout(raw), summary)

    def test_a_bare_json_document_still_parses(self) -> None:
        self.assertEqual(self.module._result_payload_from_stdout('{"ok": true}'), {"ok": True})

    def test_trailing_output_after_the_object_does_not_discard_it(self) -> None:
        raw = '{\n  "ok": true\n}\nCHILD_JSON_RETURN ts=2026-08-08T21:40:55Z\n'
        self.assertEqual(self.module._result_payload_from_stdout(raw), {"ok": True})

    def test_unparseable_stdout_returns_empty_rather_than_raising(self) -> None:
        self.assertEqual(self.module._result_payload_from_stdout("no json here at all"), {})
        self.assertEqual(self.module._result_payload_from_stdout(""), {})
        self.assertEqual(self.module._result_payload_from_stdout("   "), {})

    def test_a_failure_summary_is_now_reachable_end_to_end(self) -> None:
        """The whole point: this chain returned [] in production for seven days
        because the first link returned {}."""
        summary = {
            "ok": False,
            "results": [
                {
                    "sport": "soccer",
                    "ok": False,
                    "refresh_steps": [
                        {
                            "name": "soccer_artifacts_eredivisie",
                            "ok": False,
                            "return_code": 1,
                            "stderr_tail": "SystemExit: No fixtures for week 19",
                        }
                    ],
                }
            ],
        }
        parsed = self.module._result_payload_from_stdout(self._stdout_as_the_child_writes_it(summary))
        failures = self.module._failure_summary_from_result(parsed)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["sport"], "soccer")
        self.assertIn("SystemExit", failures[0]["failing_steps"][0]["stderr_tail"])


class StepFailMarkerTests(unittest.TestCase):
    """A non-zero return code must emit STEP_FAIL and must not claim status=ok.

    Seven days of refresh-worker logs held zero STEP_FAIL lines while the soccer
    refresh exited return_code=1 every ~45s, because STEP_FAIL was only wired to
    the TIMEOUT branch and the STEP_END line hardcoded status=ok.
    """

    def setUp(self) -> None:
        self.module = _load_module("refresh_odds_sources.py", "test_obs_refresh_odds_sources_stepfail")

    def _run_step_capturing_stderr(self, return_code: int) -> str:
        import io
        import types
        from contextlib import redirect_stderr

        step = types.SimpleNamespace(
            name="soccer_artifacts_eredivisie",
            description="soccer artifacts",
            cwd=REPO_ROOT,
            command=["python", "-c", "pass"],
            env_updates=None,
        )
        completed = types.SimpleNamespace(returncode=return_code, stdout="", stderr="boom")
        original_run = self.module.subprocess.run
        self.module.subprocess.run = lambda *a, **k: completed
        buffer = io.StringIO()
        try:
            with redirect_stderr(buffer):
                self.module._run_command(step)
        finally:
            self.module.subprocess.run = original_run
        return buffer.getvalue()

    def test_non_zero_return_code_emits_step_fail(self) -> None:
        stderr = self._run_step_capturing_stderr(1)
        self.assertIn("STEP_FAIL name=soccer_artifacts_eredivisie", stderr)
        self.assertIn("return_code=1", stderr)
        self.assertIn("STEP_END name=soccer_artifacts_eredivisie status=failed", stderr)
        self.assertNotIn("status=ok", stderr)

    def test_zero_return_code_is_unchanged(self) -> None:
        stderr = self._run_step_capturing_stderr(0)
        self.assertNotIn("STEP_FAIL", stderr)
        self.assertIn("STEP_END name=soccer_artifacts_eredivisie status=ok", stderr)


if __name__ == "__main__":
    unittest.main()
