from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import poll_soccer_live_state


class PollActiveLeaguesForTickTests(unittest.TestCase):
    def test_flattens_games_across_active_leagues(self) -> None:
        def _fake_poll_league(league, iso_date, *, source_root, out_root, simulations):
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
        def _fake_poll_league(league, iso_date, *, source_root, out_root, simulations):
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
