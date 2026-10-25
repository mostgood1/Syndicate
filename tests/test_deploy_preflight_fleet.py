"""deploy_preflight on the FLEET `[2026-10-25, lane preflight-fleet-path]`.

Render is suspended (2026-09-30); a web preflight died on `/v1/logs` HTTP 503
on 2026-10-24. These pin the fleet path: every reading comes from the fleet,
no Render request is made, and an unreadable fleet is UNKNOWN, never CLEAR.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "deploy_preflight_fleet_under_test",
    Path(__file__).resolve().parents[1] / "scripts" / "deploy_preflight.py",
)
deploy_preflight = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = deploy_preflight
_spec.loader.exec_module(deploy_preflight)

STATUS_TEXT = """HEAD=b2cdb6ed6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
supervisor pid=523171 since 2026-10-25T15:15:35+00:00 state=redis
  web               pid=523186 up  rss=942 MB (cap 2048 MB)  restarts=0  code=b2cdb6ed
  refresh-worker    pid=1467610 up  rss=4246 MB (cap 6144 MB)  restarts=10  code=b2cdb6ed
  live-odds-worker  pid=1822371 DOWN  rss=? MB  restarts=7  code=5f32d9c4
  GET /healthz -> 200  {"ok":true}
"""


def _no_render(*_a, **_k):
    raise AssertionError("the fleet path must not call Render")


def _expectation_args():
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return ["--expect", "x=1", "--baseline", "x=0", "--baseline-read-at", stamp]


class ParseStatusTests(unittest.TestCase):
    def test_role_lines_parse_with_loaded_commit_and_state(self) -> None:
        rows = deploy_preflight.parse_fleet_status(STATUS_TEXT)
        self.assertEqual(rows["web"]["live_commit"], "b2cdb6ed")
        self.assertTrue(rows["refresh-worker"]["up"])
        self.assertEqual(rows["refresh-worker"]["restarts"], 10)
        self.assertFalse(rows["live-odds-worker"]["up"])
        self.assertEqual(rows["live-odds-worker"]["live_commit"], "5f32d9c4")

    def test_a_down_role_carries_an_error_in_the_fleet_block(self) -> None:
        rows = deploy_preflight.fleet_live_commits_from(deploy_preflight.parse_fleet_status(STATUS_TEXT))
        self.assertEqual(rows["web"]["live_commit"], "b2cdb6ed")
        self.assertEqual(rows["live-odds-worker"]["error"], "role DOWN")


class FleetVerdictTests(unittest.TestCase):
    def _run(self, service, *, jobs=(), worker_age_s=3600, ps_error=None, status_error=None,
             board=(False, {}), extra=()):
        status = deploy_preflight.parse_fleet_status(STATUS_TEXT)

        def fake_status():
            if status_error:
                raise RuntimeError(status_error)
            return "b2cdb6ed6" + "a" * 31, status

        def fake_processes(role, now):
            if ps_error:
                raise RuntimeError(ps_error)
            started = (now - timedelta(seconds=worker_age_s)).isoformat().replace("+00:00", "Z")
            return ([{"pid": 9000 + i, "ppid": 1, "rss_mb": None, "cmdline": ["python", name]}
                     for i, name in enumerate(jobs)],
                    {"worker_pid": 1, "worker_age_seconds": worker_age_s},
                    {"id": "fleet pid 1", "status": "live", "createdAt": started})

        captured = {}

        def fake_receipt(args, report, verdict, reason, live_commit):
            captured.update(report=report, verdict=verdict, reason=reason)

        out = io.StringIO()
        with mock.patch.object(deploy_preflight, "_api_key", side_effect=_no_render), \
             mock.patch.object(deploy_preflight, "_get", side_effect=_no_render), \
             mock.patch.object(deploy_preflight, "fleet_status", side_effect=fake_status), \
             mock.patch.object(deploy_preflight, "fleet_role_processes", side_effect=fake_processes), \
             mock.patch.object(deploy_preflight, "read_board_build_state", return_value=board) as board_read, \
             mock.patch.object(deploy_preflight, "is_ancestor", return_value=True), \
             mock.patch.object(deploy_preflight, "_write_receipt", side_effect=fake_receipt), \
             mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch.object(deploy_preflight.sys, "argv",
                               ["deploy_preflight.py", "--target", "fleet", "--service", service,
                                "--holder", "me", *_expectation_args(), *extra]), \
             mock.patch.dict(sys.modules,  # never the machine's real claim (see test_deploy_preflight._claim)
                             {"deploy_claim": types.SimpleNamespace(active_claim=lambda _service: None)}), \
             redirect_stdout(out):
            code = deploy_preflight.main()
        return code, captured, out.getvalue(), board_read

    def test_web_is_CLEAR_with_the_fleet_commit_and_no_render_call(self) -> None:
        code, got, text, _ = self._run("web")
        self.assertEqual(got["verdict"], "CLEAR", got["reason"])
        self.assertEqual(code, deploy_preflight.EXIT_CLEAR)
        self.assertEqual(got["report"]["platform"], "fleet")
        self.assertEqual(got["report"]["live_commit"], "b2cdb6ed")
        self.assertIn("reload-web", got["report"]["sample_source"])
        self.assertIn("FLEET", text)

    def test_a_worker_job_in_flight_HOLDs(self) -> None:
        code, got, _, _ = self._run("live-odds-worker", jobs=["run_refresh_odds_job.py"])
        self.assertEqual(got["verdict"], "HOLD")
        self.assertEqual(code, deploy_preflight.EXIT_HOLD)
        self.assertEqual(len(got["report"]["jobs_in_flight"]), 1)

    def test_an_unreadable_process_table_is_UNKNOWN_not_CLEAR(self) -> None:
        code, got, _, _ = self._run("live-odds-worker", ps_error="wsl tail rc=1")
        self.assertEqual(got["verdict"], "UNKNOWN")
        self.assertIn("wsl tail rc=1", got["reason"])

    def test_an_unreadable_status_leaves_web_UNKNOWN(self) -> None:
        code, got, _, _ = self._run("web", status_error="wsl not found")
        self.assertEqual(got["verdict"], "UNKNOWN")
        self.assertIn("wsl not found", got["reason"])

    def test_refresh_worker_reads_the_FLEET_board_build_and_holds_mid_build(self) -> None:
        code, got, _, board_read = self._run(
            "refresh-worker", board=(True, {"newest_build_start": "stage=portfolio_commit"}))
        board_read.assert_called_once_with(deploy_preflight.FLEET_BASE_URL)
        self.assertNotEqual(got["verdict"], "CLEAR")

    def test_spacing_is_measured_from_the_worker_process_start(self) -> None:
        code, got, _, _ = self._run("refresh-worker", worker_age_s=60)
        self.assertEqual(got["verdict"], "TOO_SOON", got["reason"])
        self.assertLess(got["report"]["last_deploy"]["age_seconds"], 120)

    def test_a_cron_service_on_the_fleet_is_UNKNOWN_with_the_reason(self) -> None:
        code, got, _, _ = self._run("ci-suite")
        self.assertEqual(got["verdict"], "UNKNOWN")
        self.assertIn("scheduled job", got["reason"])


if __name__ == "__main__":
    unittest.main()
