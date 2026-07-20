from __future__ import annotations

import unittest

from syndicate.features.soccer.features.live_lens import apply_red_card_penalty
from syndicate.features.soccer.features.live_lens import build_resume_state
from syndicate.features.soccer.features.live_lens import goal_in_window_probability
from syndicate.features.soccer.features.live_lens import project_live_match
from syndicate.features.soccer.features.live_lens import project_live_player_props


def _live_state(**overrides) -> dict:
    base = {
        "event_id": "e1",
        "home_team": "Home FC",
        "away_team": "Away FC",
        "half": 2,
        "clock_remaining": 900,
        "score_home": 1,
        "score_away": 0,
        "home_red_cards": 0,
        "away_red_cards": 0,
        "home_corners_so_far": 4,
        "away_corners_so_far": 2,
        "player_stats": {
            "h1": {"player_id": "h1", "player_name": "Home Striker", "team": "Home FC", "shots_so_far": 3},
            "a1": {"player_id": "a1", "player_name": "Away Striker", "team": "Away FC", "shots_so_far": 1},
        },
    }
    base.update(overrides)
    return base


_NEUTRAL = {"attack_rating": 0.0, "defense_rating": 0.0}


class RedCardPenaltyTests(unittest.TestCase):
    def test_no_penalty_at_zero_cards(self) -> None:
        rating = {"attack_rating": 0.1, "defense_rating": 0.05}
        self.assertEqual(apply_red_card_penalty(rating, 0), rating)

    def test_penalty_reduces_both_ratings(self) -> None:
        rating = {"attack_rating": 0.1, "defense_rating": 0.05}
        adjusted = apply_red_card_penalty(rating, 1)
        self.assertLess(adjusted["attack_rating"], rating["attack_rating"])
        self.assertLess(adjusted["defense_rating"], rating["defense_rating"])

    def test_penalty_stacks_but_stays_capped(self) -> None:
        rating = {"attack_rating": 0.0, "defense_rating": 0.0}
        one_card = apply_red_card_penalty(rating, 1)
        two_cards = apply_red_card_penalty(rating, 2)
        self.assertLess(two_cards["attack_rating"], one_card["attack_rating"])
        self.assertGreaterEqual(two_cards["attack_rating"], -0.35)


class BuildResumeStateTests(unittest.TestCase):
    def test_carries_score_half_and_clock(self) -> None:
        state = build_resume_state(_live_state())
        self.assertEqual(state.half, 2)
        self.assertEqual(state.clock_remaining, 900)
        self.assertEqual(state.score_home, 1)
        self.assertEqual(state.score_away, 0)
        self.assertEqual(state.home_team, "Home FC")


class ProjectLiveMatchTests(unittest.TestCase):
    def test_projection_is_well_formed(self) -> None:
        proj = project_live_match(_live_state(), home_rating=_NEUTRAL, away_rating=_NEUTRAL, simulations=40)
        self.assertEqual(proj.simulations, 40)
        self.assertAlmostEqual(
            proj.home_win_probability + proj.draw_probability + proj.away_win_probability, 1.0, places=6
        )
        self.assertGreaterEqual(proj.projected_final_home_goals, 1.0)  # already 1-0, can't go below
        self.assertGreaterEqual(proj.projected_home_corners, 4.0)  # already 4 corners, can't go below
        self.assertGreaterEqual(proj.projected_away_corners, 2.0)

    def test_leading_team_with_lead_is_favored(self) -> None:
        proj = project_live_match(
            _live_state(score_home=3, score_away=0, clock_remaining=300),
            home_rating=_NEUTRAL,
            away_rating=_NEUTRAL,
            simulations=60,
        )
        self.assertGreater(proj.home_win_probability, 0.9)

    def test_red_card_flags_reflected_in_output(self) -> None:
        proj = project_live_match(
            _live_state(home_red_cards=1), home_rating=_NEUTRAL, away_rating=_NEUTRAL, simulations=20
        )
        self.assertTrue(proj.home_red_card_applied)
        self.assertFalse(proj.away_red_card_applied)

    def test_red_carded_team_is_disadvantaged_relative_to_no_card(self) -> None:
        even_state = _live_state(score_home=0, score_away=0, clock_remaining=2700)
        carded_state = _live_state(score_home=0, score_away=0, clock_remaining=2700, home_red_cards=1)
        even_proj = project_live_match(even_state, home_rating=_NEUTRAL, away_rating=_NEUTRAL, simulations=150, seed=5)
        carded_proj = project_live_match(carded_state, home_rating=_NEUTRAL, away_rating=_NEUTRAL, simulations=150, seed=5)
        self.assertLess(carded_proj.home_win_probability, even_proj.home_win_probability)


