"""#327. One implementation of the process-memory checkpoint, not two.

There used to be two functions named `_diag_log_all_process_memory`:
`pipeline/intelligence_state.py` logged AND persisted to the ring buffer behind
`/api/ops/intelligence/memory-diagnostics`; `scripts/run_refresh_worker.py`
only logged. Nothing at either call site showed the difference, so
`_diag_log_all_process_memory("post_mlb_sim_tick")` read as instrumented and
was not.

Measured cost, 2026-08-10 15:59-16:38Z: 172 pid-38 samples in the logs against
39 in the ring buffer, and the missing 77% carried the highest values --
`post_mlb_sim_tick` peaked at 1867.4MB where the visible stages topped out at
1044.1MB. The largest memory excursion on the service was invisible to the
instrument built to find memory excursions.

Deliberately a separate file from `tests/test_memory_observability.py`, which
another lane is actively editing.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared import memory_observability


class LogAndPersistTests(unittest.TestCase):
    def test_it_both_logs_and_persists(self) -> None:
        # The whole point: the persisting half is not optional or separate.
        with patch.object(memory_observability, "log_all_process_memory", return_value={"stage": "s"}) as logged, \
             patch.object(memory_observability, "dump_process_memory_checkpoint") as dumped:
            memory_observability.log_and_persist_process_memory("post_mlb_sim_tick")
        logged.assert_called_once_with("post_mlb_sim_tick")
        dumped.assert_called_once()
        self.assertEqual(dumped.call_args[0][0], "post_mlb_sim_tick")

    def test_a_persist_failure_never_propagates(self) -> None:
        # This runs inside the worker's tick loop and a background thread. A
        # diagnostic that can kill the thing it observes is worse than none.
        with patch.object(memory_observability, "log_all_process_memory", return_value={"stage": "s"}), \
             patch.object(memory_observability, "dump_process_memory_checkpoint", side_effect=RuntimeError("store down")):
            self.assertIsNone(memory_observability.log_and_persist_process_memory("post_mlb_sim_tick"))

    def test_a_log_failure_never_propagates(self) -> None:
        with patch.object(memory_observability, "log_all_process_memory", side_effect=RuntimeError("procfs gone")):
            self.assertIsNone(memory_observability.log_and_persist_process_memory("s"))


class RingBufferTests(unittest.TestCase):
    def test_it_trims_to_the_cap_keeping_the_NEWEST(self) -> None:
        written: dict = {}
        cap = memory_observability.PROCESS_MEMORY_CHECKPOINT_MAX_RECORDS
        existing = {"records": [{"stage": f"old{i}"} for i in range(cap + 40)]}
        with patch("syndicate.features.shared.refresh_state_store.read_json_file", return_value=existing), \
             patch("syndicate.features.shared.refresh_state_store.write_json_file",
                   side_effect=lambda path, payload: written.update(payload)), \
             patch.object(memory_observability, "process_memory_checkpoint_path", return_value="p"):
            memory_observability.dump_process_memory_checkpoint("newest", {"rss": 1})
        self.assertEqual(len(written["records"]), cap)
        self.assertEqual(written["records"][-1]["stage"], "newest", "the newest sample must survive the trim")

    def test_the_cap_is_sized_for_the_post_extraction_write_rate(self) -> None:
        # Measured before the extraction: 60 records at 1,233 bytes covered 36.1
        # minutes at intelligence_state's ~9 stages per cycle. Wiring the
        # worker's stages in multiplies the rate ~6x (26 live_lens_tick_* and 6
        # post_mlb_sim_tick per 5 min). At 60 the window would have collapsed to
        # ~6 minutes -- fixing the blind spot while destroying the history that
        # made it findable.
        self.assertGreaterEqual(memory_observability.PROCESS_MEMORY_CHECKPOINT_MAX_RECORDS, 300)


class OnlyOneImplementationTests(unittest.TestCase):
    """The structural property. If a second copy reappears, this fails."""

    def test_the_shims_delegate_rather_than_reimplement(self) -> None:
        import inspect

        import pipeline.intelligence_state as intelligence_state

        source = inspect.getsource(intelligence_state._diag_log_all_process_memory)
        self.assertIn("log_and_persist_process_memory", source)
        # A reimplementation would build the record itself.
        self.assertNotIn("records.append", source)

    def test_the_worker_uses_the_persisting_entry_point(self) -> None:
        from pathlib import Path

        source = Path(__file__).resolve().parents[1].joinpath("scripts", "run_refresh_worker.py").read_text(
            encoding="utf-8", errors="ignore"
        )
        self.assertIn("log_and_persist_process_memory", source)
        # The bare logger inside the diag helper is exactly the #327 bug.
        self.assertNotIn(
            "from syndicate.features.shared.memory_observability import log_all_process_memory",
            source,
            "the worker's diag helper must not fall back to the stderr-only logger",
        )

    def test_ops_can_still_import_the_path_helper_by_its_old_name(self) -> None:
        # syndicate/blueprints/ops.py imports this from intelligence_state by
        # name; the extraction must not break the endpoint.
        from pipeline.intelligence_state import _diag_memory_dump_path

        self.assertTrue(str(_diag_memory_dump_path()).endswith("memory_diagnostics.json"))


if __name__ == "__main__":
    unittest.main()
