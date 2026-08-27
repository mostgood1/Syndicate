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
        # ADJACENCY TO THE PRODUCER BLOCK, not to the pbp fetch alone.
        #
        # The docstring above is right that a bare `pbp < fantasy <
        # season_projections` is too weak -- it passed while this branch sat
        # TENTH and logged nothing for twelve minutes after a deploy. That
        # protection is kept in full here: nothing may sit between the pbp fetch
        # and this job EXCEPT the jobs that produce what it reads.
        #
        # What changed on 2026-08-25 is which slot it holds. This asserted
        # `branches[position - 1] == "_launch_autorun_nfl_pbp_fetch"`, i.e. the
        # pbp+1 slot -- the same slot `test_nfl_injuries_fetch_autorun` asserts
        # for the INJURIES fetch. Both could not pass. The tiebreak is not a
        # preference: this artifact CONSUMES injuries and news
        # (`use_injury_availability`, and the news layer), so running it above
        # them fed it yesterday's data. Producer before consumer, which is the
        # rule the pbp branch's own comment already cites.
        #
        # Starvation is not reopened by the move: every branch now between pbp
        # and this one is daily or six-hourly gated, so the NFL block as a whole
        # needs ~6 winning ticks a day out of ~2,880. `#341`'s starvation came
        # from sitting below HIGH-FREQUENCY branches, which is still forbidden by
        # the window assertion below.
        producers = {
            "_launch_autorun_nfl_pbp_fetch",
            "_launch_autorun_nfl_injuries_fetch",
            "_launch_autorun_nfl_roster_snapshot",
            "_launch_autorun_nfl_depth_chart_snapshot",
            "_launch_autorun_nfl_news_capture",
        }
        pbp_position = branches.index("_launch_autorun_nfl_pbp_fetch")
        window = branches[pbp_position:position]
        intruders = [name for name in window if name not in producers]
        self.assertEqual(
            intruders, [],
            f"only the jobs this artifact consumes may sit between the pbp fetch "
            f"and it; found {intruders} in {branches[:9]}",
        )
        self.assertLess(
            branches.index("_launch_autorun_nfl_injuries_fetch"), position,
            f"must run behind the injuries fetch it consumes; chain is {branches[:9]}",
        )
        self.assertLess(
            branches.index("_launch_autorun_nfl_news_capture"), position,
            f"must run behind the news capture it consumes; chain is {branches[:9]}",
        )
        # RELATIVE DEPTH, not absolute. This asserted `position <= 3`, a literal
        # index from when the NFL block was three branches long. The concern it
        # encodes -- "deep enough down that it never gets reached" -- is about
        # what sits ABOVE it, not about the number itself, and the window check
        # above already forbids anything above it that is not a producer.
        #
        # So the bound is expressed against the producer block: this job must sit
        # immediately after the last of the jobs it consumes, with nothing else
        # in between. That is exactly as tight as the old literal against the
        # failure it was written for (an unrelated branch inserted higher), and
        # it does not go stale when the producer block legitimately grows.
        self.assertEqual(
            position, pbp_position + len(window),
            f"must sit immediately after the producers it consumes; chain is {branches[:9]}",
        )
        self.assertLessEqual(
            len(window), len(producers),
            f"the pbp->fantasy window may hold only producer jobs; chain is {branches[:9]}",
        )


if __name__ == "__main__":
    unittest.main()
