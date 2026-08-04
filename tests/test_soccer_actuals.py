"""Tests for syndicate.features.soccer.actuals -- soccer's first-ever
settlement grader (moneyline/total@2.5/BTTS from real schedule scores)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import actuals


def _schedule_payload(matches):
    return {"league": "mls", "season": 2026, "matches": matches}


class GradedRowsForLeagueDateTests(unittest.TestCase):
    def test_finished_match_grades_moneyline_total_and_btts(self) -> None:
        matches = [
            {
                "event_id": "1", "date": "2026-07-25T22:30Z", "home_team": "Red Bull New York",
                "away_team": "Charlotte FC", "home_score": "2", "away_score": "1",
                "status_state": "post", "week": 20,
            }
        ]
        with patch("syndicate.features.soccer.actuals.schedule_payload", side_effect=lambda league, season: _schedule_payload(matches) if season == 2026 else None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=()):
            rows = actuals.graded_rows_for_league_date("mls", "2026-07-25")

        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("moneyline", "Red Bull New York")]["result"], "win")
        self.assertEqual(by_market_selection[("moneyline", "Draw")]["result"], "loss")
        self.assertEqual(by_market_selection[("moneyline", "Charlotte FC")]["result"], "loss")
        # total goals = 3 > 2.5 -> over wins
        self.assertEqual(by_market_selection[("total", "over")]["result"], "win")
        self.assertEqual(by_market_selection[("total", "under")]["result"], "loss")
        # both teams scored (2-1) -> btts yes wins
        self.assertEqual(by_market_selection[("btts", "yes")]["result"], "win")
        self.assertEqual(by_market_selection[("btts", "no")]["result"], "loss")

    def test_draw_grades_correctly(self) -> None:
        matches = [
            {
                "event_id": "2", "date": "2026-07-25T22:30Z", "home_team": "D.C. United",
                "away_team": "Philadelphia Union", "home_score": "1", "away_score": "1",
                "status_state": "post", "week": 20,
            }
        ]
        with patch("syndicate.features.soccer.actuals.schedule_payload", side_effect=lambda league, season: _schedule_payload(matches) if season == 2026 else None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=()):
            rows = actuals.graded_rows_for_league_date("mls", "2026-07-25")
        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("moneyline", "Draw")]["result"], "win")
        self.assertEqual(by_market_selection[("moneyline", "D.C. United")]["result"], "loss")
        self.assertEqual(by_market_selection[("moneyline", "Philadelphia Union")]["result"], "loss")
        # 1-1 total = 2 < 2.5 -> under wins; both scored -> btts yes wins
        self.assertEqual(by_market_selection[("total", "under")]["result"], "win")
        self.assertEqual(by_market_selection[("btts", "yes")]["result"], "win")

    def test_shutout_means_btts_no_wins(self) -> None:
        matches = [
            {
                "event_id": "3", "date": "2026-07-25T22:30Z", "home_team": "FC Cincinnati",
                "away_team": "Atlanta United FC", "home_score": "2", "away_score": "0",
                "status_state": "post", "week": 20,
            }
        ]
        with patch("syndicate.features.soccer.actuals.schedule_payload", side_effect=lambda league, season: _schedule_payload(matches) if season == 2026 else None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=()):
            rows = actuals.graded_rows_for_league_date("mls", "2026-07-25")
        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("btts", "no")]["result"], "win")
        self.assertEqual(by_market_selection[("btts", "yes")]["result"], "loss")

    def test_pregame_match_is_skipped(self) -> None:
        matches = [
            {
                "event_id": "4", "date": "2026-07-25T22:30Z", "home_team": "LA Galaxy",
                "away_team": "Seattle Sounders FC", "home_score": "0", "away_score": "0",
                "status_state": "pre", "week": 20,
            }
        ]
        with patch("syndicate.features.soccer.actuals.schedule_payload", side_effect=lambda league, season: _schedule_payload(matches) if season == 2026 else None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=()):
            rows = actuals.graded_rows_for_league_date("mls", "2026-07-25")
        self.assertEqual(rows, [])

    def test_wrong_date_is_skipped(self) -> None:
        matches = [
            {
                "event_id": "5", "date": "2026-07-24T22:30Z", "home_team": "LA Galaxy",
                "away_team": "Seattle Sounders FC", "home_score": "1", "away_score": "0",
                "status_state": "post", "week": 20,
            }
        ]
        with patch("syndicate.features.soccer.actuals.schedule_payload", side_effect=lambda league, season: _schedule_payload(matches) if season == 2026 else None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=()):
            rows = actuals.graded_rows_for_league_date("mls", "2026-07-25")
        self.assertEqual(rows, [])

    def test_odds_price_joined_when_team_names_fuzzy_match(self) -> None:
        matches = [
            {
                "event_id": "6", "date": "2026-07-25T22:30Z", "home_team": "Red Bull New York",
                "away_team": "Charlotte FC", "home_score": "2", "away_score": "1",
                "status_state": "post", "week": 20,
            }
        ]
        odds_rows = (
            {"event_id": "odds-abc", "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "market": "h2h", "side": "New York Red Bulls", "price": "-150"},
            {"event_id": "odds-abc", "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "market": "totals", "side": "Over", "line": "2.5", "price": "-110"},
        )
        with patch("syndicate.features.soccer.actuals.schedule_payload", side_effect=lambda league, season: _schedule_payload(matches) if season == 2026 else None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=odds_rows):
            rows = actuals.graded_rows_for_league_date("mls", "2026-07-25")
        by_market_selection = {(r["market"], r["selection"]): r for r in rows}
        self.assertEqual(by_market_selection[("total", "over")]["odds"], -110.0)

    def test_no_schedule_data_returns_empty(self) -> None:
        with patch("syndicate.features.soccer.actuals.schedule_payload", return_value=None), \
             patch("syndicate.features.soccer.actuals.game_odds_rows", return_value=()):
            self.assertEqual(actuals.graded_rows_for_league_date("mls", "2026-07-25"), [])


class GradedRowsForDateTests(unittest.TestCase):
    def test_scans_all_leagues_and_tolerates_one_failing(self) -> None:
        def _fake_league_grader(league, date_str):
            if league == "epl":
                raise RuntimeError("boom")
            if league == "mls":
                return [{"sport": "soccer", "league": "mls", "market": "moneyline", "result": "win"}]
            return []

        with patch("syndicate.features.soccer.actuals.graded_rows_for_league_date", side_effect=_fake_league_grader):
            rows = actuals.graded_rows_for_date("2026-07-25")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["league"], "mls")


if __name__ == "__main__":
    unittest.main()
