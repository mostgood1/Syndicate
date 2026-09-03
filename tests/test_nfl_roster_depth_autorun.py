"""`nfl-roster-depth-autorun` lane — the roster and depth-chart snapshot
autoruns.

Mirrors `test_nfl_injuries_fetch_autorun.py`'s shape exactly, because both
are deliberate structural copies of the pbp autorun's own contract (default-
OFF gating, last-ATTEMPT marker rate-limiting, no persisted PID guard, no
silent decline). Two things pinned here that are easy to get wrong and
invisible in review:

1. **Dispatched directly behind the injuries fetch, grouped together.**
   `#341`: an `elif` chain where only one branch fires per tick means a
   branch appended at the end can go mute for weeks even while correctly
   enabled. All three NFL ingestion autoruns (pbp, injuries, roster,
   depth-chart) are equally time-sensitive for the same sport.

2. **No persisted PID guard.** `#443`: rate-limits on a last-ATTEMPT marker
   instead of a pid, so there is no pid whose liveness can be misread.

3. **Independently armable.** A roster snapshot is useful before a depth
   chart exists, so the two gates are separate env vars, not one flag
   controlling both.
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import scripts.run_refresh_worker as worker


class _Store(dict):
    """Minimal stand-in for the refresh state store."""

    def __init__(self, payload=None):
        self.written = {}
        self.payload = payload
        super().__init__(
            read_json_file=lambda path: self.payload,
            write_json_file=lambda path, data: self.written.update({str(path): data}),
            reports_root=lambda: __import__("pathlib").Path("/tmp/reports"),
        )


def _kwargs():
    return {
        "latest_manifest_path": MagicMock(),
        "worker_status_path": MagicMock(),
        "refresh_cycle": {},
    }


class DispatchOrder(unittest.TestCase):
    def test_roster_and_depth_chart_sit_directly_behind_injuries(self):
        """`#341`: position in this elif chain is the behaviour."""
        source = open(worker.__file__, encoding="utf-8").read()
        order = [
            line.strip().removeprefix("elif ").removeprefix("if ").split("(")[0]
            for line in source.splitlines()
            if line.strip().startswith(("elif _launch_autorun", "if _launch_autorun"))
        ]
        for name in (
            "_launch_autorun_nfl_injuries_fetch",
            "_launch_autorun_nfl_roster_snapshot",
            "_launch_autorun_nfl_depth_chart_snapshot",
        ):
            self.assertIn(name, order)
        injuries_index = order.index("_launch_autorun_nfl_injuries_fetch")
        roster_index = order.index("_launch_autorun_nfl_roster_snapshot")
        depth_index = order.index("_launch_autorun_nfl_depth_chart_snapshot")
        self.assertEqual(roster_index, injuries_index + 1, f"order={order}")
        self.assertEqual(depth_index, roster_index + 1, f"order={order}")

    def test_both_sit_high_in_the_chain(self):
        """`#341`: not starved -- asserted against the branches that starve.

        THIS ASSERTED `roster_index <= 4` / `depth_index <= 5` AND WENT RED ON
        `main` `[fixed 2026-09-03]`. Nothing about the NFL block moved. The
        chain grew ahead of it: `_launch_autorun_accuracy_summary` was inserted
        at index 2 (`258d312f`, phase0 `#626(h)`), pushing roster 4 -> 5 and
        depth 5 -> 6.

        The literals were stale, not violated. `accuracy_summary` is daily-gated
        (`ACCURACY_SUMMARY_AUTORUN_GATED reason=daily_gate`, one tick per 24h),
        which is the same reason every branch above the NFL block is documented
        in `run_refresh_worker.py` as "safe this high". Starvation is about what
        wins ticks DURING A SLATE, and one tick a day is not it.

        So the bound is expressed against the branches that actually starve
        things, which is what `#341` measured and what the index was only ever a
        proxy for. `test_nfl_pbp_fetch_autorun.py` already had this loop and
        called it "strictly stronger" while keeping a literal alongside it that
        had been raised twice and was red on `main` for the same insertion;
        `test_nfl_injuries_fetch_autorun.py` and
        `test_nfl_fantasy_artifact_autorun.py` had already deleted theirs. The
        relative form does not go stale when the chain legitimately grows, and
        it is tighter: a literal permits these branches to sit behind
        `mlb_refresh` as long as the chain is long enough, this forbids it at
        any index.

        The TIER placement -- roster directly behind injuries, depth directly
        behind roster -- is not asserted here; it is
        `test_roster_and_depth_chart_sit_directly_behind_injuries` above, which
        is relative already and passed throughout.
        """
        source = open(worker.__file__, encoding="utf-8").read()
        order = [
            line.strip().removeprefix("elif ").removeprefix("if ").split("(")[0]
            for line in source.splitlines()
            if line.strip().startswith(("elif _launch_autorun", "if _launch_autorun"))
        ]
        roster_index = order.index("_launch_autorun_nfl_roster_snapshot")
        depth_index = order.index("_launch_autorun_nfl_depth_chart_snapshot")
        for name, index in (
            ("_launch_autorun_nfl_roster_snapshot", roster_index),
            ("_launch_autorun_nfl_depth_chart_snapshot", depth_index),
        ):
            for high_frequency in (
                "_launch_autorun_mlb_refresh",
                "_launch_autorun_weekly_sports_refresh",
                "_launch_autorun_soccer_weekly_refresh",
            ):
                self.assertIn(high_frequency, order)
                self.assertLess(
                    index, order.index(high_frequency),
                    f"{high_frequency} precedes {name}; an elif chain means "
                    f"{name} only runs on a tick where it declines, which is "
                    f"the starvation #341 measured. order={order}",
                )


class SilentDeclines(unittest.TestCase):
    def test_every_decline_path_logs_a_reason(self):
        import inspect

        for fn in (worker._launch_autorun_nfl_roster_snapshot, worker._launch_autorun_nfl_depth_chart_snapshot):
            src = inspect.getsource(fn)
            for reason in ("disabled", "not_in_season", "rate_limited"):
                self.assertIn(reason, src, f"{fn.__name__} missing reason {reason}")
            lines = src.splitlines()
            silent: list[str] = []
            for i, line in enumerate(lines):
                if line.strip() != "return False":
                    continue
                window = "\n".join(lines[max(0, i - 5):i])
                if "print(" not in window and "_skip(" not in window:
                    silent.append(f"{fn.__name__} line {i}: {line.strip()}")
            self.assertEqual(silent, [], f"silent decline path(s): {silent}")


class NoStalePidGuard(unittest.TestCase):
    def test_neither_autorun_consults_a_persisted_pid(self):
        import inspect

        for fn in (worker._launch_autorun_nfl_roster_snapshot, worker._launch_autorun_nfl_depth_chart_snapshot):
            src = inspect.getsource(fn)
            self.assertNotIn("_process_exists", src)
            self.assertNotIn("still_running", src)
            self.assertIn("attempted_at_epoch", src)


class RosterSnapshotGatingAndRateLimiting(unittest.TestCase):
    def test_absent_flag_means_OFF(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN", None)
            self.assertFalse(worker._nfl_roster_snapshot_enabled())

    def test_explicit_true_arms_it(self):
        import os
        with patch.dict(os.environ, {"NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}):
            self.assertTrue(worker._nfl_roster_snapshot_enabled())

    def test_out_of_season_nfl_is_skipped(self):
        store = _Store(None)
        with patch.dict(__import__("os").environ, {"NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="mlb,soccer"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_roster_snapshot(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_recent_attempt_suppresses_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 60})
        with patch.dict(__import__("os").environ, {"NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_roster_snapshot(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_stale_marker_allows_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(__import__("os").environ, {"NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_roster_snapshot(**_kwargs())
        self.assertTrue(launched)
        sp.Popen.assert_called_once()

    def test_marker_is_written_BEFORE_the_launch(self):
        order: list[str] = []
        store = _Store(None)
        store["write_json_file"] = lambda path, data: order.append("marker")
        with patch.dict(__import__("os").environ, {"NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            sp.Popen.side_effect = lambda *a, **k: order.append("launch") or MagicMock(pid=1)
            worker._launch_autorun_nfl_roster_snapshot(**_kwargs())
        self.assertEqual(order, ["marker", "launch"])

    def test_interval_has_a_floor(self):
        with patch.dict("os.environ", {"NFL_ROSTER_SNAPSHOT_INTERVAL_SECONDS": "5"}):
            self.assertGreaterEqual(worker._nfl_roster_snapshot_interval_seconds(), 3600)

    def test_default_interval_is_21600_seconds(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_ROSTER_SNAPSHOT_INTERVAL_SECONDS", None)
            self.assertEqual(worker._nfl_roster_snapshot_interval_seconds(), 21600)


class DepthChartSnapshotGatingAndRateLimiting(unittest.TestCase):
    def test_absent_flag_means_OFF(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN", None)
            self.assertFalse(worker._nfl_depth_chart_snapshot_enabled())

    def test_explicit_true_arms_it(self):
        import os
        with patch.dict(os.environ, {"NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}):
            self.assertTrue(worker._nfl_depth_chart_snapshot_enabled())

    def test_out_of_season_nfl_is_skipped(self):
        store = _Store(None)
        with patch.dict(__import__("os").environ, {"NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="mlb,soccer"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_depth_chart_snapshot(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_recent_attempt_suppresses_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 60})
        with patch.dict(__import__("os").environ, {"NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_depth_chart_snapshot(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_stale_marker_allows_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(__import__("os").environ, {"NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_depth_chart_snapshot(**_kwargs())
        self.assertTrue(launched)
        sp.Popen.assert_called_once()

    def test_marker_is_written_BEFORE_the_launch(self):
        order: list[str] = []
        store = _Store(None)
        store["write_json_file"] = lambda path, data: order.append("marker")
        with patch.dict(__import__("os").environ, {"NFL_DEPTH_CHART_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            sp.Popen.side_effect = lambda *a, **k: order.append("launch") or MagicMock(pid=1)
            worker._launch_autorun_nfl_depth_chart_snapshot(**_kwargs())
        self.assertEqual(order, ["marker", "launch"])

    def test_interval_has_a_floor(self):
        with patch.dict("os.environ", {"NFL_DEPTH_CHART_SNAPSHOT_INTERVAL_SECONDS": "5"}):
            self.assertGreaterEqual(worker._nfl_depth_chart_snapshot_interval_seconds(), 3600)

    def test_default_interval_is_21600_seconds(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_DEPTH_CHART_SNAPSHOT_INTERVAL_SECONDS", None)
            self.assertEqual(worker._nfl_depth_chart_snapshot_interval_seconds(), 21600)


class IndependentlyArmable(unittest.TestCase):
    def test_roster_can_launch_while_depth_chart_stays_off(self):
        store = _Store({"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(__import__("os").environ, {"NFL_ROSTER_SNAPSHOT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            roster_launched = worker._launch_autorun_nfl_roster_snapshot(**_kwargs())
            depth_launched = worker._launch_autorun_nfl_depth_chart_snapshot(**_kwargs())
        self.assertTrue(roster_launched)
        self.assertFalse(depth_launched)
        sp.Popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
