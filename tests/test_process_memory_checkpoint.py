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



class HighWaterTests(unittest.TestCase):
    """#327. O(distinct stages), not O(samples) -- the reason this exists.

    The ring is a time series: instrumenting `live_lens_tick_*` (~6.6/min) would
    have taken 300 records from ~36 minutes to ~20-23, while the excursions
    being hunted arrive 11-42 minutes apart (measured, n=4). A high-water mark
    never rotates, so a once-per-75-minutes event cannot be lost.
    """

    def _harness(self):
        store: dict = {}
        writes: list = []

        def read(path):
            return store.get(str(path))

        def write(path, payload):
            writes.append(str(path))
            store[str(path)] = payload

        return store, writes, read, write

    def _run(self, samples, read, write):
        with patch("syndicate.features.shared.refresh_state_store.read_json_file", read), \
             patch("syndicate.features.shared.refresh_state_store.write_json_file", write), \
             patch.object(memory_observability, "process_memory_high_water_path", return_value="hw"):
            return [memory_observability.update_process_memory_high_water(s, p) for s, p in samples]

    def test_first_sample_always_records_so_absence_is_answerable(self) -> None:
        # "Is this stage reaching the instrument at all?" is the question #327
        # existed to ask and could not. A stage's first sample must always land.
        store, _, read, write = self._harness()
        self._run([("live_lens_tick_after_build_mlb", {"container_memory_mb": 100.0})], read, write)
        self.assertIn("live_lens_tick_after_build_mlb", store["hw"]["stages"])

    def test_steady_state_performs_no_write(self) -> None:
        # THE property that makes it affordable from a high-rate loop.
        store, writes, read, write = self._harness()
        results = self._run(
            [("s", {"container_memory_mb": v}) for v in (1923.9, 1500.0, 1600.0, 2709.9)], read, write
        )
        self.assertEqual(results, [True, False, False, True])
        self.assertEqual(len(writes), 2, "only genuine peaks may write")
        self.assertEqual(store["hw"]["stages"]["s"]["peak_mb"], 2709.9)

    def test_it_ranks_by_container_memory_not_process_rss(self) -> None:
        # The two diverged by ~800MB during the #327 excursion, and the cgroup
        # figure is the one the OOM killer acts on.
        self.assertEqual(
            memory_observability._high_water_metric({"container_memory_mb": 2709.9, "accounted_rss_mb": 1896.4}),
            2709.9,
        )
        self.assertEqual(memory_observability._high_water_metric({"accounted_rss_mb": 1896.4}), 1896.4)
        self.assertIsNone(memory_observability._high_water_metric({"stage": "s"}))

    def test_stage_cardinality_is_bounded_and_drops_the_least_interesting(self) -> None:
        store, _, read, write = self._harness()
        cap = memory_observability.PROCESS_MEMORY_HIGH_WATER_MAX_STAGES
        self._run([(f"stage{i}", {"container_memory_mb": 100.0 + i}) for i in range(cap)], read, write)
        self._run([("a_big_one", {"container_memory_mb": 9999.0})], read, write)
        stages = store["hw"]["stages"]
        self.assertLessEqual(len(stages), cap)
        self.assertIn("a_big_one", stages)
        self.assertNotIn("stage0", stages, "the lowest peak is the one to drop")

    def test_append_to_ring_false_still_records_the_high_water(self) -> None:
        # How live_lens_tick_* becomes visible without rotating the ring.
        with patch.object(memory_observability, "log_all_process_memory", return_value={"container_memory_mb": 2296.9}), \
             patch.object(memory_observability, "dump_process_memory_checkpoint") as ring, \
             patch.object(memory_observability, "update_process_memory_high_water") as hw:
            memory_observability.log_and_persist_process_memory(
                "live_lens_tick_after_build_mlb", append_to_ring=False, sport="mlb"
            )
        ring.assert_not_called()
        hw.assert_called_once()

    def test_extra_kwargs_reach_the_logger(self) -> None:
        # live_lens passes sport=/date=/ok=; dropping them would silently lose
        # the fields that make a stage interpretable.
        with patch.object(memory_observability, "log_all_process_memory", return_value={}) as logged, \
             patch.object(memory_observability, "update_process_memory_high_water"):
            memory_observability.log_and_persist_process_memory("s", append_to_ring=False, sport="mlb", ok=True)
        self.assertEqual(logged.call_args.kwargs, {"sport": "mlb", "ok": True})

    def test_live_lens_loop_uses_the_persisting_entry_point(self) -> None:
        # The third emitter. Structural: fails if it reverts to stderr-only.
        from pathlib import Path

        source = Path(__file__).resolve().parents[1].joinpath(
            "syndicate", "features", "shared", "live_lens_loop.py"
        ).read_text(encoding="utf-8", errors="ignore")
        self.assertEqual(source.count("log_and_persist_process_memory(f\"live_lens_tick"), 3)
        self.assertNotIn("log_all_process_memory(f\"live_lens_tick", source)
if __name__ == "__main__":
    unittest.main()
