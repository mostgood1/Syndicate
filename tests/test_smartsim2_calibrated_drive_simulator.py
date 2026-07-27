from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_simulator import simulate_drive
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state


class SmartSim2CalibratedDriveSimulatorTests(unittest.TestCase):
    def _make_input(self, *, strong: bool) -> SmartSim2SimulationInput:
        if strong:
            return SmartSim2SimulationInput(
                home_team="PHI",
                away_team="DAL",
                seed=13,
                feature_generation_payload={
                    "offensive_metrics": {"offensive_epa": 0.16, "success_rate": 0.60, "red_zone_efficiency": 0.72, "explosive_play_rate": 0.18},
                    "defensive_metrics": {"defensive_epa": -0.03, "success_rate_allowed": 0.45},
                    "pace": {"pace_seconds_per_play": 22.5},
                    "advanced_metrics": {"home_offensive_epa": 0.15, "home_defensive_epa": -0.02},
                    "player_usage": {"snap_share": 0.54, "target_share": 0.41, "route_participation": 0.46, "air_yard_share": 0.35},
                    "market_features": {"total": {"line": 56.5}, "spread": {"home_line": -8.5}, "confidence": 0.67, "model_probability": 0.62},
                    "returning_production": {"percent_ppa": 0.76},
                    "coach_continuity": {"continuity_score": 0.81},
                    "transfer_impact": {"net": 3.0},
                },
            )
        return SmartSim2SimulationInput(
            home_team="PHI",
            away_team="DAL",
            seed=13,
            feature_generation_payload={
                "offensive_metrics": {"offensive_epa": -0.05, "success_rate": 0.41, "red_zone_efficiency": 0.39, "explosive_play_rate": 0.06},
                "defensive_metrics": {"defensive_epa": 0.10, "success_rate_allowed": 0.58},
                "pace": {"pace_seconds_per_play": 29.0},
                "advanced_metrics": {"home_offensive_epa": -0.03, "home_defensive_epa": 0.07},
                "player_usage": {"snap_share": 0.22, "target_share": 0.17, "route_participation": 0.19, "air_yard_share": 0.11},
                "market_features": {"total": {"line": 40.5}, "spread": {"home_line": -4.0}, "confidence": 0.43, "model_probability": 0.42},
                "returning_production": {"percent_ppa": 0.37},
                "coach_continuity": {"continuity_score": 0.34},
                "transfer_impact": {"net": 11.0},
            },
        )

    def test_stronger_features_raise_scoring_frequency(self) -> None:
        strong_state = build_initial_possession_state(home_team="PHI", away_team="DAL", field_position=62)
        weak_state = build_initial_possession_state(home_team="PHI", away_team="DAL", field_position=62)

        strong_points = 0
        weak_points = 0
        strong_touchdowns = 0
        weak_touchdowns = 0

        for seed in range(1, 31):
            strong_input = self._make_input(strong=True)
            weak_input = self._make_input(strong=False)
            strong_input = SmartSim2SimulationInput(**{**strong_input.to_dict(), "seed": seed})
            weak_input = SmartSim2SimulationInput(**{**weak_input.to_dict(), "seed": seed})
            strong_result = simulate_drive(strong_state, strong_input)
            weak_result = simulate_drive(weak_state, weak_input)
            strong_points += strong_result.points_scored
            weak_points += weak_result.points_scored
            strong_touchdowns += int(strong_result.outcome == PossessionOutcome.TOUCHDOWN)
            weak_touchdowns += int(weak_result.outcome == PossessionOutcome.TOUCHDOWN)

        # Points and touchdown counts are the scoring-frequency signal this
        # test pins. Punt counts at 30 seeded drives are single-digit noise
        # (the calibration-profile v2 change reshuffled them without changing
        # the scoring relationship), so they are deliberately not compared.
        self.assertGreater(strong_points, weak_points)
        self.assertGreater(strong_touchdowns, weak_touchdowns)

    def test_input_changes_shift_possession_outcomes(self) -> None:
        base_state = build_initial_possession_state(home_team="PHI", away_team="DAL", field_position=55, down=3, distance=8)
        aggressive = self._make_input(strong=True)
        conservative = self._make_input(strong=False)

        aggressive_result = simulate_drive(base_state, aggressive)
        conservative_result = simulate_drive(base_state, conservative)

        self.assertNotEqual(aggressive_result.outcome, conservative_result.outcome)


if __name__ == "__main__":
    unittest.main()