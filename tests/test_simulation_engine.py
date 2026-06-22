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

    def test_mlb_advanced_inputs_reduce_uncertainty_when_present(self) -> None:
        base_context = {
            "sport": "mlb",
            "team_projections": {"home": 5.4, "away": 4.8},
            "player_projections": [{"player": "Starter", "stat": "hits", "projection": 1.2}],
            "model_probability": 0.58,
            "confidence": 0.55,
            "edge": 0.03,
            "seed": 19,
        }
        advanced_context = {
            **base_context,
            "matchup_modifiers": {
                "advanced": {
                    "available": True,
                    "page": {
                        "lineup_health": {"healthy": True},
                        "marketAvailability": {
                            "gameLines": {"available": True},
                            "pitcherProps": {"available": True},
                            "hitterProps": {"available": True},
                            "warnings": [],
                        },
                        "hrTargets": {
                            "rows": 2,
                            "topRows": [{
                                "player": "Slugger",
                                "batter_xwoba": 0.356,
                                "batter_hardhit_rate": 0.47,
                                "batter_barrel_rate": 0.09,
                                "batter_launch_angle_mean": 18.2,
                                "pitcher_xwoba_allowed": 0.301,
                                "pitch_mix_score": 1.08,
                            }],
                        },
                        "workflow": {"mode": "daily_update"},
                    },
                    "game": {
                        "run_projection_rows": [{"label": "Q1", "value": 1.0}],
                        "segment_overview_cards": [{"title": "First 5", "value": "Edge"}],
                        "first1BetSignal": {"market": "first1", "value": 0.31},
                        "gameLens": [{"label": "Live lens"}],
                        "props": [{"market": "hitter_props"}],
                        "liveProps": [{"market": "pitcher_props"}],
                        "snapshotAvailable": True,
                        "simContextAvailable": True,
                    },
                }
            },
        }

        baseline = run_monte_carlo(base_context, iterations=100)
        advanced = run_monte_carlo(advanced_context, iterations=100)

        self.assertIn("advanced", advanced["inputs"])
        self.assertTrue(advanced["inputs"]["advanced"]["available"])
        self.assertEqual(advanced["inputs"]["advanced"]["page"]["hrTargets"]["topRows"][0]["batter_xwoba"], 0.356)
        self.assertLess(advanced["inputs"]["advanced_std_dev_scale"], 1.0)
        self.assertLess(advanced["std_dev"]["team_score"]["home"], baseline["std_dev"]["team_score"]["home"])
