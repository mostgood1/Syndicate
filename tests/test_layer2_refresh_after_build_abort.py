"""A heavy build refused MID-BUILD must still refresh the Layer 2 shortlist (lane `heavy-build-memory-refusal`).

MEASURED 2026-09-16 on refresh-worker: `LAYER2_SHORTLIST date=2026-09-16` was written at 22:03Z
and not again until 23:12Z, while builds were refused at `post_pull_hot_artifacts` and
`post_collect_candidates_with_fallback_merge`. The cheap refresh (`_refresh_layer2_shortlist_only`)
was only wired to the `pre_source_state_fingerprint` refusal, so a mid-build refusal left the
served combined board an hour old. These tests pin the mark, the trigger, and the wiring.
"""

from __future__ import annotations

import inspect
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pipeline.intelligence_state as ism
from pipeline.intelligence_state import IntelligenceStateService


class AbortedPoolMarkTests(unittest.TestCase):
    def test_aborted_pool_carries_the_stage_and_is_otherwise_the_empty_pool(self) -> None:
        pool = IntelligenceStateService._memory_guard_aborted_pool("2026-09-16", "fp", "post_pull_hot_artifacts")
        self.assertEqual(pool.pop("memory_guard_abort_stage"), "post_pull_hot_artifacts")
        self.assertEqual(pool, IntelligenceStateService._empty_candidate_pool("2026-09-16", "fp"))

    def test_an_honestly_empty_pool_is_not_marked(self) -> None:
        self.assertNotIn("memory_guard_abort_stage", IntelligenceStateService._empty_candidate_pool("2026-09-16", "fp"))


class RefreshTriggerTests(unittest.TestCase):
    def _run(self, pool):
        service = IntelligenceStateService()
        with patch.object(IntelligenceStateService, "_refresh_layer2_shortlist_only", return_value={"rows": []}) as fast:
            with redirect_stdout(io.StringIO()) as out:
                service._refresh_layer2_after_build_abort("2026-09-16", pool)
        return fast, out.getvalue()

    def test_a_marked_pool_runs_the_fast_refresh_for_that_date(self) -> None:
        fast, out = self._run(IntelligenceStateService._memory_guard_aborted_pool("2026-09-16", "fp", "post_collect_candidates_with_fallback_merge"))
        fast.assert_called_once_with("2026-09-16")
        self.assertIn("LAYER2_REFRESH_AFTER_BUILD_ABORT date=2026-09-16 stage=post_collect_candidates_with_fallback_merge ran=yes", out)

    def test_an_unmarked_pool_does_not(self) -> None:
        for pool in (IntelligenceStateService._empty_candidate_pool("2026-09-16", "fp"), {"candidate_count": 406}, None):
            fast, out = self._run(pool)
            fast.assert_not_called()
            self.assertEqual(out, "")

    def test_a_fast_path_that_declines_is_logged_as_not_run(self) -> None:
        service = IntelligenceStateService()
        pool = IntelligenceStateService._memory_guard_aborted_pool("2026-09-16", "fp", "post_pull_hot_artifacts")
        with patch.object(IntelligenceStateService, "_refresh_layer2_shortlist_only", return_value=None):
            with redirect_stdout(io.StringIO()) as out:
                service._refresh_layer2_after_build_abort("2026-09-16", pool)
        self.assertIn("ran=no", out.getvalue())


class BuildReachabilityTests(unittest.TestCase):
    def test_a_refused_pool_build_returns_the_marked_pool(self) -> None:
        # off != on: with the guard refusing at the first mid-build stage, the real
        # `_build_candidate_pool` must come back marked, or the trigger never fires.
        service = IntelligenceStateService()
        with patch.object(ism, "_abort_build_candidate_pool_if_memory_critical", side_effect=lambda stage: stage == "build_candidate_pool_start"), \
                patch.object(ism, "_release_freed_memory_to_os", return_value=None), \
                redirect_stdout(io.StringIO()):
            try:
                pool = service._build_candidate_pool("2026-09-16", "fp-reach")
            except Exception as exc:  # pragma: no cover - a guard/preamble change must be seen
                self.fail(f"_build_candidate_pool raised before its first guard: {type(exc).__name__}: {exc}")
        self.assertEqual(pool.get("memory_guard_abort_stage"), "build_candidate_pool_start")
        self.assertEqual(pool.get("candidate_count"), 0)

    def test_every_guard_return_in_the_pool_build_is_marked(self) -> None:
        body = inspect.getsource(IntelligenceStateService._build_candidate_pool)
        guards = body.count("_abort_build_candidate_pool_if_memory_critical(")
        self.assertGreaterEqual(guards, 6)
        self.assertEqual(body.count("self._memory_guard_aborted_pool("), guards)
        self.assertNotIn("return self._empty_candidate_pool(", body, "an unmarked abort return would skip the Layer 2 refresh")

    def test_both_pool_builds_for_the_requested_date_trigger_the_refresh(self) -> None:
        for fn in (IntelligenceStateService._compute_board_publication_response, IntelligenceStateService._compute_response):
            body = inspect.getsource(fn)
            build_at = body.find("_timed_candidate_pool(self._build_candidate_pool, selected_date, source_fingerprint)")
            self.assertGreater(build_at, 0, fn.__name__)
            next_line = body[build_at:].splitlines()[1].strip()
            self.assertEqual(next_line, "self._refresh_layer2_after_build_abort(selected_date, candidate_pool)", fn.__name__)


if __name__ == "__main__":
    unittest.main()
