from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import poll_soccer_live_state


class EspnScoreboardQueryShapeTests(unittest.TestCase):
    """The live poller must ask ESPN for ONE date, never a `YYYYMMDD-YYYYMMDD` range.

    Measured 2026-09-15 20:10:46Z, both ESPN hosts, same instant: the range form
    served Championship at 5' 0-0 while the single-date form, the undated
    scoreboard and the match summary all read 69'-70'. Every soccer live surface
    (live lens, Layer 2 chips) was about an hour behind while every timestamp on
    the way read fresh.
    """

    def test_both_scoreboard_reads_use_the_single_date(self) -> None:
        calls: list[tuple[tuple[str, ...], frozenset[str]]] = []

        def _fake_fetch_events(league, *, date_windows, statuses=None, timeout=20):
            calls.append((tuple(date_windows), frozenset(statuses or ())))
            return []

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            poll_soccer_live_state, "fetch_events", side_effect=_fake_fetch_events
        ):
            poll_soccer_live_state.poll_league(
                "championship", "2026-09-15", source_root=Path(tmp), out_root=Path(tmp), simulations=10
            )

        # BOTH call sites reached: the in-play read and the box-score read.
        self.assertEqual({statuses for _, statuses in calls}, {frozenset({"in"}), frozenset({"in", "post"})})
        self.assertEqual({windows for windows, _ in calls}, {("20260915",)})


class PollActiveLeaguesForTickTests(unittest.TestCase):
    def test_flattens_games_across_active_leagues(self) -> None:
        def _fake_poll_league(league, iso_date, *, source_root, out_root, simulations,
                              fixture_cache=None):
            if league == "mls":
                return {"league": league, "date": iso_date, "count": 1, "games": {"123": {"home_team": "A", "away_team": "B"}}}
            return {"league": league, "date": iso_date, "count": 0, "games": {}}

        with patch.object(poll_soccer_live_state, "active_leagues_for_date", return_value=["mls", "epl"]), patch.object(
            poll_soccer_live_state, "poll_league", side_effect=_fake_poll_league
        ):
            result = poll_soccer_live_state.poll_active_leagues_for_tick(
                "2026-07-31", source_root=Path("/tmp/soccer"), out_root=Path("/tmp/soccer"), simulations=80
            )

        self.assertEqual(result["date"], "2026-07-31")
        self.assertEqual(result["leagues_checked"], ["mls", "epl"])
        self.assertEqual(result["leagues_with_games"], ["mls"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["games"]), 1)
        self.assertEqual(result["games"][0]["league"], "mls")
        self.assertEqual(result["games"][0]["event_id"], "123")
        self.assertEqual(result["games"][0]["home_team"], "A")
        self.assertEqual(result["errors"], {})

    def test_one_league_exception_does_not_drop_others(self) -> None:
        def _fake_poll_league(league, iso_date, *, source_root, out_root, simulations,
                              fixture_cache=None):
            if league == "mls":
                raise RuntimeError("espn down")
            return {"league": league, "date": iso_date, "count": 1, "games": {"999": {"home_team": "C", "away_team": "D"}}}

        with patch.object(poll_soccer_live_state, "active_leagues_for_date", return_value=["mls", "epl"]), patch.object(
            poll_soccer_live_state, "poll_league", side_effect=_fake_poll_league
        ):
            result = poll_soccer_live_state.poll_active_leagues_for_tick(
                "2026-07-31", source_root=Path("/tmp/soccer"), out_root=Path("/tmp/soccer"), simulations=80
            )

        self.assertIn("mls", result["errors"])
        self.assertIn("espn down", result["errors"]["mls"])
        self.assertEqual(result["leagues_with_games"], ["epl"])
        self.assertEqual(result["count"], 1)

    def test_no_active_leagues_returns_empty_but_valid_shape(self) -> None:
        with patch.object(poll_soccer_live_state, "active_leagues_for_date", return_value=[]):
            result = poll_soccer_live_state.poll_active_leagues_for_tick(
                "2026-01-15", source_root=Path("/tmp/soccer"), out_root=Path("/tmp/soccer"), simulations=80
            )

        self.assertEqual(result["leagues_checked"], [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["games"], [])


if __name__ == "__main__":
    unittest.main()
