from __future__ import annotations

import unittest

from syndicate.features.soccer.features.loaders import build_soccer_simulation_input
from syndicate.features.soccer.features.loaders import compute_team_ratings
from syndicate.features.soccer.features.loaders import team_rows_from_match_history
from syndicate.features.soccer.features.team_names import canonical_team_name
from syndicate.features.soccer.features.team_names import match_team_name


def _team_rows() -> list[dict]:
    rows = []
    for _ in range(10):
        rows.append({"team": "Manchester City", "xg_for": 2.3, "xg_against": 0.8, "ppda": 9.0})
        rows.append({"team": "Everton", "xg_for": 1.1, "xg_against": 2.2, "ppda": 13.0})
        rows.append({"team": "Arsenal", "xg_for": 2.0, "xg_against": 0.9, "ppda": 10.0})
    return rows


class TeamNameTests(unittest.TestCase):
    def test_canonical_aliases(self) -> None:
        self.assertEqual(canonical_team_name("Man City"), "manchester city")
        self.assertEqual(canonical_team_name("Nott'm Forest"), "nottingham forest")
        self.assertEqual(canonical_team_name("Wolverhampton Wanderers"), "wolverhampton")
        self.assertEqual(canonical_team_name("Tottenham Hotspur"), "tottenham")

    def test_lafc_does_not_collide_with_galaxy(self) -> None:
        candidates = ["Los Angeles FC", "LA Galaxy"]
        self.assertEqual(match_team_name("Los Angeles FC", candidates), "Los Angeles FC")
        self.assertEqual(match_team_name("LA Galaxy", candidates), "LA Galaxy")
        self.assertEqual(match_team_name("Los Angeles Galaxy", candidates), "LA Galaxy")

    def test_match_team_name_fuzzy_and_missing(self) -> None:
        candidates = ["Manchester City", "Manchester United", "Everton"]
        self.assertEqual(match_team_name("Man City", candidates), "Manchester City")
        self.assertEqual(match_team_name("Man Utd", candidates), "Manchester United")
        self.assertIsNone(match_team_name("Real Madrid", candidates))


class TeamRatingTests(unittest.TestCase):
    def test_ratings_are_relative_to_league_mean(self) -> None:
        ratings = compute_team_ratings(_team_rows())

        self.assertGreater(ratings["Manchester City"]["attack_rating"], 0.0)
        self.assertGreater(ratings["Manchester City"]["defense_rating"], 0.0)
        self.assertLess(ratings["Everton"]["attack_rating"], 0.0)
        self.assertLess(ratings["Everton"]["defense_rating"], 0.0)
        self.assertAlmostEqual(ratings["Manchester City"]["xg_for_per_match"], 2.3, places=4)

    def test_window_limits_rows(self) -> None:
        rows = _team_rows()
        # Append a late collapse for City; a short window should see only it.
        for _ in range(5):
            rows.append({"team": "Manchester City", "xg_for": 0.5, "xg_against": 2.5, "ppda": 14.0})
        full = compute_team_ratings(rows)
        recent = compute_team_ratings(rows, window=5)
        self.assertLess(recent["Manchester City"]["attack_rating"], full["Manchester City"]["attack_rating"])

    def test_team_rows_from_match_history(self) -> None:
        match_rows = [
            {"league": "epl", "season": 2025, "date": "x", "home_team": "A", "away_team": "B", "home_goals": 3, "away_goals": 1},
        ]
        rows = team_rows_from_match_history(match_rows)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["team"], "A")
        self.assertEqual(rows[0]["xg_for"], 3.0)
        self.assertEqual(rows[1]["team"], "B")
        self.assertEqual(rows[1]["xg_against"], 3.0)


class SimulationInputBuilderTests(unittest.TestCase):
    def test_build_input_matches_ratings_and_players(self) -> None:
        ratings = compute_team_ratings(_team_rows())
        player_rows = [
            {"player_id": "p1", "player_name": "City Striker", "team": "Man City", "position": "FW",
             "shots_per90": 3.5, "xg_per90": 0.6, "xa_per90": 0.2, "expected_minutes_share": 0.9},
            {"player_id": "p2", "player_name": "Everton Mid", "team": "Everton", "position": "MF",
             "shots_per90": 1.5, "xg_per90": 0.2, "xa_per90": 0.2, "expected_minutes_share": 0.8},
            {"player_id": "p3", "player_name": "Elsewhere", "team": "Real Madrid", "position": "FW",
             "shots_per90": 3.0, "xg_per90": 0.5, "xa_per90": 0.2},
        ]
        simulation_input = build_soccer_simulation_input(
            league="epl",
            date="2026-08-21",
            fixtures=[{"home_team": "Manchester City", "away_team": "Everton"}],
            ratings=ratings,
            player_rows=player_rows,
            simulations=25,
        )

        self.assertEqual(len(simulation_input.matches), 1)
        match = simulation_input.matches[0]
        self.assertGreater(match.team_metrics["home_attack_rating"], 0.0)
        self.assertLess(match.team_metrics["away_attack_rating"], 0.0)
        self.assertTrue(match.adapter_metadata["home_rating_matched"])
        # Player from an unrelated team is excluded; matched players are
        # rewritten to fixture naming.
        self.assertEqual(len(simulation_input.players), 2)
        self.assertEqual(simulation_input.players[0].team, "Manchester City")
        self.assertEqual(simulation_input.metadata["simulations"], 25)

    def test_unrated_team_gets_neutral_rating_and_flag(self) -> None:
        ratings = compute_team_ratings(_team_rows())
        simulation_input = build_soccer_simulation_input(
            league="epl",
            date="2026-08-21",
            fixtures=[{"home_team": "Arsenal", "away_team": "Coventry City"}],
            ratings=ratings,
        )
        match = simulation_input.matches[0]
        self.assertEqual(match.team_metrics["away_attack_rating"], 0.0)
        self.assertFalse(match.adapter_metadata["away_rating_matched"])


if __name__ == "__main__":
    unittest.main()
