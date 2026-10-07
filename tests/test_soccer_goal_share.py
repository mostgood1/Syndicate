"""Each soccer player-prop row carries the inputs it was allocated from (lane soccer-goal-allocation, 2026-10-07).

Builds stored only outputs and the per-league player files are overwritten in place, so the goal-share fit
(H40) could not be graded as-of. `usage_inputs` makes every future build gradable against what the sim knew
before the match.
"""
from __future__ import annotations

from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.player_props import (
    build_usage_profiles,
    project_team_player_props,
)


def _distribution() -> MatchDistributionSummary:
    return MatchDistributionSummary(
        simulations=1000, home_win_probability=0.45, draw_probability=0.27, away_win_probability=0.28,
        mean_home_goals=1.6, mean_away_goals=1.1, mean_total=2.7, mean_margin=0.5, over_2_5_probability=0.52,
        both_teams_scored_probability=0.55, scoreline_probabilities={"1-0": 0.12}, mean_home_shots=13.0,
        mean_away_shots=10.0, mean_home_shots_on_target=4.5, mean_away_shots_on_target=3.4,
        mean_home_corners=6.0, mean_away_corners=5.0)


def _rows():
    return [
        {"player_id": "understat_1", "player_name": "Striker", "position": "F", "season": 2026, "source": "understat",
         "minutes": 430.0, "games": 5, "xg_per90": 0.45, "shots_per90": 3.1, "expected_minutes_share": 0.95},
        {"player_id": "understat_2", "player_name": "Fringe Defender", "position": "D", "season": 2026,
         "source": "understat", "minutes": 20.0, "games": 2, "xg_per90": 0.5156, "shots_per90": 3.76,
         "expected_minutes_share": 0.1111},
    ]


def test_reachability_every_row_carries_its_allocation_inputs_through_the_real_build_path():
    profiles = build_usage_profiles(_rows(), side="home", team="Home FC")
    rows = [p.to_dict() for p in project_team_player_props(_distribution(), profiles)]
    for row, raw, profile in zip(rows, _rows(), profiles):
        inputs = row["usage_inputs"]
        assert inputs["goal_share"] == round(profile.goal_share, 6)
        assert inputs["on_pitch_goal_share"] == round(profile.on_pitch_goal_share, 6)
        assert inputs["start_probability"] == round(profile.start_probability, 6)
        for key in ("season", "source", "minutes", "games", "xg_per90", "shots_per90"):
            assert inputs[key] == raw[key], key


def test_the_goal_shares_in_the_inputs_sum_to_one_per_side():
    profiles = build_usage_profiles(_rows(), side="home", team="Home FC")
    rows = [p.to_dict() for p in project_team_player_props(_distribution(), profiles)]
    assert abs(sum(r["usage_inputs"]["goal_share"] for r in rows) - 1.0) < 1e-5


def test_a_missing_raw_field_is_absent_not_zero():
    raw = [{"player_id": "x", "player_name": "No Rates", "position": "M", "expected_minutes_share": 0.5}]
    row = project_team_player_props(_distribution(), build_usage_profiles(raw, side="away"))[0].to_dict()
    assert "xg_per90" not in row["usage_inputs"] and "minutes" not in row["usage_inputs"]