class GoalInWindowProbabilityTests(unittest.TestCase):
    def test_probability_is_bounded(self) -> None:
        p = goal_in_window_probability(
            _live_state(), home_rating=_NEUTRAL, away_rating=_NEUTRAL, window_seconds=600, simulations=40
        )
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_longer_window_gives_higher_or_equal_probability(self) -> None:
        state = _live_state(clock_remaining=1800)
        short = goal_in_window_probability(
            state, home_rating=_NEUTRAL, away_rating=_NEUTRAL, window_seconds=300, simulations=150, seed=3
        )
        long = goal_in_window_probability(
            state, home_rating=_NEUTRAL, away_rating=_NEUTRAL, window_seconds=1200, simulations=150, seed=3
        )
        self.assertGreaterEqual(long, short)

    def test_window_beyond_clock_remaining_is_clamped(self) -> None:
        # Should not raise even though the window exceeds time left.
        p = goal_in_window_probability(
            _live_state(clock_remaining=100),
            home_rating=_NEUTRAL,
            away_rating=_NEUTRAL,
            window_seconds=5000,
            simulations=20,
        )
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)


class ProjectLivePlayerPropsTests(unittest.TestCase):
    def test_already_accumulated_shots_are_included_as_a_floor(self) -> None:
        home_rows = [{"player_id": "h1", "player_name": "Home Striker", "team": "Home FC", "shots_per90": 3.0, "xg_per90": 0.5}]
        away_rows = [{"player_id": "a1", "player_name": "Away Striker", "team": "Away FC", "shots_per90": 2.0, "xg_per90": 0.3}]
        projections = project_live_player_props(
            _live_state(),
            home_rating=_NEUTRAL,
            away_rating=_NEUTRAL,
            home_player_rows=home_rows,
            away_player_rows=away_rows,
            simulations=40,
        )
        by_id = {p.player_id: p for p in projections}
        self.assertEqual(by_id["h1"].shots_so_far, 3)
        self.assertGreaterEqual(by_id["h1"].projected_final_shots, 3.0)
        self.assertEqual(by_id["a1"].shots_so_far, 1)

    def test_shots_over_probability_accounts_for_shots_already_taken(self) -> None:
        # A player already at 3 shots should have near-certain P(over 2.5).
        home_rows = [{"player_id": "h1", "player_name": "Home Striker", "team": "Home FC", "shots_per90": 3.0, "xg_per90": 0.5}]
        projections = project_live_player_props(
            _live_state(),
            home_rating=_NEUTRAL,
            away_rating=_NEUTRAL,
            home_player_rows=home_rows,
            away_player_rows=[],
            simulations=40,
        )
        striker = projections[0]
        self.assertEqual(striker.shots_over_probabilities["2.5"], 1.0)

    def test_empty_player_rows_produce_no_projections(self) -> None:
        projections = project_live_player_props(
            _live_state(), home_rating=_NEUTRAL, away_rating=_NEUTRAL, home_player_rows=[], away_player_rows=[], simulations=10
        )
        self.assertEqual(projections, ())


if __name__ == "__main__":
    unittest.main()
