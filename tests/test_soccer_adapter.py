from __future__ import annotations

import unittest

from syndicate.features.soccer.adapters import build_soccer_simulation_adapter
from syndicate.features.soccer.contracts import SoccerMatchFeatures
from syndicate.features.soccer.contracts import SoccerPlayerFeatures
from syndicate.features.soccer.contracts import SoccerSimulationInput


def _simulation_input() -> SoccerSimulationInput:
    match = SoccerMatchFeatures(
        league="epl",
        date="2026-08-15",
        match_id="epl_ars_liv_2026_08_15",
        home_team="ARS",
        away_team="LIV",
        team_metrics={"home_attack_rating": 0.08, "away_attack_rating": 0.05},
        market_features={"total": {"line": 2.75}},
    )
    players = (
        SoccerPlayerFeatures(
            league="epl",
            date="2026-08-15",
            player_id="ars_9",
            player_name="Home Striker",
            team="ARS",
            position="FW",
            usage_metrics={"shots_per90": 3.4, "xg_per90": 0.55, "xa_per90": 0.12, "penalty_taker": True},
        ),
        SoccerPlayerFeatures(
            league="epl",
            date="2026-08-15",
            player_id="ars_1",
            player_name="Home Keeper",
            team="ARS",
            position="GK",
            usage_metrics={"is_goalkeeper": True},
        ),
        SoccerPlayerFeatures(
            league="epl",
            date="2026-08-15",
            player_id="liv_11",
            player_name="Away Winger",
            team="LIV",
            position="FW",
            usage_metrics={"shots_per90": 2.8, "xg_per90": 0.40, "xa_per90": 0.25},
        ),
    )
    return SoccerSimulationInput(
        league="epl",
        date="2026-08-15",
        matches=(match,),
        players=players,
        metadata={"simulations": 40},
    )


class SoccerSimulationAdapterTests(unittest.TestCase):
    def test_simulate_games_produces_three_way_market_outputs(self) -> None:
        adapter = build_soccer_simulation_adapter("epl")
        output = adapter.simulate_games(_simulation_input())

        self.assertEqual(output.league, "epl")
        self.assertEqual(len(output.match_outputs), 1)
        self.assertEqual(len(output.player_outputs), 0)
        match_output = output.match_outputs[0]
        probabilities = match_output["win_probability"]
        self.assertAlmostEqual(
            probabilities["home"] + probabilities["draw"] + probabilities["away"], 1.0, places=6
        )
        self.assertIn("volume_projection", match_output)
        self.assertGreater(match_output["team_projection"]["total_mean"], 0.5)
        self.assertEqual(match_output["simulations"], 40)

    def test_simulate_games_is_deterministic_per_match(self) -> None:
        adapter = build_soccer_simulation_adapter("epl")
        first = adapter.simulate_games(_simulation_input()).match_outputs[0]
        second = adapter.simulate_games(_simulation_input()).match_outputs[0]
        self.assertEqual(first["win_probability"], second["win_probability"])
        self.assertEqual(first["scoreline_probabilities"], second["scoreline_probabilities"])

    def test_simulate_props_projects_players_on_both_sides(self) -> None:
        adapter = build_soccer_simulation_adapter("epl")
        output = adapter.simulate_props(_simulation_input())

        self.assertEqual(len(output.player_outputs), 3)
        by_id = {row["player_id"]: row for row in output.player_outputs}

        striker = by_id["ars_9"]
        self.assertEqual(striker["side"], "home")
        self.assertGreater(striker["anytime_scorer_probability"], 0.0)
        self.assertGreater(striker["expected_shots"], 0.0)
        self.assertIn("0.5", striker["shots_over_probabilities"])

        keeper = by_id["ars_1"]
        self.assertIsNotNone(keeper["expected_saves"])
        self.assertGreater(keeper["expected_saves"], 0.0)
        self.assertEqual(keeper["anytime_scorer_probability"], 0.0)

        winger = by_id["liv_11"]
        self.assertEqual(winger["side"], "away")
        self.assertEqual(winger["match_id"], "epl_ars_liv_2026_08_15")

    def test_build_artifacts_surfaces_top_scorer_props(self) -> None:
        adapter = build_soccer_simulation_adapter("epl")
        output = adapter.simulate_props(_simulation_input())
        artifacts = adapter.build_artifacts(output)

        self.assertEqual(artifacts["league"], "epl")
        rows = artifacts["top_props"]["rows"]
        self.assertGreaterEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["anytime_scorer_probability"], rows[-1]["anytime_scorer_probability"])

    def test_load_features_returns_empty_fallback(self) -> None:
        adapter = build_soccer_simulation_adapter("epl")
        simulation_input = adapter.load_features(date="2026-08-15")
        self.assertEqual(simulation_input.adapter_metadata.get("source"), "fallback_empty")
        self.assertEqual(simulation_input.matches, ())


if __name__ == "__main__":
    unittest.main()
