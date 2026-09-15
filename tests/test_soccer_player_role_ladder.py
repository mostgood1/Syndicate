"""Soccer shot props: the retired divisor stays retired.

The 1.393 shot-shrinkage divisor (shipped 2026-08-31) was read from a dated
`soccer_source/calibration/shot_shrinkage_*.json` artifact. That artifact is still
on production's disk, and the calibration glob that delivered it is still
allowlisted, because `probability_calibration` shares it. So the only thing
keeping the old correction out of the engine is that nothing reads the file any
more. The first test pins exactly that, with the artifact PRESENT: an `off == on`
test, the inverse of the reachability test that shipped with the divisor.

Measured before removal (lane soccer-player-role-allocation, 16,377 appeared
outfield rows, 07-22..09-14): log loss at P(shots >= 1) / P(shots >= 2) was
0.690 / 0.570 with the divisor, worse than a constant at 1.5, and 0.632 / 0.498
without it, better in 10/10 leagues.
"""

from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.player_props import PlayerUsageProfile
from syndicate.features.soccer.sim_engine.soccersim.player_props import poisson_at_least
from syndicate.features.soccer.sim_engine.soccersim.player_props import project_player_props


def _distribution() -> MatchDistributionSummary:
    return MatchDistributionSummary(
        simulations=1, home_win_probability=0.4, draw_probability=0.3,
        away_win_probability=0.3, mean_home_goals=1.4, mean_away_goals=1.1,
        mean_total=2.5, mean_margin=0.3, over_2_5_probability=0.5,
        both_teams_scored_probability=0.5, scoreline_probabilities={},
        mean_home_shots=12.0, mean_away_shots=10.0,
        mean_home_shots_on_target=4.0, mean_away_shots_on_target=3.0,
    )


def _striker() -> PlayerUsageProfile:
    return PlayerUsageProfile(
        player_id="p1", player_name="Test Striker", side="home", position="F",
        team="Test FC", expected_minutes_share=0.9, shot_share=0.25,
        goal_share=0.2, assist_share=0.1, on_target_rate=0.35,
    )


class TheRetiredDivisorStaysRetired(unittest.TestCase):
    def _with_divisor_artifact(self, divisor: float):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calibration = Path(tmp.name) / "soccer_source" / "calibration"
        calibration.mkdir(parents=True)
        (calibration / "shot_shrinkage_2026-08-31.json").write_text(
            json.dumps({"divisor": divisor}), encoding="utf-8")
        patcher = mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_divisor_artifact_on_disk_no_longer_moves_the_shot_mean(self):
        """off == on: the artifact production still holds must be inert."""
        without = project_player_props(_distribution(), _striker())
        self._with_divisor_artifact(1.393)
        with_file = project_player_props(_distribution(), _striker())
        self.assertEqual(without.expected_shots, with_file.expected_shots)
        self.assertEqual(without.shots_over_probabilities, with_file.shots_over_probabilities)
        self.assertEqual(without.shots_on_target_over_probabilities,
                         with_file.shots_on_target_over_probabilities)

    def test_the_shot_mean_is_exactly_the_share_of_team_volume(self):
        self._with_divisor_artifact(1.393)
        projection = project_player_props(_distribution(), _striker())
        self.assertAlmostEqual(projection.expected_shots, 12.0 * 0.25, places=4)
        self.assertEqual(projection.shots_over_probabilities["0.5"],
                         round(poisson_at_least(12.0 * 0.25, 1), 4))

    def test_shots_on_target_is_the_shot_mean_times_the_rate(self):
        projection = project_player_props(_distribution(), _striker())
        self.assertAlmostEqual(projection.expected_shots_on_target, 12.0 * 0.25 * 0.35, places=4)

    def test_the_calibration_module_is_gone(self):
        """Nothing can re-import the loader and quietly re-apply it."""
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("syndicate.features.soccer.sim_engine.soccersim.shot_calibration")


if __name__ == "__main__":
    unittest.main()
