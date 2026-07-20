from __future__ import annotations

import unittest

from syndicate.features.soccer.features.market_anchoring import anchor_ratings_to_market
from syndicate.features.soccer.features.market_anchoring import anchor_team_ratings
from syndicate.features.soccer.features.market_anchoring import devig_decimal_odds
from syndicate.features.soccer.features.market_anchoring import simulated_home_win_probability
from syndicate.features.soccer.features.market_anchoring import solve_market_rating_shift


class DevigTests(unittest.TestCase):
    def test_devig_removes_the_overround(self) -> None:
        probabilities = devig_decimal_odds({"home": 2.0, "draw": 3.4, "away": 4.0})
        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=6)
        # Raw implied probabilities (1/price) summed to > 1 before devig.
        raw_total = 1 / 2.0 + 1 / 3.4 + 1 / 4.0
        self.assertGreater(raw_total, 1.0)

    def test_devig_ignores_invalid_prices(self) -> None:
        probabilities = devig_decimal_odds({"home": 2.0, "draw": 0.0, "away": -1.0})
        self.assertEqual(set(probabilities), {"home"})
        self.assertAlmostEqual(probabilities["home"], 1.0)

    def test_devig_empty_input(self) -> None:
        self.assertEqual(devig_decimal_odds({}), {})


class RatingShiftSolverTests(unittest.TestCase):
    def test_shift_is_near_zero_when_target_matches_model_baseline(self) -> None:
        # The model's own neutral-rating home win probability is below 0.5
        # by design (draws split off a chunk of both sides' probability
        # mass in a three-outcome market) -- so the self-consistent
        # zero-shift point is the model's baseline, not literally 0.5.
        neutral = {"attack_rating": 0.0, "defense_rating": 0.0}
        baseline = simulated_home_win_probability(home_rating=neutral, away_rating=neutral, simulations=300, seed=7)
        self.assertLess(baseline, 0.5)  # confirms the three-outcome effect this test relies on

        shift = solve_market_rating_shift(
            home_rating=neutral, away_rating=neutral, market_home_win_probability=baseline, simulations=100, seed=7
        )
        self.assertAlmostEqual(shift, 0.0, delta=0.05)

    def test_shift_is_positive_when_market_favors_home(self) -> None:
        neutral = {"attack_rating": 0.0, "defense_rating": 0.0}
        shift = solve_market_rating_shift(
            home_rating=neutral, away_rating=neutral, market_home_win_probability=0.70, simulations=120
        )
        self.assertGreater(shift, 0.03)

    def test_shift_is_negative_when_market_favors_away(self) -> None:
        neutral = {"attack_rating": 0.0, "defense_rating": 0.0}
        shift = solve_market_rating_shift(
            home_rating=neutral, away_rating=neutral, market_home_win_probability=0.15, simulations=120
        )
        self.assertLess(shift, -0.03)


class AnchorTeamRatingsTests(unittest.TestCase):
    def test_zero_weight_leaves_ratings_untouched(self) -> None:
        home = {"attack_rating": 0.05, "defense_rating": 0.02}
        away = {"attack_rating": -0.05, "defense_rating": 0.01}
        anchored_home, anchored_away = anchor_team_ratings(
            home, away, market_home_win_probability=0.9, weight=0.0
        )
        self.assertEqual(anchored_home, home)
        self.assertEqual(anchored_away, away)

    def test_full_weight_moves_toward_market_favorite(self) -> None:
        home = {"attack_rating": 0.0, "defense_rating": 0.0}
        away = {"attack_rating": 0.0, "defense_rating": 0.0}
        anchored_home, anchored_away = anchor_team_ratings(
            home, away, market_home_win_probability=0.75, weight=1.0, simulations=120
        )
        self.assertGreater(anchored_home["attack_rating"], 0.0)
        self.assertLess(anchored_away["attack_rating"], 0.0)
        self.assertIn("market_shift_applied", anchored_home)

    def test_partial_weight_is_between_zero_and_full(self) -> None:
        home = {"attack_rating": 0.0, "defense_rating": 0.0}
        away = {"attack_rating": 0.0, "defense_rating": 0.0}
        full_home, _ = anchor_team_ratings(home, away, market_home_win_probability=0.75, weight=1.0, simulations=120)
        half_home, _ = anchor_team_ratings(home, away, market_home_win_probability=0.75, weight=0.5, simulations=120)
        self.assertGreater(half_home["attack_rating"], 0.0)
        self.assertLess(half_home["attack_rating"], full_home["attack_rating"])


class AnchorRatingsToMarketTests(unittest.TestCase):
    def test_fixtures_without_market_odds_are_untouched(self) -> None:
        ratings = {"Arsenal": {"attack_rating": 0.1, "defense_rating": 0.05}}
        result = anchor_ratings_to_market(ratings, [{"home_team": "Arsenal", "away_team": "Liverpool"}], weight=0.5)
        self.assertEqual(result["Arsenal"], ratings["Arsenal"])

    def test_fixtures_with_direct_probability_are_anchored(self) -> None:
        ratings = {
            "Arsenal": {"attack_rating": 0.0, "defense_rating": 0.0},
            "Liverpool": {"attack_rating": 0.0, "defense_rating": 0.0},
        }
        fixtures = [
            {
                "home_team": "Arsenal",
                "away_team": "Liverpool",
                "market_odds": {"home_win_probability": 0.70},
            }
        ]
        result = anchor_ratings_to_market(ratings, fixtures, weight=0.5, simulations=120)
        self.assertGreater(result["Arsenal"]["attack_rating"], 0.0)
        self.assertLess(result["Liverpool"]["attack_rating"], 0.0)

    def test_fixtures_with_moneyline_odds_are_devigged_and_anchored(self) -> None:
        ratings = {
            "Arsenal": {"attack_rating": 0.0, "defense_rating": 0.0},
            "Liverpool": {"attack_rating": 0.0, "defense_rating": 0.0},
        }
        fixtures = [
            {
                "home_team": "Arsenal",
                "away_team": "Liverpool",
                "market_odds": {"moneyline": {"home": 1.5, "draw": 4.5, "away": 6.0}},
            }
        ]
        result = anchor_ratings_to_market(ratings, fixtures, weight=0.5, simulations=120)
        self.assertGreater(result["Arsenal"]["attack_rating"], 0.0)

    def test_missing_team_in_ratings_defaults_to_neutral(self) -> None:
        ratings = {"Arsenal": {"attack_rating": 0.1, "defense_rating": 0.05}}
        fixtures = [
            {
                "home_team": "Arsenal",
                "away_team": "Promoted FC",
                "market_odds": {"home_win_probability": 0.6},
            }
        ]
        result = anchor_ratings_to_market(ratings, fixtures, weight=0.4, simulations=100)
        self.assertIn("Promoted FC", result)
        self.assertLess(result["Promoted FC"]["attack_rating"], 0.0)


if __name__ == "__main__":
    unittest.main()
