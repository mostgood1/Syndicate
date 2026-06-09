from __future__ import annotations

import unittest

from syndicate.features.simulation_engine import SimulationEngine, run_monte_carlo


class SimulationEngineTests(unittest.TestCase):
    def test_run_simulation_preserves_compatibility_keys_and_simulates_players(self) -> None:
        engine = SimulationEngine(default_iterations=200)
        result = engine.run_simulation(
            {
                "sport": "nba",
                "market": "points",
                "selection": "Player Over 20.5",
                "line": 20.5,
                "model_probability": 0.62,
                "confidence": 0.58,
                "edge": 0.04,
                "team_projections": {"home": 112.5, "away": 108.0},
                "player_projections": [{"player": "Player", "stat": "points", "projection": 21.2}],
                "seed": 7,
            }
        )

        self.assertIn("distribution", result)
        self.assertIn("probability_distributions", result)
        self.assertEqual(result["distribution"], result["probability_distributions"])
        self.assertAlmostEqual(sum(result["distribution"].values()), 1.0, places=3)
        self.assertIn("expected_values", result)
        self.assertIn("variance", result)
        self.assertIn("std_dev", result)
        self.assertIn("Player", result["player_stat_distributions"])
        self.assertIn("points", result["player_stat_distributions"]["Player"])
        self.assertEqual(result["iterations"], 200)

    def test_module_helper_runs_with_explicit_iterations(self) -> None:
        result = run_monte_carlo({"sport": "mlb", "team_projections": {"home": 5.2, "away": 4.7}, "seed": 11}, iterations=50)

        self.assertEqual(result["iterations"], 50)
        self.assertIn("outcome_distribution", result)
        self.assertIn("home", result["expected_values"]["team_score"])
