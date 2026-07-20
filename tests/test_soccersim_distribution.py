from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.distribution import simulate_match_distribution
from syndicate.features.soccer.sim_engine.soccer_core import simulate_league_match
from syndicate.features.soccer.sim_engine.soccer_core import simulate_league_match_distribution


class SoccerSimDistributionTests(unittest.TestCase):
    def test_distribution_probabilities_sum_to_one(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=3)
        summary = simulate_match_distribution(simulation_input, simulations=60)

        self.assertEqual(summary.simulations, 60)
        self.assertAlmostEqual(
            summary.home_win_probability + summary.draw_probability + summary.away_win_probability,
            1.0,
            places=6,
        )
        self.assertAlmostEqual(summary.mean_total, summary.mean_home_goals + summary.mean_away_goals, places=4)
        self.assertAlmostEqual(sum(summary.scoreline_probabilities.values()), 1.0, places=2)

    def test_distribution_is_seed_stable(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=3)
        first = simulate_match_distribution(simulation_input, simulations=40).to_dict()
        second = simulate_match_distribution(simulation_input, simulations=40).to_dict()
        self.assertEqual(first, second)

    def test_stronger_home_side_wins_more(self) -> None:
        neutral = simulate_match_distribution(
            SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=5), simulations=120
        )
        lopsided = simulate_match_distribution(
            SoccerSimSimulationInput(
                home_team="ARS",
                away_team="LIV",
                seed=5,
                home_attack_rating=0.25,
                home_defense_rating=0.25,
                away_attack_rating=-0.25,
                away_defense_rating=-0.25,
            ),
            simulations=120,
        )
        self.assertGreater(lopsided.home_win_probability, neutral.home_win_probability)
        self.assertGreater(lopsided.mean_margin, neutral.mean_margin)

    def test_league_entrypoints_resolve_profiles(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=9)
        output = simulate_league_match(simulation_input, league="epl")
        self.assertEqual(output.simulation_kind, "soccersim_possession")
        summary = simulate_league_match_distribution(simulation_input, league="bundesliga", simulations=30)
        self.assertEqual(summary.simulations, 30)


if __name__ == "__main__":
    unittest.main()
