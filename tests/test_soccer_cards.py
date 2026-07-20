from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import cards


class MatchToGameTests(unittest.TestCase):
    def test_simulated_match_renders_real_metrics(self) -> None:
        match = {
            "event_id": "123",
            "match_id": "123",
            "status_state": "pre",
            "kickoff": "2026-08-21T19:00Z",
            "simulations": 200,
            "matchup": {"home_team": "Arsenal", "away_team": "Chelsea"},
            "win_probability": {"home": 0.55, "draw": 0.25, "away": 0.20},
            "team_projection": {"home_mean": 1.8, "away_mean": 1.1, "total_mean": 2.9, "margin_mean": 0.7},
            "total_distribution": {"both_teams_scored_probability": 0.52, "over_2_5_probability": 0.48},
            "volume_projection": {
                "home_shots": 14.0, "away_shots": 10.0,
                "home_shots_on_target": 5.0, "away_shots_on_target": 3.5,
                "home_corners": 6.0, "away_corners": 4.0,
            },
            "top_props": [],
        }
        with patch.object(cards, "team_by_name", return_value=None):
            game = cards._match_to_game(match, league="epl", week=1, season=2026)
        self.assertEqual(game["home"]["name"], "Arsenal")
        self.assertEqual(game["away"]["name"], "Chelsea")
        metrics = {m["label"]: m["value"] for m in game["metrics"]}
        self.assertEqual(metrics["Home win"], "55.0%")
        self.assertEqual(metrics["Draw"], "25.0%")
        self.assertEqual(metrics["Away win"], "20.0%")
        self.assertIn("/soccer/epl/game/123?week=1&season=2026", game["href"])
        self.assertEqual(game["panels"][0]["eyebrow"], "Match projection")

    def test_unsimulated_fixture_shows_placeholder_card(self) -> None:
        fixture = {
            "event_id": "999",
            "home_team": "Newcastle United",
            "away_team": "Fulham",
            "status_state": "pre",
            "date": "2026-08-22T15:00Z",
        }
        with patch.object(cards, "team_by_name", return_value=None):
            game = cards._unsimulated_game(fixture, league="epl", week=1, season=2026)
        self.assertEqual(game["home"]["name"], "Newcastle United")
        self.assertEqual(game["metrics"][0]["value"], "-")
        self.assertEqual(game["panels"][0]["eyebrow"], "Not yet simulated")
        self.assertIn("has not been simulated yet", game["summary"])

    def test_team_roster_href_uses_directory_id_when_matched(self) -> None:
        with patch.object(cards, "team_by_name", return_value={"team_id": "359", "abbreviation": "ARS"}):
            self.assertEqual(cards._team_roster_href("Arsenal", "epl"), "/soccer/epl/team/359/roster")

    def test_team_roster_href_is_none_when_unmatched(self) -> None:
        with patch.object(cards, "team_by_name", return_value=None):
            self.assertIsNone(cards._team_roster_href("Unknown FC", "epl"))


class WeekGamesMergeTests(unittest.TestCase):
    def test_merges_real_schedule_with_simulated_output_by_event_id(self) -> None:
        fixtures = [
            {"event_id": "1", "home_team": "Arsenal", "away_team": "Chelsea", "date": "2026-08-21T19:00Z", "status_state": "pre"},
            {"event_id": "2", "home_team": "Everton", "away_team": "Fulham", "date": "2026-08-22T15:00Z", "status_state": "pre"},
        ]
        simulated_payload = {
            "matches": [
                {
                    "event_id": "1",
                    "match_id": "1",
                    "status_state": "pre",
                    "matchup": {"home_team": "Arsenal", "away_team": "Chelsea"},
                    "win_probability": {"home": 0.5, "draw": 0.3, "away": 0.2},
                    "team_projection": {"home_mean": 1.5, "away_mean": 1.0, "total_mean": 2.5, "margin_mean": 0.5},
                    "total_distribution": {},
                    "volume_projection": {},
                    "top_props": [],
                }
            ]
        }
        with patch.object(cards, "week_matches", return_value=fixtures), \
             patch.object(cards, "week_date_list", return_value=["2026-08-21", "2026-08-22"]), \
             patch.object(cards, "recommendations_payload", side_effect=lambda league, date: simulated_payload if date == "2026-08-21" else {}), \
             patch.object(cards, "team_by_name", return_value=None):
            games = cards.week_games("epl", 1, 2026)
        self.assertEqual(len(games), 2)
        simulated_game = next(g for g in games if g["gamePk"] == "1")
        unsimulated_game = next(g for g in games if g["gamePk"] == "2")
        self.assertEqual(simulated_game["panels"][0]["eyebrow"], "Match projection")
        self.assertEqual(unsimulated_game["panels"][0]["eyebrow"], "Not yet simulated")

    def test_no_fixtures_returns_empty_list(self) -> None:
        with patch.object(cards, "week_matches", return_value=[]):
            self.assertEqual(cards.week_games("epl", 1, 2026), [])


if __name__ == "__main__":
    unittest.main()
