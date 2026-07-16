from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors


class SmartSim2DrivePriorsTests(unittest.TestCase):
    def test_stronger_offense_increases_drive_success_and_explosiveness(self) -> None:
        weak_input = SmartSim2SimulationInput(
            home_team="PHI",
            away_team="DAL",
            feature_generation_payload={
                "offensive_metrics": {"offensive_epa": -0.05, "success_rate": 0.42, "red_zone_efficiency": 0.41, "explosive_play_rate": 0.06, "pass_rate_over_expectation": -0.03},
                "defensive_metrics": {"defensive_epa": 0.09, "success_rate_allowed": 0.56},
                "pace": {"pace_seconds_per_play": 29.0},
                "advanced_metrics": {"home_offensive_epa": -0.04, "home_defensive_epa": 0.08},
                "player_usage": {"snap_share": 0.22, "target_share": 0.18, "route_participation": 0.20, "air_yard_share": 0.12},
                "market_features": {"total": {"line": 41.0}, "spread": {"home_line": -4.5}, "confidence": 0.44, "model_probability": 0.43},
                "returning_production": {"percent_ppa": 0.39},
                "coach_continuity": {"continuity_score": 0.36},
                "transfer_impact": {"net": 10.0},
            },
        )
        strong_input = SmartSim2SimulationInput(
            home_team="PHI",
            away_team="DAL",
            feature_generation_payload={
                "offensive_metrics": {"offensive_epa": 0.17, "success_rate": 0.61, "red_zone_efficiency": 0.74, "explosive_play_rate": 0.19, "pass_rate_over_expectation": 0.08},
                "defensive_metrics": {"defensive_epa": -0.04, "success_rate_allowed": 0.44},
                "pace": {"pace_seconds_per_play": 22.4},
                "advanced_metrics": {"home_offensive_epa": 0.16, "home_defensive_epa": -0.03},
                "player_usage": {"snap_share": 0.51, "target_share": 0.42, "route_participation": 0.47, "air_yard_share": 0.39},
                "market_features": {"total": {"line": 57.0}, "spread": {"home_line": -9.5}, "confidence": 0.69, "model_probability": 0.63},
                "returning_production": {"percent_ppa": 0.77},
                "coach_continuity": {"continuity_score": 0.82},
                "transfer_impact": {"net": 2.0},
            },
        )

        weak_priors = build_drive_priors(weak_input)
        strong_priors = build_drive_priors(strong_input)

        self.assertGreater(strong_priors.drive_success_probability, weak_priors.drive_success_probability)
        self.assertGreater(strong_priors.explosive_play_probability, weak_priors.explosive_play_probability)
        self.assertGreater(strong_priors.touchdown_probability, weak_priors.touchdown_probability)
        self.assertLess(strong_priors.turnover_probability, weak_priors.turnover_probability)

    def test_prior_profile_includes_feature_summary(self) -> None:
        simulation_input = SmartSim2SimulationInput(
            home_team="PHI",
            away_team="DAL",
            feature_generation_payload={"offensive_metrics": {"success_rate": 0.53}},
        )

        priors = build_drive_priors(simulation_input)

        self.assertIn("offensive_metrics", priors.feature_summary)
        self.assertIn("feature_generation_payload", simulation_input.to_dict())


if __name__ == "__main__":
    unittest.main()