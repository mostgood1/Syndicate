from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import cards


def _directory_team(**overrides) -> dict:
    base = dict(
        team_id="359",
        name="Arsenal",
        abbreviation="ARS",
        short_name="Arsenal",
        color="e20520",
        alternate_color="003399",
        logo_url="https://a.espncdn.com/i/teamlogos/soccer/500/359.png",
    )
    base.update(overrides)
    return base


class SoccerTeamBrandingHelperTests(unittest.TestCase):
    def test_logo_url_from_directory(self) -> None:
        with patch.object(cards, "team_by_name", return_value=_directory_team()):
            self.assertEqual(cards._team_logo_url("Arsenal", "epl"), "https://a.espncdn.com/i/teamlogos/soccer/500/359.png")

    def test_logo_url_none_when_unresolved(self) -> None:
        with patch.object(cards, "team_by_name", return_value=None):
            self.assertIsNone(cards._team_logo_url("Unknown FC", "epl"))

    def test_colors_re_add_hash_prefix(self) -> None:
        with patch.object(cards, "team_by_name", return_value=_directory_team()):
            self.assertEqual(cards._team_primary_color("Arsenal", "epl"), "#e20520")
            self.assertEqual(cards._team_secondary_color("Arsenal", "epl"), "#003399")

    def test_colors_none_when_unresolved(self) -> None:
        with patch.object(cards, "team_by_name", return_value=None):
            self.assertIsNone(cards._team_primary_color("Unknown FC", "epl"))
            self.assertIsNone(cards._team_secondary_color("Unknown FC", "epl"))

    def test_colors_none_when_directory_missing_color_fields(self) -> None:
        with patch.object(cards, "team_by_name", return_value=_directory_team(color="", alternate_color="")):
            self.assertIsNone(cards._team_primary_color("Arsenal", "epl"))
            self.assertIsNone(cards._team_secondary_color("Arsenal", "epl"))


class UnsimulatedGameBrandingTests(unittest.TestCase):
    def test_unsimulated_game_includes_branding_fields(self) -> None:
        fixture = {
            "event_id": "456",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "status_state": "pre",
            "date": "2026-08-21",
            "week": 1,
        }
        chelsea = _directory_team(team_id="363", name="Chelsea", abbreviation="CHE", color="034694", alternate_color="ffffff", logo_url="https://a.espncdn.com/i/teamlogos/soccer/500/363.png")
        arsenal = _directory_team()

        def fake_team_by_name(league, team):
            return {"Arsenal": arsenal, "Chelsea": chelsea}.get(team)

        with patch.object(cards, "team_by_name", side_effect=fake_team_by_name):
            game = cards._unsimulated_game(fixture, league="epl", week=1, season=2026)

        self.assertEqual(game["home"]["logo_url"], "https://a.espncdn.com/i/teamlogos/soccer/500/359.png")
        self.assertEqual(game["home"]["primary_color"], "#e20520")
        self.assertEqual(game["away"]["logo_url"], "https://a.espncdn.com/i/teamlogos/soccer/500/363.png")


class MatchToGameBrandingTests(unittest.TestCase):
    def test_match_to_game_includes_branding_fields(self) -> None:
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
        chelsea = _directory_team(team_id="363", name="Chelsea", abbreviation="CHE", color="034694", alternate_color="ffffff", logo_url="https://a.espncdn.com/i/teamlogos/soccer/500/363.png")
        arsenal = _directory_team()

        def fake_team_by_name(league, team):
            return {"Arsenal": arsenal, "Chelsea": chelsea}.get(team)

        with patch.object(cards, "team_by_name", side_effect=fake_team_by_name):
            game = cards._match_to_game(match, league="epl", week=1, season=2026)

        self.assertEqual(game["home"]["logo_url"], "https://a.espncdn.com/i/teamlogos/soccer/500/359.png")
        self.assertEqual(game["home"]["primary_color"], "#e20520")
        self.assertEqual(game["away"]["logo_url"], "https://a.espncdn.com/i/teamlogos/soccer/500/363.png")
        self.assertEqual(game["away"]["secondary_color"], "#ffffff")

    def test_match_to_game_branding_none_when_directory_unresolved(self) -> None:
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
        self.assertIsNone(game["home"]["logo_url"])
        self.assertIsNone(game["away"]["primary_color"])


if __name__ == "__main__":
    unittest.main()
