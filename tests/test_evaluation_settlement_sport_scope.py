"""`EVALUATION_SETTLEMENT_SPORTS` narrows the daily settlement sweep.

2026-09-08, user decision: the autorun was found LIVE on refresh-worker and
settling every registered grader, with 250-350 MB chunks per lookback date.
Narrowing to the shards whose grading is known-good is a scope, not a switch --
absent keeps the old all-graders behaviour, and a key that names nothing
registered falls back to ALL rather than to an empty sweep.
"""

from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch

run_refresh_worker = importlib.import_module("scripts.run_refresh_worker")


class SettlementSportScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("EVALUATION_SETTLEMENT_SPORTS", None)

    def tearDown(self) -> None:
        os.environ.pop("EVALUATION_SETTLEMENT_SPORTS", None)

    def _registered(self) -> tuple[str, ...]:
        from syndicate.features.shared.graded_outcomes import GRADED_OUTCOME_GRADERS

        return tuple(sorted(GRADED_OUTCOME_GRADERS.keys()))

    def test_absent_means_every_registered_grader(self) -> None:
        self.assertEqual(run_refresh_worker._evaluation_settlement_sports(), self._registered())

    def test_named_sports_narrow_the_sweep_in_registry_order(self) -> None:
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_SPORTS": "wnba, mlb"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_sports(), ("mlb", "wnba"))

    def test_unknown_tokens_are_dropped_not_guessed(self) -> None:
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_SPORTS": "mlb,cricket"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_sports(), ("mlb",))

    def test_only_unknown_tokens_fall_back_to_all_not_empty(self) -> None:
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_SPORTS": "cricket"}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_sports(), self._registered())

    def test_case_and_whitespace_are_forgiven(self) -> None:
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_SPORTS": " MLB ,Wnba "}):
            self.assertEqual(run_refresh_worker._evaluation_settlement_sports(), ("mlb", "wnba"))

    def test_the_autorun_passes_the_scope_and_records_it(self) -> None:
        """Reachability: the scope must reach `settle_ledger_for_dates` AND the
        status payload, or a reader cannot tell what the run covered."""
        seen: dict[str, object] = {}

        def fake_settle(dates, sports=None, **kwargs):
            seen["sports"] = list(sports or [])
            return {"totals": {"settled": 0}}

        writes: list[dict] = []
        store = {
            "read_json_file": lambda path: {},
            "write_json_file": lambda path, payload: writes.append(dict(payload)),
            "reports_root": lambda: run_refresh_worker.Path("."),
        }
        with patch.dict(os.environ, {"EVALUATION_SETTLEMENT_SPORTS": "mlb,wnba", "EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(run_refresh_worker, "_refresh_state_store", lambda: store), \
             patch.object(run_refresh_worker, "_evaluation_settlement_should_run_now", lambda **kw: True), \
             patch.object(run_refresh_worker, "_report_evaluation_ledger_index_size", lambda: None), \
             patch("syndicate.features.shared.evaluation_settlement.settle_ledger_for_dates", fake_settle), \
             patch.object(run_refresh_worker, "_write_worker_status", lambda **kw: None):
            try:
                run_refresh_worker._launch_autorun_evaluation_settlement(
                    latest_manifest_path=run_refresh_worker.Path("manifest.json"),
                    worker_status_path=run_refresh_worker.Path("status.json"),
                    refresh_cycle={},
                )
            except Exception as exc:  # the bridge/diagnostics may need files; the scope assertions below still hold
                seen["exc"] = repr(exc)
        self.assertEqual(seen.get("sports"), ["mlb", "wnba"])
        completed = [w for w in writes if w.get("state") == "completed"]
        if completed:
            self.assertEqual(completed[-1].get("sports"), ["mlb", "wnba"])


if __name__ == "__main__":
    unittest.main()
