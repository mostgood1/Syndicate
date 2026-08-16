"""`#441` — the pbp fetch autorun, and the `#443` failure it must not inherit.

Two things are pinned here that are easy to get wrong and invisible in review:

1. **Producer before consumer.** The fetch must be dispatched BEFORE
   `_launch_autorun_season_projections`, because it fetches the only input those
   projections rate teams from. In an `elif` chain, order IS behaviour.

2. **No persisted PID guard.** `#443`: the sibling guard blocks on a stale pid
   after a restart and `continue`s with no log line, stalling a sport for up to
   45 minutes per deploy. This autorun rate-limits on a last-ATTEMPT marker
   instead, so there is no pid whose liveness can be misread.
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
    def test_pbp_fetch_is_dispatched_before_season_projections(self):
        """PRODUCER BEFORE CONSUMER. Order in the elif chain is the behaviour."""
        source = open(worker.__file__, encoding="utf-8").read()
        pbp_at = source.index("elif _launch_autorun_nfl_pbp_fetch(")
        proj_at = source.index("elif _launch_autorun_season_projections(")
        self.assertLess(
            pbp_at, proj_at,
            "the pbp fetch must be dispatched before the projections that consume it",
        )


class NoStalePidGuard(unittest.TestCase):
    def test_autorun_does_not_consult_a_persisted_pid(self):
        """`#443`: a pid-existence guard stalls silently after a restart.

        Asserted on the SOURCE of this function rather than behaviourally,
        because the defect being excluded is the PRESENCE of that pattern.
        """
        import inspect

        src = inspect.getsource(worker._launch_autorun_nfl_pbp_fetch)
        self.assertNotIn("_process_exists", src)
        self.assertNotIn("still_running", src)
        self.assertIn("attempted_at_epoch", src)


class RateLimiting(unittest.TestCase):
    def test_recent_attempt_suppresses_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 60})
        with patch.dict(__import__("os").environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl,mlb"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_pbp_fetch(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_stale_marker_allows_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(__import__("os").environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl,mlb"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_pbp_fetch(**_kwargs())
        self.assertTrue(launched)
        sp.Popen.assert_called_once()

    def test_marker_is_written_BEFORE_the_launch(self):
        """A crash must cost one interval, never a storm -- the `#441` failure."""
        order: list[str] = []
        store = _Store(None)
        store["write_json_file"] = lambda path, data: order.append("marker")
        with patch.dict(__import__("os").environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            sp.Popen.side_effect = lambda *a, **k: order.append("launch") or MagicMock(pid=1)
            worker._launch_autorun_nfl_pbp_fetch(**_kwargs())
        self.assertEqual(order, ["marker", "launch"])

    def test_unwritable_marker_refuses_rather_than_risking_a_storm(self):
        store = _Store(None)

        def _boom(path, data):
            raise OSError("read-only")

        store["write_json_file"] = _boom
        with patch.dict(__import__("os").environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_pbp_fetch(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()


class Gating(unittest.TestCase):
    def test_absent_flag_means_OFF_like_every_sibling_autorun(self):
        """THE DEFAULT I GOT WRONG FIRST, pinned so it cannot drift back.

        A default-ON autorun fires inside `test_main_run_once_*`, which invoke
        `main()` with a CLEARED environment and assert that a worker with
        nothing pending reports `state=idle / ranJob=False`. Default-on writes
        `state=launched / ranJob=True` and breaks that contract in three
        existing tests -- confirmed against a clean-HEAD worktree, where all
        three pass.
        """
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN", None)
            self.assertFalse(worker._nfl_pbp_fetch_enabled())

    def test_explicit_true_arms_it(self):
        import os
        with patch.dict(os.environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}):
            self.assertTrue(worker._nfl_pbp_fetch_enabled())

    def test_explicit_false_disables_it(self):
        import os
        with patch.dict(os.environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "false"}):
            self.assertFalse(worker._nfl_pbp_fetch_enabled())

    def test_out_of_season_nfl_is_skipped(self):
        store = _Store(None)
        with patch.dict(__import__("os").environ, {"NFL_PBP_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="mlb,soccer"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_pbp_fetch(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_interval_has_a_floor(self):
        """A tiny interval would hammer a public host."""
        with patch.dict("os.environ", {"NFL_PBP_FETCH_INTERVAL_SECONDS": "5"}):
            self.assertGreaterEqual(worker._nfl_pbp_fetch_interval_seconds(), 3600)


if __name__ == "__main__":
    unittest.main()
