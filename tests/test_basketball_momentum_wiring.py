"""`#514` Phase B wiring: the momentum capture actually FIRES on the tick.

**REACHABILITY BEFORE CORRECTNESS.** `model_engine_standard.md` makes this the
first test for anything behind a flag or a branch, and `#208` states the
general form: allowlisting permits a transfer, it does not make one happen --
and neither does a producer merely existing. Phase B shipped deliberately
unwired, so the single thing worth proving now is that wiring it changed the
behaviour of the tick: basketball ticks call the poller, and the sports that
have no basketball taxonomy do not.

Nothing here asserts anything about momentum's VALUE. Whether pressure leads
scoring is Phase C's question and no test in this file may be cited about it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import live_lens_loop


def _run(sport: str, poll_mock):
    """Drive one per-sport tick with every heavy dependency stubbed."""
    snapshot = {"ok": True, "date": "2026-08-22", "rank_cards": [], "games": []}
    with mock.patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {sport: lambda _d: snapshot}), \
         mock.patch.dict(live_lens_loop._LIVE_LENS_VALIDATORS, {sport: lambda _s: True}), \
         mock.patch.dict(
             live_lens_loop._LIVE_LENS_SNAPSHOT_PATHS,
             {sport: lambda: Path("/tmp/does-not-matter.json")},
         ), \
         mock.patch.object(live_lens_loop, "write_json_file"), \
         mock.patch.object(live_lens_loop, "log_and_persist_process_memory"), \
         mock.patch.object(live_lens_loop, "_mlb_live_lens_headroom_snapshot", return_value=None), \
         mock.patch.object(live_lens_loop, "_soccer_live_lens_headroom_snapshot", return_value=None), \
         mock.patch.object(live_lens_loop, "_wnba_live_lens_headroom_snapshot", return_value=None), \
         mock.patch("scripts.poll_basketball_momentum.poll", poll_mock), \
         mock.patch("scripts.capture_wnba_live_player_box.fetch", side_effect=RuntimeError("no network")):
        return live_lens_loop._run_live_lens_tick_for_sport(sport, "2026-08-22")


class BasketballMomentumWiringTests(unittest.TestCase):
    def test_the_nba_tick_calls_the_momentum_poller(self) -> None:
        poll = mock.MagicMock(return_value={"count": 2, "with_series": 2})
        _run("nba", poll)
        poll.assert_called_once()
        self.assertEqual(poll.call_args.args[0], "nba")

    def test_the_wnba_tick_calls_the_momentum_poller(self) -> None:
        poll = mock.MagicMock(return_value={"count": 1, "with_series": 1})
        _run("wnba", poll)
        poll.assert_called_once()
        self.assertEqual(poll.call_args.args[0], "wnba")

    def test_non_basketball_sports_do_not(self) -> None:
        """`off != on` from the other side. Without this, a block that called
        the poller for EVERY sport would pass the two tests above while
        fetching ESPN basketball URLs on every MLB and soccer tick."""
        for sport in ("mlb", "soccer"):
            poll = mock.MagicMock(return_value={"count": 0, "with_series": 0})
            _run(sport, poll)
            poll.assert_not_called()

    def test_a_momentum_failure_does_not_break_the_tick(self) -> None:
        """The capture is additive and nothing consumes it yet. Taking the
        live-lens tick down for it would trade a feature nobody reads for one
        every sport depends on."""
        poll = mock.MagicMock(side_effect=RuntimeError("espn unreachable"))
        meta = _run("wnba", poll)
        poll.assert_called_once()
        self.assertNotEqual(meta.get("ok"), False, "a capture failure must not fail the tick")

    def test_the_poller_writes_under_the_swept_data_root(self) -> None:
        """The artifact has to land where `sweep_changed_hot_artifacts` looks,
        or the allowlist entry added in Phase B is inert -- `#208` again, in the
        direction that is easy to miss: the pattern matches, and nothing is ever
        in the place the sweep walks."""
        from syndicate.features.shared.artifact_publisher import _data_root
        from syndicate.features.shared.refresh_state_store import data_root

        self.assertEqual(Path(data_root()).resolve(), Path(_data_root()).resolve())

    def test_the_artifact_path_is_allowlisted_from_that_root(self) -> None:
        import fnmatch

        from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS
        from syndicate.features.shared.basketball_momentum_artifacts import momentum_artifact_path
        from syndicate.features.shared.refresh_state_store import data_root

        root = Path(data_root())
        for league in ("nba", "wnba"):
            relative = momentum_artifact_path(root, league_code=league, date_str="2026-08-22")
            rel = relative.relative_to(root).as_posix()
            self.assertTrue(
                any(fnmatch.fnmatch(rel, pattern) for pattern in HOT_ARTIFACT_PATTERNS),
                f"{rel} is not allowlisted -- it could never reach web",
            )


if __name__ == "__main__":
    unittest.main()
