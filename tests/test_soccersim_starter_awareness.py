from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles
from syndicate.features.soccer.sim_engine.soccersim.player_props import project_team_player_props


def _rows() -> list[dict]:
    return [
        {"player_id": "starter1", "player_name": "Starter Striker", "shots_per90": 3.0, "xg_per90": 0.5},
        {"player_id": "bench1", "player_name": "Bench Forward", "shots_per90": 2.5, "xg_per90": 0.4},
        {"player_id": "bench2", "player_name": "Bench Mid", "shots_per90": 1.0, "xg_per90": 0.1},
    ]


def _distribution() -> MatchDistributionSummary:
    return MatchDistributionSummary(
        simulations=500,
        home_win_probability=0.45,
        draw_probability=0.27,
        away_win_probability=0.28,
        mean_home_goals=1.6,
        mean_away_goals=1.1,
        mean_total=2.7,
        mean_margin=0.5,
        over_2_5_probability=0.52,
        both_teams_scored_probability=0.55,
        scoreline_probabilities={},
        mean_home_shots=13.0,
        mean_away_shots=10.0,
        mean_home_shots_on_target=4.5,
        mean_away_shots_on_target=3.4,
    )


class StarterAwarenessTests(unittest.TestCase):
    def test_no_lineup_matches_season_rate_behavior(self) -> None:
        profiles = build_usage_profiles(_rows(), side="home")
        # Unchanged from pre-starter-awareness behavior: shares track raw
        # per-90 rates directly since no minutes-share/starter info exists.
        self.assertAlmostEqual(profiles[0].shot_share, 3.0 / 6.5, places=3)

    def test_explicit_starters_concentrate_share(self) -> None:
        baseline = build_usage_profiles(_rows(), side="home")
        lineup = build_usage_profiles(_rows(), side="home", starters={"starter1"})

        self.assertGreater(lineup[0].shot_share, baseline[0].shot_share)
        self.assertLess(lineup[1].shot_share, baseline[1].shot_share)
        self.assertLess(lineup[2].shot_share, baseline[2].shot_share)
        # Shares still normalize to 1.0 across the squad.
        self.assertAlmostEqual(sum(p.shot_share for p in lineup), 1.0, places=6)

    def test_name_based_key_when_no_player_id(self) -> None:
        rows = [dict(row) for row in _rows()]
        for row in rows:
            del row["player_id"]
        lineup = build_usage_profiles(rows, side="home", starters={"name:starter striker"})
        self.assertGreater(lineup[0].shot_share, lineup[1].shot_share)

    def test_is_starter_row_flag_auto_detected(self) -> None:
        rows = _rows()
        rows[0]["is_starter"] = True
        rows[1]["is_starter"] = False
        rows[2]["is_starter"] = False
        auto = build_usage_profiles(rows, side="home")
        explicit = build_usage_profiles(_rows(), side="home", starters={"starter1"})
        self.assertAlmostEqual(auto[0].shot_share, explicit[0].shot_share, places=4)

    def test_bench_player_still_gets_nonzero_projection(self) -> None:
        lineup = build_usage_profiles(_rows(), side="home", starters={"starter1"})
        projections = project_team_player_props(_distribution(), lineup)
        bench_projection = next(p for p in projections if p.player_id == "bench1")
        self.assertGreater(bench_projection.expected_shots, 0.0)

    def test_bench_minutes_share_is_configurable(self) -> None:
        loose = build_usage_profiles(_rows(), side="home", starters={"starter1"}, bench_minutes_share=0.5)
        tight = build_usage_profiles(_rows(), side="home", starters={"starter1"}, bench_minutes_share=0.05)
        self.assertGreater(loose[1].shot_share, tight[1].shot_share)


if __name__ == "__main__":
    unittest.main()
