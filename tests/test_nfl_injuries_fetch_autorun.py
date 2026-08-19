"""`nfl-injuries-fetcher` lane -- the injuries fetch autorun.

Mirrors `test_nfl_pbp_fetch_autorun.py` exactly, because this autorun is a
deliberate structural copy of that one (same gating/marker/no-pid-guard
contract, same `#341` starvation risk, same `#443` silent-decline risk).
Two things pinned here that are easy to get wrong and invisible in review:

1. **Dispatched directly behind the pbp fetch.** `#341`: an `elif` chain
   where only one branch fires per tick means a branch appended at the end
   can go mute for weeks even while correctly enabled. Injuries are exactly
   as time-sensitive as pbp for the same sport, so they get the same tier.

2. **No persisted PID guard.** `#443`: rate-limits on a last-ATTEMPT marker
   instead of a pid, so there is no pid whose liveness can be misread.
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
    def test_injuries_fetch_is_dispatched_directly_behind_pbp_fetch(self):
        """`#341`: position in this elif chain is the behaviour.

        Pinned to "directly behind pbp", not merely "somewhere before
        season_projections" -- the pbp branch's own comment records that a
        branch even one or two slots later than expected still starved for
        weeks during a busy slate.
        """
        source = open(worker.__file__, encoding="utf-8").read()
        order = [
            line.strip().removeprefix("elif ").removeprefix("if ").split("(")[0]
            for line in source.splitlines()
            if line.strip().startswith(("elif _launch_autorun", "if _launch_autorun"))
        ]
        self.assertIn("_launch_autorun_nfl_pbp_fetch", order)
        self.assertIn("_launch_autorun_nfl_injuries_fetch", order)
        pbp_index = order.index("_launch_autorun_nfl_pbp_fetch")
        injuries_index = order.index("_launch_autorun_nfl_injuries_fetch")
        self.assertEqual(
            injuries_index, pbp_index + 1,
            f"injuries fetch must sit directly behind the pbp fetch; order={order}",
        )

    def test_injuries_fetch_sits_high_in_the_chain(self):
        source = open(worker.__file__, encoding="utf-8").read()
        order = [
            line.strip().removeprefix("elif ").removeprefix("if ").split("(")[0]
            for line in source.splitlines()
            if line.strip().startswith(("elif _launch_autorun", "if _launch_autorun"))
        ]
        index = order.index("_launch_autorun_nfl_injuries_fetch")
        self.assertLessEqual(
            index, 2,
            f"injuries fetch must stay near the front of the chain; found at {index} in {order}",
        )


class SilentDeclines(unittest.TestCase):
    def test_every_decline_path_logs_a_reason(self):
        """`#443`: no decline may be silent."""
        import inspect

        src = inspect.getsource(worker._launch_autorun_nfl_injuries_fetch)
        for reason in ("disabled", "not_in_season", "rate_limited"):
            self.assertIn(reason, src)

        lines = src.splitlines()
        silent: list[str] = []
        for i, line in enumerate(lines):
            if line.strip() != "return False":
                continue
            window = "\n".join(lines[max(0, i - 5):i])
            if "print(" not in window and "_skip(" not in window:
                silent.append(f"line {i}: {line.strip()}")
        self.assertEqual(silent, [], f"silent decline path(s) reintroduced: {silent}")


class NoStalePidGuard(unittest.TestCase):
    def test_autorun_does_not_consult_a_persisted_pid(self):
        import inspect

        src = inspect.getsource(worker._launch_autorun_nfl_injuries_fetch)
        self.assertNotIn("_process_exists", src)
        self.assertNotIn("still_running", src)
        self.assertIn("attempted_at_epoch", src)


class RateLimiting(unittest.TestCase):
    def test_recent_attempt_suppresses_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 60})
        with patch.dict(__import__("os").environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl,mlb"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_injuries_fetch(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_stale_marker_allows_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(__import__("os").environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl,mlb"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_injuries_fetch(**_kwargs())
        self.assertTrue(launched)
        sp.Popen.assert_called_once()

    def test_marker_is_written_BEFORE_the_launch(self):
        """A crash must cost one interval, never a storm."""
        order: list[str] = []
        store = _Store(None)
        store["write_json_file"] = lambda path, data: order.append("marker")
        with patch.dict(__import__("os").environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            sp.Popen.side_effect = lambda *a, **k: order.append("launch") or MagicMock(pid=1)
            worker._launch_autorun_nfl_injuries_fetch(**_kwargs())
        self.assertEqual(order, ["marker", "launch"])

    def test_unwritable_marker_refuses_rather_than_risking_a_storm(self):
        store = _Store(None)

        def _boom(path, data):
            raise OSError("read-only")

        store["write_json_file"] = _boom
        with patch.dict(__import__("os").environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="nfl"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_injuries_fetch(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()


class Gating(unittest.TestCase):
    def test_absent_flag_means_OFF_like_every_sibling_autorun(self):
        """Same default-OFF contract the pbp autorun's own test pins.

        A default-ON autorun would fire inside `test_main_run_once_*`, which
        invoke `main()` with a CLEARED environment and assert that a worker
        with nothing pending reports `state=idle / ranJob=False`.
        """
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN", None)
            self.assertFalse(worker._nfl_injuries_fetch_enabled())

    def test_explicit_true_arms_it(self):
        import os
        with patch.dict(os.environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}):
            self.assertTrue(worker._nfl_injuries_fetch_enabled())

    def test_explicit_false_disables_it(self):
        import os
        with patch.dict(os.environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "false"}):
            self.assertFalse(worker._nfl_injuries_fetch_enabled())

    def test_out_of_season_nfl_is_skipped(self):
        store = _Store(None)
        with patch.dict(__import__("os").environ, {"NFL_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN": "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="mlb,soccer"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_nfl_injuries_fetch(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_interval_has_a_floor(self):
        """A tiny interval would hammer a public host."""
        with patch.dict("os.environ", {"NFL_INJURIES_FETCH_INTERVAL_SECONDS": "5"}):
            self.assertGreaterEqual(worker._nfl_injuries_fetch_interval_seconds(), 3600)

    def test_default_interval_is_21600_seconds(self):
        """The considered-guess default stated in the module comment -- pinned
        so a drive-by edit can't silently change the cadence."""
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_INJURIES_FETCH_INTERVAL_SECONDS", None)
            self.assertEqual(worker._nfl_injuries_fetch_interval_seconds(), 21600)


if __name__ == "__main__":
    unittest.main()
