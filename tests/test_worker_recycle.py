"""refresh-worker self-restart when the heavy build is stuck refused (lane `heavy-build-memory-refusal`).

MEASURED 2026-09-12/13: `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` refused the
heavy build 403 times over ~16 h, while the main process held 2.1-2.4 GB after its first
build and no child jobs ran. Every stretch ended only on a process restart. These tests pin
the rules that make an automatic restart harmless, and that the two hooks are wired.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import worker_recycle as wr


def _refuse(n: int, stage: str = "pre_source_state_fingerprint") -> None:
    for _ in range(n):
        wr.note_heavy_build_refused(stage)


class RecycleDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        wr._reset_for_tests()
        wr._last_logged["key"] = None
        env = patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS", "SYNDICATE_REFRESH_WORKER_RECYCLE_MIN_UPTIME_SECONDS"):
            patch.dict("os.environ", {key: ""}).start()
        self.addCleanup(patch.stopall)

    def _decide(self, *, uptime=7200.0, children=(), draining=False):
        return wr.recycle_decision(
            uptime_seconds=uptime,
            parent_pid=39,
            children_fn=lambda pid: None if children is None else list(children),
            drain_active_fn=lambda: draining,
        )

    def test_default_is_on_at_fifteen(self) -> None:
        self.assertEqual(wr.recycle_after_refusals(), 15)
        self.assertEqual(wr.recycle_min_uptime_seconds(), 1800)

    def test_recycles_after_fifteen_consecutive_refusals_with_nothing_running(self) -> None:
        _refuse(15)
        recycle, reason, detail = self._decide()
        self.assertTrue(recycle)
        self.assertEqual(reason, "recycle")
        self.assertEqual(detail["consecutive_refusals"], 15)

    def test_fourteen_is_not_enough(self) -> None:
        _refuse(14)
        self.assertEqual(self._decide()[:2], (False, "below_threshold"))

    def test_a_completed_build_resets_the_count(self) -> None:
        _refuse(14)
        wr.note_heavy_build_completed()
        _refuse(14)
        self.assertEqual(wr.consecutive_refusals(), 14)
        self.assertEqual(self._decide()[:2], (False, "below_threshold"))

    def test_mid_build_refusals_reach_the_recycle(self) -> None:
        # 2026-09-16 22:23-22:55Z: every refusal was mid-build. Off != on: these
        # must be able to fire a recycle, and the detail must name the stage.
        _refuse(14, stage="post_pull_hot_artifacts")
        _refuse(1, stage="post_collect_candidates_with_fallback_merge")
        recycle, reason, detail = self._decide()
        self.assertEqual((recycle, reason), (True, "recycle"))
        self.assertEqual(detail["last_refusal_stage"], "post_collect_candidates_with_fallback_merge")

    def test_zero_disables(self) -> None:
        _refuse(100)
        with patch.dict("os.environ", {"SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS": "0"}):
            self.assertEqual(self._decide()[:2], (False, "disabled"))

    def test_junk_env_falls_back_to_default_not_off(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS": "banana"}):
            self.assertEqual(wr.recycle_after_refusals(), 15)

    def test_young_process_does_not_restart_loop(self) -> None:
        _refuse(50)
        self.assertEqual(self._decide(uptime=600.0)[:2], (False, "min_uptime"))

    def test_running_child_blocks_like_the_deploy_preflight(self) -> None:
        _refuse(50)
        recycle, reason, detail = self._decide(children=[4242])
        self.assertEqual((recycle, reason), (False, "children_running"))
        self.assertEqual(detail["children"], 1)

    def test_unknown_children_block(self) -> None:
        """UNKNOWN MUST NOT MEAN ZERO: an unreadable process table refuses."""
        _refuse(50)
        self.assertEqual(self._decide(children=None)[:2], (False, "children_unknown"))

    def test_deploy_drain_blocks(self) -> None:
        _refuse(50)
        self.assertEqual(self._decide(draining=True)[:2], (False, "drain_requested"))


class ChildProcessEnumerationTests(unittest.TestCase):
    def _proc(self, root: Path, pid: int, ppid: int, state: str = "S", comm: str = "python") -> None:
        d = root / str(pid)
        d.mkdir()
        (d / "stat").write_text(f"{pid} ({comm}) {state} {ppid} 1 1 0", encoding="utf-8")

    def test_counts_live_children_and_ignores_zombies_and_others(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._proc(root, 1, 0, comm="bash")
            self._proc(root, 39, 1)
            self._proc(root, 500, 39)
            self._proc(root, 501, 39, state="Z")
            self._proc(root, 502, 1)
            self._proc(root, 503, 39, comm="odd) name (x")
            self.assertEqual(sorted(wr.child_process_pids(39, proc_root=root)), [500, 503])

    def test_unreadable_table_is_none(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(wr.child_process_pids(39, proc_root=Path(tmp)))
            self.assertIsNone(wr.child_process_pids(39, proc_root=Path(tmp) / "missing"))


class MaybeRecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        wr._reset_for_tests()
        wr._last_logged["key"] = None
        patch.dict("os.environ", {"SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS": "", "SYNDICATE_REFRESH_WORKER_RECYCLE_MIN_UPTIME_SECONDS": ""}).start()
        self.addCleanup(patch.stopall)

    def _run(self, **kwargs):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = wr.maybe_recycle(parent_pid=39, uptime_seconds=7200.0, drain_active_fn=lambda: False, **kwargs)
        return result, buffer.getvalue()

    def test_exit_line_when_it_fires(self) -> None:
        _refuse(15)
        result, emitted = self._run(children_fn=lambda pid: [])
        self.assertTrue(result)
        self.assertIn("RECYCLE_EXIT reason=heavy_build_refused", emitted)

    def test_held_off_recycle_logs_once_per_change(self) -> None:
        _refuse(15)
        first = self._run(children_fn=lambda pid: [7])
        second = self._run(children_fn=lambda pid: [7])
        self.assertFalse(first[0])
        self.assertIn("RECYCLE_CHECK held=children_running", first[1])
        self.assertEqual(second[1], "", "the same held state was logged twice")

    def test_silent_below_threshold(self) -> None:
        _refuse(3)
        result, emitted = self._run(children_fn=lambda pid: [])
        self.assertFalse(result)
        self.assertEqual(emitted, "")


class HookWiringTests(unittest.TestCase):
    """The counter must be fed by the real guard site, and the main loop must ask."""

    def setUp(self) -> None:
        wr._reset_for_tests()

    def _publication(self, *, refused: bool):
        import pipeline.intelligence_state as ism
        from pipeline.intelligence_state import IntelligenceStateService

        service = IntelligenceStateService()
        patches = [
            # The LOWER seam, so the real `_abort_build_candidate_pool_if_memory_critical`
            # (which now feeds the counter) runs.
            patch.object(ism, "_abort_if_memory_critical", return_value=refused),
            patch.object(ism, "_diag_log_all_process_memory", return_value=None),
            patch.object(IntelligenceStateService, "_refresh_layer2_shortlist_only", return_value=None),
            # Past the guard the build would do real work: stop it at the first call.
            patch.object(IntelligenceStateService, "_source_state_fingerprint", side_effect=RuntimeError("stop-here")),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        try:
            with redirect_stdout(io.StringIO()):
                service._compute_board_publication_response({"date": "2026-09-13"})
        except RuntimeError as exc:
            if str(exc) != "stop-here":
                raise

    def test_refused_start_guard_increments_the_counter_once_per_cycle(self) -> None:
        self._publication(refused=True)
        self._publication(refused=True)
        self.assertEqual(wr.consecutive_refusals(), 2)

    def test_passing_the_start_guard_does_not_reset_the_counter(self) -> None:
        # 2026-09-16: builds passed this guard, then were refused mid-build; the old
        # reset-on-pass zeroed the count every cycle, so no recycle could fire.
        self._publication(refused=True)
        self._publication(refused=False)
        self.assertEqual(wr.consecutive_refusals(), 1)

    def test_every_heavy_build_guard_stage_feeds_the_counter(self) -> None:
        import pipeline.intelligence_state as ism

        stages = ("build_candidate_pool_start", "post_pull_hot_artifacts", "post_build_overview",
                  "post_collect_candidates_with_fallback_merge", "post_candidate_building", "manifest_loop_sport=mlb")
        with patch.object(ism, "_abort_if_memory_critical", return_value=True):
            for stage in stages:
                self.assertTrue(ism._abort_build_candidate_pool_if_memory_critical(stage))
        self.assertEqual(wr.consecutive_refusals(), len(stages))
        self.assertEqual(wr._last_refusal_stage(), "manifest_loop_sport=mlb")
        with patch.object(ism, "_abort_if_memory_critical", return_value=False):
            self.assertFalse(ism._abort_build_candidate_pool_if_memory_critical("post_pull_hot_artifacts"))
        self.assertEqual(wr.consecutive_refusals(), len(stages), "a passing guard must not reset or count")

    def test_every_guard_in_the_pool_build_goes_through_the_counting_wrapper(self) -> None:
        # A new guard written against `_abort_if_memory_critical` directly with the
        # 1,900 MB floor would be invisible to the recycle again.
        import inspect
        import pipeline.intelligence_state as ism

        body = inspect.getsource(ism.IntelligenceStateService._build_candidate_pool)
        self.assertNotIn("_abort_if_memory_critical(", body.replace("_abort_build_candidate_pool_if_memory_critical(", ""))
        self.assertGreaterEqual(body.count("_abort_build_candidate_pool_if_memory_critical("), 6)

    def test_the_reset_sits_at_the_pool_builds_normal_completion_only(self) -> None:
        import inspect
        import pipeline.intelligence_state as ism

        source = inspect.getsource(ism)
        self.assertEqual(source.count("note_heavy_build_completed()"), 1, "exactly one reset site")
        body = inspect.getsource(ism.IntelligenceStateService._build_candidate_pool)
        reset_at = body.find("note_heavy_build_completed()")
        self.assertGreater(reset_at, body.rfind("_abort_build_candidate_pool_if_memory_critical("))
        self.assertGreater(reset_at, body.rfind("_log_candidate_pool_cache("))
        self.assertIn("return json.loads(serialized_pool)", body[reset_at:])
        self.assertNotIn("note_heavy_build_guard", source, "the reset-on-pass hook must be gone")

    def test_main_loop_asks_maybe_recycle_before_sleeping(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
        sleep_at = source.rfind("time.sleep(poll_seconds)")
        ask_at = source.rfind("maybe_recycle(parent_pid=os.getpid())")
        self.assertGreater(ask_at, 0, "run_refresh_worker.py never calls maybe_recycle")
        self.assertLess(ask_at, sleep_at)
        self.assertIn("return 0", source[ask_at:sleep_at])


if __name__ == "__main__":
    unittest.main()
