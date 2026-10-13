"""Cap-exempt autoruns (lane refresh-worker-odds-job-slot, 2026-10-13)."""

from __future__ import annotations

import importlib.util
import inspect
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location("rrw_slot", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py")
rrw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rrw)

_KW = {"latest_manifest_path": Path("m"), "worker_status_path": Path("s"), "refresh_cycle": {}}


class CapExempt(unittest.TestCase):
    def _patched(self, due: set[str], raising: set[str] = frozenset()):
        calls: list[str] = []

        def make(name):
            def fn(*_a, **_k):
                calls.append(name)
                if name in raising:
                    raise RuntimeError("boom")
                return name in due
            fn.__name__ = name
            return fn

        fakes = {name: make(name) for name in (
            "_launch_autorun_evaluation_settlement", "_launch_autorun_ledger_projection", "_launch_autorun_nfl_pbp_fetch",
            "_launch_autorun_nfl_injuries_fetch", "_launch_autorun_nfl_roster_snapshot", "_launch_autorun_nfl_depth_chart_snapshot",
            "_launch_autorun_nfl_news_capture", "_launch_autorun_nfl_game_injuries_fetch", "_launch_autorun_ncaaf_player_stats",
            "_launch_autorun_mlb_refresh", "_launch_autorun_weekly_sports_refresh")}
        return fakes, calls

    def _run(self, due, raising=frozenset()):
        fakes, calls = self._patched(due, raising)
        with mock.patch.multiple(rrw, **fakes):
            got = rrw._launch_cap_exempt_autorun(**_KW)
        return got, calls

    def test_settlement_launches_at_cap(self) -> None:
        got, calls = self._run({"_launch_autorun_evaluation_settlement"})
        self.assertEqual(got, "_launch_autorun_evaluation_settlement")
        self.assertEqual(calls, ["_launch_autorun_evaluation_settlement"])  # one per tick

    def test_nfl_fetch_launches_when_settlement_is_not_due(self) -> None:
        got, calls = self._run({"_launch_autorun_nfl_pbp_fetch"})
        self.assertEqual(got, "_launch_autorun_nfl_pbp_fetch")
        self.assertNotIn("_launch_autorun_nfl_injuries_fetch", calls)

    def test_odds_starting_refreshes_are_never_tried(self) -> None:
        got, calls = self._run(set())
        self.assertIsNone(got)
        self.assertNotIn("_launch_autorun_mlb_refresh", calls)
        self.assertNotIn("_launch_autorun_weekly_sports_refresh", calls)

    def test_one_failing_autorun_does_not_stop_the_rest(self) -> None:
        got, _calls = self._run({"_launch_autorun_nfl_pbp_fetch"}, raising={"_launch_autorun_evaluation_settlement"})
        self.assertEqual(got, "_launch_autorun_nfl_pbp_fetch")


class ThrottleBranchReachesIt(unittest.TestCase):
    def test_the_cap_branch_calls_the_exempt_launcher_after_run_once(self) -> None:
        src = inspect.getsource(rrw)
        cap = src.index("if active_jobs >= max_active_jobs:")
        nxt = src.index("elif _has_pending_external_contract(", cap)
        branch = src[cap:nxt]
        self.assertIn("_launch_cap_exempt_autorun(", branch)
        self.assertLess(branch.index("if args.run_once:"), branch.index("_launch_cap_exempt_autorun("))


if __name__ == "__main__":
    unittest.main()
