"""`latest_tick.result` must not read "running" for an odds run that has exited.

The tick writes its `result` once, at tick end, as a LAUNCH-TIME snapshot
(state="running", pid). Measured 2026-10-02 on the local fleet: run
20261002_135535 ended `failed exitCode=1` 13 s after launch, while the served
tick said "running" for 11+ minutes. The run's own `refresh_job_status.json`
held the truth in the shared store all along; the endpoint now overlays it.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.live_refresh_loop import reconcile_tick_result


def _tick(state="running", artifacts_dir="/data/reports/migration_runs/2026-10-02/odds_refresh_20261002_135535"):
    return {
        "ok": True,
        "phase": "pregame",
        "startedAt": "2026-10-02T13:54:57Z",
        "finishedAt": "2026-10-02T08:55:35-05:00",
        "result": {"ok": True, "pid": 391685, "run_stamp": "20261002_135535", "lane": "live-odds-worker",
                   "state": state, "artifacts_dir": artifacts_dir},
    }


class ReconcileTickResultTests(unittest.TestCase):
    def _reader(self, payload):
        calls = []

        def read(path):
            calls.append(Path(path))
            if isinstance(payload, Exception):
                raise payload
            return payload

        return read, calls

    def test_terminal_status_overrides_launch_snapshot(self) -> None:
        read, calls = self._reader({"state": "failed", "exitCode": 1, "finishedAt": "2026-10-02T08:55:48-05:00"})
        tick = _tick()
        out = reconcile_tick_result(tick, read)
        self.assertEqual(out["result"]["state"], "failed")
        self.assertEqual(out["result"]["launchState"], "running")
        self.assertEqual(out["result"]["exitCode"], 1)
        self.assertEqual(out["result"]["finishedAt"], "2026-10-02T08:55:48-05:00")
        self.assertEqual(out["result"]["stateSource"], "refresh_job_status")
        self.assertEqual(out["result"]["pid"], 391685)
        self.assertEqual(calls, [Path(tick["result"]["artifacts_dir"]) / "refresh_job_status.json"])
        self.assertEqual(tick["result"]["state"], "running")  # input not mutated

    def test_finished_and_canceled_are_terminal(self) -> None:
        for terminal in ("finished", "canceled", "FINISHED"):
            read, _ = self._reader({"state": terminal})
            self.assertEqual(reconcile_tick_result(_tick(), read)["result"]["state"], terminal.lower())

    def test_still_running_or_unknown_status_leaves_snapshot(self) -> None:
        for payload in ({"state": "running"}, {"state": "queued"}, {}, None, "garbage", RuntimeError("store down")):
            read, _ = self._reader(payload)
            tick = _tick()
            self.assertIs(reconcile_tick_result(tick, read), tick, payload)

    def test_nothing_to_reconcile_never_reads(self) -> None:
        read, calls = self._reader({"state": "failed"})
        skipped = {"ok": False, "skipped": True, "phase": "pregame"}
        for tick in (None, {}, skipped, _tick(state="failed"), _tick(artifacts_dir="")):
            self.assertIs(reconcile_tick_result(tick, read), tick)
        self.assertEqual(calls, [])


class LiveRefreshStateEndpointTests(unittest.TestCase):
    """Reachability: the served endpoint, not just the helper."""

    def setUp(self) -> None:
        from syndicate.app import create_app

        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.reports_root = Path(self._tmp.name) / "reports"
        (self.reports_root / "live_refresh_loop").mkdir(parents=True, exist_ok=True)
        self.run_dir = self.reports_root / "migration_runs" / "2026-10-02" / "odds_refresh_20261002_135535"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._prior = {k: os.environ.get(k) for k in ("SYNDICATE_REPORTS_ROOT", "ADMIN_TOKEN")}
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(self.reports_root)
        os.environ["ADMIN_TOKEN"] = "test-token"
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for key, value in self._prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _write_tick(self, state: str = "running") -> None:
        tick = _tick(state=state, artifacts_dir=str(self.run_dir))
        (self.reports_root / "live_refresh_loop" / "latest_live_refresh_tick.json").write_text(
            json.dumps(tick), encoding="utf-8"
        )

    def _get_tick(self) -> dict:
        response = self.client.get("/api/ops/live-refresh/state", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["state"]["latest_tick"]

    def test_exited_run_is_served_with_its_terminal_state(self) -> None:
        self._write_tick()
        (self.run_dir / "refresh_job_status.json").write_text(
            json.dumps({"state": "failed", "exitCode": 1, "finishedAt": "2026-10-02T08:55:48-05:00"}), encoding="utf-8"
        )
        result = self._get_tick()["result"]
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["launchState"], "running")
        self.assertEqual(result["exitCode"], 1)

    def test_running_run_still_served_as_running(self) -> None:
        self._write_tick()
        (self.run_dir / "refresh_job_status.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")
        result = self._get_tick()["result"]
        self.assertEqual(result["state"], "running")
        self.assertNotIn("launchState", result)


if __name__ == "__main__":
    unittest.main()
