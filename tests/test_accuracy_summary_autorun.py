"""The evaluation loop scores itself on a schedule — `#626`(h), Phase 0.

`build_accuracy_summary` (overall metrics, the segmented reliability surface,
win-rate/CLV drift) has existed since the learning-loop plan's Stage 5 with NO
scheduled caller — which is why every finding in the 2026-08-31 accuracy
assessments was made by a human running a CLI and none by the platform.

What these tests pin is the SAFETY of adding periodic work to this host, which
has an expensive history: `#241` caused a production restart loop and `#256`
was 110 OOM kills over eleven hours, caused by a status file written only at
the END of a self-catching-up job. So the gate must be off by default, the run
must be CLAIMED before the work, a previous run that died must not be retried
the same day, and what gets persisted must be bounded.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_worker():
    spec = importlib.util.spec_from_file_location(
        "run_refresh_worker_under_test", REPO_ROOT / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKER = _load_worker()


class AutorunIsOffByDefaultTests(unittest.TestCase):
    """This file's own convention for a NEW periodic job, and the reason is on
    the record: settlement ships absent = OFF so it can be verified against
    real production data before being trusted to run on a schedule."""

    def test_absent_means_off(self) -> None:
        with patch.dict(WORKER.os.environ, {}, clear=True):
            self.assertFalse(WORKER._accuracy_summary_auto_refresh_enabled())

    def test_it_can_be_armed(self) -> None:
        for value in ("1", "true", "yes", "on", "ON"):
            with patch.dict(WORKER.os.environ, {"ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN": value}, clear=True):
                self.assertTrue(WORKER._accuracy_summary_auto_refresh_enabled(), value)

    def test_a_disabled_gate_does_no_work_at_all(self) -> None:
        """Off must mean it never reads the ledger, not merely that it discards
        the result — the cost this guards is the read."""
        with patch.dict(WORKER.os.environ, {}, clear=True):
            with patch.object(WORKER, "_refresh_state_store") as store:
                fired = WORKER._launch_autorun_accuracy_summary(
                    latest_manifest_path=Path("x"), worker_status_path=Path("y"), refresh_cycle={}
                )
        self.assertFalse(fired)
        store.assert_not_called()


class DailyGateTests(unittest.TestCase):
    def _epoch_at(self, hour: int, day: int = 1) -> float:
        stamp = WORKER.central_datetime_from_epoch(time.time()).replace(
            year=2026, month=9, day=day, hour=hour, minute=0, second=0, microsecond=0
        )
        return stamp.timestamp()

    def test_it_waits_for_the_target_hour(self) -> None:
        with patch.dict(WORKER.os.environ, {}, clear=True):
            self.assertFalse(
                WORKER._accuracy_summary_should_run_now(now_epoch=self._epoch_at(5), last_epoch=0.0)
            )

    def test_it_runs_at_or_after_the_target_hour_when_never_run(self) -> None:
        with patch.dict(WORKER.os.environ, {}, clear=True):
            self.assertTrue(
                WORKER._accuracy_summary_should_run_now(now_epoch=self._epoch_at(8), last_epoch=0.0)
            )

    def test_it_runs_once_per_central_day(self) -> None:
        with patch.dict(WORKER.os.environ, {}, clear=True):
            morning = self._epoch_at(8)
            self.assertFalse(
                WORKER._accuracy_summary_should_run_now(now_epoch=self._epoch_at(20), last_epoch=morning)
            )
            self.assertTrue(
                WORKER._accuracy_summary_should_run_now(now_epoch=self._epoch_at(8, day=2), last_epoch=morning)
            )

    def test_it_runs_behind_settlement(self) -> None:
        """It scores what settlement writes, so scoring first would report a
        drift window one day stale every day."""
        with patch.dict(WORKER.os.environ, {}, clear=True):
            self.assertGreater(
                WORKER._accuracy_summary_target_hour_central(),
                WORKER._evaluation_settlement_target_hour_central(),
            )


class ClaimBeforeWorkTests(unittest.TestCase):
    """`#256`. A self-catching-up gate plus a status written only at the END is
    a crash loop: the process dies mid-pass, the epoch never advances, the next
    boot runs it again, forever."""

    def _run(self, *, last_status, summary_side_effect=None):
        writes: list[dict] = []
        store = {
            "read_json_file": lambda _path: dict(last_status),
            "write_json_file": lambda _path, payload: writes.append(payload),
            "reports_root": lambda: Path("reports"),
        }
        with patch.dict(WORKER.os.environ, {"ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN": "1"}, clear=True):
            with patch.object(WORKER, "_refresh_state_store", return_value=store):
                with patch.object(WORKER, "_accuracy_summary_should_run_now", return_value=True):
                    with patch(
                        "syndicate.features.shared.intelligence_evaluation.build_accuracy_summary",
                        side_effect=summary_side_effect
                        or (lambda **kwargs: {"sport": kwargs.get("sport"), "sample_size": 3, "settled_count": 1}),
                    ):
                        fired = WORKER._launch_autorun_accuracy_summary(
                            latest_manifest_path=Path("x"), worker_status_path=Path("y"), refresh_cycle={}
                        )
        return fired, writes

    def test_the_run_is_claimed_before_the_work(self) -> None:
        fired, writes = self._run(last_status={})
        self.assertTrue(fired)
        self.assertGreaterEqual(len(writes), 2, "one claim write, then one result write")
        self.assertEqual(writes[0].get("state"), "started", "the CLAIM must be written first")
        self.assertIn(writes[-1].get("state"), {"ok", "error"})

    def test_a_previous_run_that_died_is_reported_AND_the_message_matches_the_code(self) -> None:
        """This test used to assert only that the string was PRINTED, and it
        passed while the line said "Not retrying today" and the code retried on
        the very next statement. A log line that reports the opposite of the
        behaviour beneath it is worse than no line: a crash reads as a halt.

        So this pins the BEHAVIOUR too — the run proceeds and re-claims — and
        forbids the message that contradicts it."""
        with patch("builtins.print") as printer:
            fired, writes = self._run(last_status={"epoch": 1.0, "state": "started"})
        printed = " ".join(str(call.args[0]) for call in printer.call_args_list if call.args)
        self.assertIn("PREVIOUS_RUN_NEVER_COMPLETED", printed)

        self.assertTrue(fired, "a died-mid-pass previous run must NOT stop today's run")
        self.assertEqual(writes[0].get("state"), "started", "it must re-CLAIM before working")
        self.assertNotIn("not retrying", printed.lower(),
                         "the message must not claim a skip the code does not perform")

    def test_one_sport_failing_does_not_lose_the_others(self) -> None:
        calls = {"n": 0}

        def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {"sport": kwargs.get("sport"), "sample_size": 1, "settled_count": 0}

        _fired, writes = self._run(last_status={}, summary_side_effect=_flaky)
        sports = writes[-1].get("sports") or {}
        self.assertGreater(len(sports), 1)
        self.assertTrue(any("error" in (value or {}) for value in sports.values()))
        self.assertTrue(any("error" not in (value or {}) for value in sports.values()))

    def test_a_total_failure_still_writes_a_terminal_status(self) -> None:
        """Otherwise the claim stands forever and the job never runs again."""
        _fired, writes = self._run(last_status={}, summary_side_effect=ImportError("no module"))
        self.assertIn(writes[-1].get("state"), {"ok", "error"})
        self.assertNotEqual(writes[-1].get("state"), "started")


class BoundedPersistenceTests(unittest.TestCase):
    """The status store is keyvalue-backed with an 8MB ceiling per key, and the
    segmented surface grows with coverage — so it is precisely the field that
    would one day exceed it. Truncation must be visible, not silent."""

    def test_segments_are_capped_and_the_truncation_is_reported(self) -> None:
        summary = {
            "sport": "mlb",
            "generated_at": "now",
            "sample_size": 10,
            "settled_count": 4,
            "metrics": {"win_rate": 0.5},
            "drift": {},
            "segmented_reliability": {f"seg{i}": {"n": i} for i in range(120)},
        }
        bounded = WORKER._bounded_accuracy_summary(summary, max_segments=50)
        self.assertEqual(len(bounded["segmented_reliability"]), 50)
        self.assertEqual(bounded["segments_total"], 120)
        self.assertTrue(bounded["segments_truncated"])

    def test_a_small_surface_is_not_marked_truncated(self) -> None:
        bounded = WORKER._bounded_accuracy_summary(
            {"segmented_reliability": {"a": 1}, "sample_size": 1}, max_segments=50
        )
        self.assertFalse(bounded["segments_truncated"])
        self.assertEqual(bounded["segments_total"], 1)

    def test_the_headline_numbers_survive_bounding(self) -> None:
        """Truncation is of the SURFACE, never of the counts that say how much
        the summary rests on."""
        bounded = WORKER._bounded_accuracy_summary(
            {"sample_size": 19692, "settled_count": 35, "metrics": {"win_rate": 0.4}, "drift": {"win_rate": {}}}
        )
        self.assertEqual(bounded["sample_size"], 19692)
        self.assertEqual(bounded["settled_count"], 35)
        self.assertEqual(bounded["metrics"], {"win_rate": 0.4})


class WiredIntoTheTickChainTests(unittest.TestCase):
    """Presence is not reachability: a helper nothing calls is inert."""

    def test_the_autorun_is_called_from_the_tick_chain(self) -> None:
        source = (REPO_ROOT / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8-sig")
        self.assertIn("elif _launch_autorun_accuracy_summary(", source)

    def test_it_sits_behind_evaluation_settlement(self) -> None:
        source = (REPO_ROOT / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8-sig")
        self.assertLess(
            source.index("elif _launch_autorun_evaluation_settlement("),
            source.index("elif _launch_autorun_accuracy_summary("),
            "it scores what settlement writes, so it must not run ahead of it",
        )


class DeclineTelemetryTests(unittest.TestCase):
    """A decline that says nothing is indistinguishable from never running.

    Both returns here were SILENT and it cost a real investigation on
    2026-09-02: flag set, deploy injected, 100 minutes of nothing, and no way
    to tell "disabled" from "gate refused" from "never reached". The neighbour
    `_launch_autorun_reconciliation` had emitted `..._AUTORUN_GATED` since
    `#341` for exactly this reason; this job shipped without it.
    """

    def _printed(self, env: dict, last_status: dict) -> str:
        with patch.dict(os.environ, env, clear=False), patch("builtins.print") as printer:
            with patch.object(WORKER, "_refresh_state_store", return_value={
                "read_json_file": lambda _p: last_status,
                "write_json_file": lambda _p, _v: None,
                "reports_root": lambda: Path("."),
            }):
                WORKER._launch_autorun_accuracy_summary(
                    latest_manifest_path=Path("x"), worker_status_path=Path("y"), refresh_cycle={})
        return " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)

    def test_the_DISABLED_decline_names_the_env_var_and_the_deploy(self) -> None:
        env = {"ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN": ""}
        printed = self._printed(env, {})
        self.assertIn("ACCURACY_SUMMARY_AUTORUN_GATED", printed)
        self.assertIn("reason=disabled", printed)
        self.assertIn("ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN", printed,
                      "name the key, so the reader can act without reading source")
        self.assertIn("DEPLOY", printed,
                      "a Render env change does nothing until a deploy injects it")

    def test_a_silent_decline_is_impossible(self) -> None:
        """The regression. Either branch must emit SOMETHING."""
        self.assertTrue(self._printed({"ACCURACY_SUMMARY_ENABLE_REFRESH_WORKER_AUTORUN": ""}, {}).strip(),
                        "the disabled path must not be silent")


if __name__ == "__main__":
    unittest.main()
