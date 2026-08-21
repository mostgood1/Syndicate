"""The NFL fantasy projection autorun, and the four failures it must not inherit.

Each of these is a defect this repo has already paid for once, in another
autorun, and none of them is visible in review:

1. **`#443` — a decline with no log line.** Every refusal must say why, or a
   silent autorun is indistinguishable between "flag off", "rate limited" and
   "never reached".
2. **`#341` — `elif` starvation.** Every branch in the dispatch chain is
   `elif`, so a late entry only runs on a tick where all earlier ones decline.
   Reconciliation was mute for WEEKS that way. Order IS behaviour, so it is
   pinned here.
3. **`#241` — periodic work is never free.** This build peaks at ~725MB
   (measured 2026-08-21), so it must be launched as a SUBPROCESS rather than
   run inline on a 4GB worker that also runs MLB sims.
4. **A marker written after the launch** would relaunch on every tick if a run
   died. It goes in first.
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
            write_json_file=lambda path, value: self.written.__setitem__(str(path), value),
            reports_root=lambda: __import__("pathlib").Path("/tmp/reports"),
        )


def _launch(**env):
    kwargs = dict(
        latest_manifest_path=__import__("pathlib").Path("/tmp/manifest.json"),
        worker_status_path=__import__("pathlib").Path("/tmp/status.json"),
        refresh_cycle={},
    )
    return worker._launch_autorun_nfl_fantasy_artifact(**kwargs)


class FantasyArtifactAutorunTests(unittest.TestCase):
    def setUp(self):
        worker._NFL_FANTASY_SKIP_LOG_AT.clear()

    def test_absent_flag_means_off(self):
        """Absent must not read as enabled. `CLAUDE.md`: absent is not off by
        default anywhere -- you check the code's default."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("NFL_FANTASY_ARTIFACT_ENABLE_REFRESH_WORKER_AUTORUN", None)
            self.assertFalse(worker._nfl_fantasy_artifact_enabled())

    def test_every_decline_says_why(self):
        """`#443`. A guard that returns False silently is the defect."""
        import os

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("NFL_FANTASY_ARTIFACT_ENABLE_REFRESH_WORKER_AUTORUN", None)
            with patch("builtins.print") as printed:
                self.assertFalse(_launch())
            said = " ".join(str(call) for call in printed.call_args_list)
            self.assertIn("NFL_FANTASY_ARTIFACT_SKIPPED", said)
            self.assertIn("disabled", said)

    def test_launches_as_a_subprocess_and_writes_the_marker_first(self):
        """`#241`: inline would put a ~725MB build in the poll loop's own RSS.
        And the marker must precede the launch, or a run that dies relaunches
        every tick."""
        store = _Store(payload=None)
        order = []
        store["write_json_file"] = lambda path, value: order.append("marker")

        with patch.dict(
            "os.environ", {"NFL_FANTASY_ARTIFACT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}
        ), patch.object(worker, "_refresh_state_store", lambda: store), patch.object(
            worker.subprocess, "Popen", MagicMock(side_effect=lambda *a, **k: order.append("launch"))
        ) as popen:
            self.assertTrue(_launch())

        popen.assert_called_once()
        self.assertEqual(order, ["marker", "launch"], "marker must be written BEFORE the launch")

    def test_rate_limited_by_a_fresh_marker(self):
        store = _Store(payload={"attempted_at_epoch": time.time()})
        with patch.dict(
            "os.environ", {"NFL_FANTASY_ARTIFACT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}
        ), patch.object(worker, "_refresh_state_store", lambda: store), patch.object(
            worker.subprocess, "Popen", MagicMock()
        ) as popen, patch("builtins.print") as printed:
            self.assertFalse(_launch())
        popen.assert_not_called()
        self.assertIn("rate_limited", " ".join(str(c) for c in printed.call_args_list))

    def test_a_stale_marker_allows_another_run(self):
        store = _Store(payload={"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(
            "os.environ", {"NFL_FANTASY_ARTIFACT_ENABLE_REFRESH_WORKER_AUTORUN": "true"}
        ), patch.object(worker, "_refresh_state_store", lambda: store), patch.object(
            worker.subprocess, "Popen", MagicMock()
        ) as popen:
            self.assertTrue(_launch())
        popen.assert_called_once()

    def test_interval_defaults_daily_and_has_a_floor(self):
        import os

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("NFL_FANTASY_ARTIFACT_INTERVAL_SECONDS", None)
            self.assertEqual(worker._nfl_fantasy_artifact_interval_seconds(), 86400)
        with patch.dict("os.environ", {"NFL_FANTASY_ARTIFACT_INTERVAL_SECONDS": "5"}):
            self.assertEqual(worker._nfl_fantasy_artifact_interval_seconds(), 3600)

    def test_season_is_the_surfaces_own_default_not_the_calendar_year(self):
        """The NFL season is named for the year it STARTS, so from January to
        summer the calendar year is the season just finished. Projecting that
        would rebuild a settled past."""
        from syndicate.features.nfl.fantasy import DEFAULT_FANTASY_SEASON

        self.assertEqual(worker._nfl_fantasy_artifact_season(), DEFAULT_FANTASY_SEASON)

    def test_script_args_prepare_and_publish_every_week(self):
        args = worker._nfl_fantasy_artifact_script_args(2026)
        self.assertIn("build_nfl_fantasy_projection_artifact.py", " ".join(args))
        self.assertIn("--prepare", args)
        self.assertIn("--publish", args)
        self.assertIn("1-18", args)
        self.assertIn("2026", args)

    def test_dispatched_IMMEDIATELY_after_the_pbp_fetch(self):
        """`#341`: in an `elif` chain, ORDER IS BEHAVIOUR -- and a relative
        assertion is not enough to pin it.

        The first version of this test only checked
        `pbp < fantasy < season_projections`. That PASSED while the branch was
        actually TENTH, below evaluation_settlement, because the patch that
        added it anchored on `season_projections` and inserted above that. The
        code comment said "THIRD" the whole time. Twelve minutes after the
        deploy it had logged nothing at all -- not even a SKIPPED line.

        So this asserts the ADJACENCY, not the ordering: nothing may sit
        between the pbp fetch and this job.
        """
        import inspect
        import re

        source = inspect.getsource(worker)
        branches = re.findall(r"^\s+(?:if|elif) (_launch_autorun_\w+)\(", source, re.M)
        self.assertIn("_launch_autorun_nfl_fantasy_artifact", branches)
        position = branches.index("_launch_autorun_nfl_fantasy_artifact")
        self.assertEqual(
            branches[position - 1],
            "_launch_autorun_nfl_pbp_fetch",
            f"must sit directly behind the pbp fetch it consumes; chain is {branches[:6]}",
        )
        self.assertLessEqual(
            position, 3, f"too deep in the elif chain to be reached reliably: {branches[:6]}"
        )


if __name__ == "__main__":
    unittest.main()
