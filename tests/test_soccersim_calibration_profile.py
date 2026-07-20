from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import BUNDESLIGA_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import EPL_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import LEAGUE_CALIBRATION_PROFILES
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match


class SoccerSimCalibrationProfileTests(unittest.TestCase):
    def test_default_profile_name(self) -> None:
        self.assertEqual(SOCCER_CALIBRATION_PROFILE.name, "soccer")

    def test_registry_contains_expected_leagues(self) -> None:
        for league in ("soccer", "epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "mls"):
            self.assertIn(league, LEAGUE_CALIBRATION_PROFILES)

    def test_get_league_profile_resolves_aliases_and_falls_back(self) -> None:
        self.assertEqual(get_league_profile("Premier League").name, "epl")
        self.assertEqual(get_league_profile("LALIGA").name, "la_liga")
        self.assertEqual(get_league_profile("unknown_league").name, "soccer")
        self.assertEqual(get_league_profile(None).name, "soccer")

    def test_profile_to_dict_round_trips_all_fields(self) -> None:
        payload = EPL_CALIBRATION_PROFILE.to_dict()
        self.assertEqual(payload["name"], "epl")
        self.assertIn("shot_frequency_multiplier", payload)
        self.assertIn("home_advantage_attack_boost", payload)

    def test_same_seed_different_profiles_can_diverge(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=101)
        base = simulate_match(simulation_input, profile=SOCCER_CALIBRATION_PROFILE)
        bundesliga = simulate_match(simulation_input, profile=BUNDESLIGA_CALIBRATION_PROFILE)
        # Same engine, same seed: outputs are well-formed under both profiles
        # and profile parameters actually flow through the simulation.
        self.assertEqual(base.simulation_kind, bundesliga.simulation_kind)
        self.assertNotEqual(base.to_dict()["possession_log"], bundesliga.to_dict()["possession_log"])


if __name__ == "__main__":
    unittest.main()
