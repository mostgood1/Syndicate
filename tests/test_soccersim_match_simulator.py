from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match


class SoccerSimMatchSimulatorTests(unittest.TestCase):
    def test_match_simulation_produces_complete_state_sequence(self) -> None:
        simulation_input = SoccerSimSimulationInput(
            home_team="ARS",
            away_team="LIV",
            seed=11,
            home_attack_rating=0.10,
            home_defense_rating=0.06,
            away_attack_rating=-0.02,
            away_defense_rating=0.03,
        )

        result = simulate_match(simulation_input)

        self.assertEqual(result.simulation_kind, "soccersim_possession")
        self.assertIn("home", result.final_score)
        self.assertIn("away", result.final_score)
        self.assertGreaterEqual(len(result.possession_log), 1)
        self.assertGreaterEqual(len(result.event_log), 1)
        self.assertEqual(len(result.half_log), 2)
        self.assertIn("projected_final_score", result.compatibility_summary)
        self.assertIn("projected_spread", result.compatibility_summary)
        self.assertIn("projected_total", result.compatibility_summary)
        self.assertAlmostEqual(sum(result.win_probability.values()), 1.0)
        self.assertIn("draw", result.win_probability)

    def test_match_simulation_is_seed_stable(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=4)

        first = simulate_match(simulation_input).to_dict()
        second = simulate_match(simulation_input).to_dict()

        self.assertEqual(first["final_score"], second["final_score"])
        self.assertEqual(first["possession_log"], second["possession_log"])

    def test_final_score_matches_half_log(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=17)

        result = simulate_match(simulation_input)

        home_from_halves = sum(half["home_goals"] for half in result.half_log)
        away_from_halves = sum(half["away_goals"] for half in result.half_log)
        self.assertEqual(result.final_score["home"], home_from_halves)
        self.assertEqual(result.final_score["away"], away_from_halves)

    def test_knockout_match_always_resolves_a_winner(self) -> None:
        for seed in range(1, 30):
            simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=seed, knockout=True)
            result = simulate_match(simulation_input)
            self.assertEqual(result.win_probability["draw"], 0.0)
            self.assertEqual(result.win_probability["home"] + result.win_probability["away"], 1.0)
            if result.final_score["home"] == result.final_score["away"]:
                shootout = result.compatibility_summary["shootout"]
                self.assertIsNotNone(shootout)
                self.assertIn(shootout["winner"], {"home", "away"})
                self.assertGreaterEqual(len(result.half_log), 4)


if __name__ == "__main__":
    unittest.main()
