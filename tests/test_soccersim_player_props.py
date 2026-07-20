from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.player_props import PlayerUsageProfile
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles
from syndicate.features.soccer.sim_engine.soccersim.player_props import poisson_at_least
from syndicate.features.soccer.sim_engine.soccersim.player_props import project_player_props
from syndicate.features.soccer.sim_engine.soccersim.player_props import project_team_player_props


def _distribution() -> MatchDistributionSummary:
    return MatchDistributionSummary(
        simulations=1000,
        home_win_probability=0.45,
        draw_probability=0.27,
        away_win_probability=0.28,
        mean_home_goals=1.6,
        mean_away_goals=1.1,
        mean_total=2.7,
        mean_margin=0.5,
        over_2_5_probability=0.52,
        both_teams_scored_probability=0.55,
        scoreline_probabilities={"1-0": 0.12},
        mean_home_shots=13.0,
        mean_away_shots=10.0,
        mean_home_shots_on_target=4.5,
        mean_away_shots_on_target=3.4,
        mean_home_corners=6.0,
        mean_away_corners=5.0,
    )


class SoccerSimPlayerPropsTests(unittest.TestCase):
    def test_poisson_at_least(self) -> None:
        self.assertAlmostEqual(poisson_at_least(0.0, 1), 0.0)
        self.assertAlmostEqual(poisson_at_least(0.0, 0), 1.0)
        self.assertAlmostEqual(poisson_at_least(1.0, 1), 0.6321, places=4)
        self.assertGreater(poisson_at_least(2.0, 1), poisson_at_least(1.0, 1))
        self.assertGreater(poisson_at_least(1.0, 1), poisson_at_least(1.0, 2))

    def test_striker_projection_allocates_team_volume(self) -> None:
        striker = PlayerUsageProfile(
            player_id="p9",
            player_name="Striker",
            side="home",
            position="FW",
            shot_share=0.30,
            goal_share=0.35,
            assist_share=0.05,
        )
        projection = project_player_props(_distribution(), striker)

        self.assertAlmostEqual(projection.expected_shots, 13.0 * 0.30, places=3)
        self.assertAlmostEqual(projection.expected_goals, 1.6 * 0.35, places=3)
        self.assertAlmostEqual(
            projection.anytime_scorer_probability, poisson_at_least(1.6 * 0.35, 1), places=3
        )
        self.assertGreater(projection.shots_over_probabilities["1.5"], 0.0)
        self.assertGreater(
            projection.shots_over_probabilities["0.5"], projection.shots_over_probabilities["1.5"]
        )
        self.assertGreater(projection.goal_or_assist_probability, projection.anytime_scorer_probability)

    def test_penalty_taker_gets_scorer_bump(self) -> None:
        base = PlayerUsageProfile(player_id="a", player_name="A", side="home", goal_share=0.25)
        taker = PlayerUsageProfile(player_id="b", player_name="B", side="home", goal_share=0.25, penalty_taker=True)
        base_projection = project_player_props(_distribution(), base)
        taker_projection = project_player_props(_distribution(), taker)
        self.assertGreater(taker_projection.anytime_scorer_probability, base_projection.anytime_scorer_probability)

    def test_goalkeeper_gets_saves_from_opponent_volume(self) -> None:
        keeper = PlayerUsageProfile(
            player_id="gk", player_name="Keeper", side="home", position="GK", is_goalkeeper=True
        )
        projection = project_player_props(_distribution(), keeper)

        # Home keeper faces away shots on target minus away goals.
        self.assertAlmostEqual(projection.expected_saves or 0.0, 3.4 - 1.1, places=3)
        self.assertEqual(projection.anytime_scorer_probability, 0.0)
        self.assertIn("2.5", projection.saves_over_probabilities)
        self.assertGreater(projection.saves_over_probabilities["0.5"], projection.saves_over_probabilities["2.5"])

    def test_build_usage_profiles_normalizes_shares(self) -> None:
        rows = [
            {"player_name": "Striker", "position": "FW", "shots_per90": 3.6, "xg_per90": 0.55, "xa_per90": 0.15},
            {"player_name": "Winger", "position": "FW", "shots_per90": 2.4, "xg_per90": 0.30, "xa_per90": 0.30},
            {"player_name": "Mid", "position": "MF", "shots_per90": 1.2, "xg_per90": 0.12, "xa_per90": 0.25, "expected_minutes_share": 0.5},
            {"player_name": "Keeper", "position": "GK", "shots_per90": 0.0, "xg_per90": 0.0, "xa_per90": 0.0},
        ]
        profiles = build_usage_profiles(rows, side="home", team="ARS")

        self.assertEqual(len(profiles), 4)
        self.assertAlmostEqual(sum(profile.shot_share for profile in profiles), 1.0, places=6)
        self.assertAlmostEqual(sum(profile.goal_share for profile in profiles), 1.0, places=6)
        striker, winger, mid, keeper = profiles
        self.assertGreater(striker.shot_share, winger.shot_share)
        self.assertTrue(keeper.is_goalkeeper)
        # Half-minutes midfielder is share-discounted relative to full rate.
        self.assertLess(mid.shot_share, winger.shot_share)

        projections = project_team_player_props(_distribution(), profiles)
        total_allocated_shots = sum(projection.expected_shots for projection in projections)
        self.assertAlmostEqual(total_allocated_shots, 13.0, places=2)


if __name__ == "__main__":
    unittest.main()
