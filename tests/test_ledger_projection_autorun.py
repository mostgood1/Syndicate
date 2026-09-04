"""The projected-ledger mirror's OWN cadence — `SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS`.

WHY THIS EXISTS AT ALL, separately from the daily accuracy autorun. The mirror
also runs from that autorun, but its gate is `last_run_date < today` — so on the
day the producer ships there is no way to exercise it, and the first proof would
be a day away. This knob decouples the transport from the product.

WHAT THESE TESTS PIN is the safety of adding periodic work to this host, which
has an expensive history: `#241` caused a production restart loop, and `#256`
was 110 OOM kills over eleven hours caused by a status written only at the END
of a self-catching-up job. So: OFF unless explicitly armed, CLAIMED before the
work, and never hot-looping after a death mid-pass.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_worker():
    spec = importlib.util.spec_from_file_location(
        "run_refresh_worker_projection_under_test", REPO_ROOT / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKER = _load_worker()


class IntervalGateTests(unittest.TestCase):
    def test_absent_means_off(self) -> None:
        with patch.dict(WORKER.os.environ, {}, clear=True):
            self.assertEqual(WORKER._ledger_projection_interval_seconds(), 0)

    def test_zero_means_off(self) -> None:
        with patch.dict(WORKER.os.environ, {"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "0"}, clear=True):
            self.assertEqual(WORKER._ledger_projection_interval_seconds(), 0)

    def test_garbage_means_off_rather_than_a_default_cadence(self) -> None:
        """An unparseable value must not silently become periodic work."""
        with patch.dict(WORKER.os.environ, {"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "hourly"}, clear=True):
            self.assertEqual(WORKER._ledger_projection_interval_seconds(), 0)

    def test_it_can_be_armed(self) -> None:
        with patch.dict(WORKER.os.environ, {"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"}, clear=True):
            self.assertEqual(WORKER._ledger_projection_interval_seconds(), 3600)


class RunGateTests(unittest.TestCase):
    def _run(self, *, env, last_status, side_effect=None):
        writes: list[dict] = []
        store = {
            "read_json_file": lambda _path: dict(last_status),
            "write_json_file": lambda _path, payload: writes.append(payload),
            "reports_root": lambda: Path("reports"),
        }
        calls: list[dict] = []

        def _projector(**kwargs):
            calls.append(kwargs)
            if side_effect is not None:
                raise side_effect
            return {"chunks_written": 3, "published": 3, "ratio": 0.05}

        with patch.dict(WORKER.os.environ, env, clear=True):
            with patch.object(WORKER, "_refresh_state_store", return_value=store):
                with patch(
                    "syndicate.features.shared.evaluation_ledger_projection.project_ledger_chunks",
                    side_effect=_projector,
                ):
                    fired = WORKER._launch_autorun_ledger_projection()
        return fired, writes, calls

    def test_disabled_does_no_work_at_all(self) -> None:
        fired, writes, calls = self._run(env={}, last_status={})
        self.assertFalse(fired)
        self.assertEqual(calls, [], "a disabled job must not touch the ledger")
        self.assertEqual(writes, [], "and must not write status either")

    def test_a_never_run_job_fires_immediately(self) -> None:
        """Waiting a full interval for a job that has never run is how the
        first proof ends up a day away -- the thing this knob exists to fix."""
        fired, _writes, calls = self._run(
            env={"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"}, last_status={}
        )
        self.assertTrue(fired)
        self.assertEqual(len(calls), 1)

    def test_it_waits_out_the_interval(self) -> None:
        fired, _writes, calls = self._run(
            env={"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"},
            last_status={"epoch": time.time() - 60},
        )
        self.assertFalse(fired)
        self.assertEqual(calls, [])

    def test_it_runs_once_the_interval_has_elapsed(self) -> None:
        fired, _writes, calls = self._run(
            env={"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"},
            last_status={"epoch": time.time() - 7200},
        )
        self.assertTrue(fired)
        self.assertEqual(len(calls), 1)

    def test_the_run_is_CLAIMED_before_the_work(self) -> None:
        """`#256`. The epoch must be written BEFORE the pass, so a process that
        dies inside it has still advanced the clock. A status written only at
        the end turns a job that kills the worker into a hot loop."""
        _fired, writes, _calls = self._run(
            env={"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"}, last_status={}
        )
        self.assertGreaterEqual(len(writes), 2, "expected a claim write and a terminal write")
        self.assertEqual(writes[0].get("state"), "started")
        self.assertGreater(float(writes[0].get("epoch") or 0), 0)

    def test_a_failing_pass_still_writes_a_terminal_status(self) -> None:
        _fired, writes, _calls = self._run(
            env={"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"},
            last_status={},
            side_effect=RuntimeError("disk full"),
        )
        terminal = writes[-1]
        self.assertEqual(terminal.get("state"), "error")
        self.assertIn("disk full", terminal.get("error") or "")

    def test_a_failing_pass_does_not_crash_the_tick(self) -> None:
        fired, _writes, _calls = self._run(
            env={"SYNDICATE_LEDGER_PROJECTION_INTERVAL_SECONDS": "3600"},
            last_status={},
            side_effect=RuntimeError("boom"),
        )
        self.assertTrue(fired, "it did work and must claim the tick, error or not")


class WiringTests(unittest.TestCase):
    def test_it_is_called_from_the_tick_chain(self) -> None:
        source = (REPO_ROOT / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
        self.assertIn("elif _launch_autorun_ledger_projection():", source)

    def test_it_sits_behind_the_accuracy_summary(self) -> None:
        """It mirrors the same ledger; the summary is the product and this is
        the transport, so the product wins the tick."""
        source = (REPO_ROOT / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("elif _launch_autorun_accuracy_summary("),
            source.index("elif _launch_autorun_ledger_projection():"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
