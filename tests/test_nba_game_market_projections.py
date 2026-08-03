from __future__ import annotations

import math
import unittest

from syndicate.features.nba.cards import _game_from_row


def _betting_for_row(row: dict[str, str], *, sim_index: dict | None = None) -> dict:
    game = _game_from_row(
        {"home_team": "Boston Celtics", "visitor_team": "New York Knicks", "home_tri": "BOS", "away_tri": "NYK", **row},
        idx=1,
        selected_date="2026-05-22",
        rec_index={},
        sim_index=sim_index or {},
        props_index={},
    )
    return game["betting"]


class GameFromRowProbabilityPriorityTests(unittest.TestCase):
    # Port of the WNBA _source_betting fix (2026-08-02 end-to-end
    # assessment): the old derivation used the book's own vig-inclusive
    # moneyline (implied probability) unconditionally, so whenever a
    # moneyline existed the "model" probability WAS the market price and
    # edge was structurally zero.
    def test_sim_margin_probability_outranks_market_implied(self) -> None:
        betting = _betting_for_row({"home_ml": "-200", "away_ml": "170", "pred_margin": "1.0"})
        expected = 1.0 / (1.0 + math.exp(-1.0 / 6.5))
        self.assertAlmostEqual(betting["p_home_win"], expected, places=9)
        self.assertAlmostEqual(betting["p_away_win"], 1.0 - expected, places=9)
        # The old (buggy) normalized market-implied value this must never
        # regress to.
        old_market_value = (200.0 / 300.0) / ((200.0 / 300.0) + (100.0 / 270.0))
        self.assertNotAlmostEqual(betting["p_home_win"], old_market_value, places=3)

    def test_sim_detail_margin_mean_outranks_market_implied_too(self) -> None:
        sim_index = {("BOS", "NYK"): {"sim": {"score": {"margin_mean": -2.0}}}}
        betting = _betting_for_row({"home_ml": "-200", "away_ml": "170"}, sim_index=sim_index)
        expected = 1.0 / (1.0 + math.exp(2.0 / 6.5))
        self.assertAlmostEqual(betting["p_home_win"], expected, places=9)

    def test_market_implied_is_the_last_resort_without_any_sim_signal(self) -> None:
        betting = _betting_for_row({"home_ml": "-200", "away_ml": "170"})
        home_implied = 200.0 / 300.0
        away_implied = 100.0 / 270.0
        self.assertAlmostEqual(betting["p_home_win"], home_implied / (home_implied + away_implied), places=9)
        self.assertAlmostEqual(betting["p_away_win"], away_implied / (home_implied + away_implied), places=9)


class GameFromRowCoverAndTotalProbabilityTests(unittest.TestCase):
    def test_cover_and_total_probabilities_derive_from_sim_means(self) -> None:
        betting = _betting_for_row(
            {
                "home_spread": "-4.5",
                "away_spread": "4.5",
                "total": "218.5",
                "pred_margin": "6.0",
                "pred_total": "220.0",
            }
        )
        expected_cover = 1.0 / (1.0 + math.exp(-(6.0 + (-4.5)) / 7.5))
        self.assertAlmostEqual(betting["p_home_cover"], expected_cover, places=9)
        self.assertAlmostEqual(betting["p_away_cover"], 1.0 - expected_cover, places=9)
        expected_over = 1.0 / (1.0 + math.exp(-(220.0 - 218.5) / 10.5))
        self.assertAlmostEqual(betting["p_total_over"], expected_over, places=9)
        self.assertAlmostEqual(betting["p_total_under"], 1.0 - expected_over, places=9)

    def test_cover_and_total_probabilities_are_none_without_sim_means(self) -> None:
        # Not the old fabricated coin-flip 0.5: with no model margin/total the
        # probabilities must be None so basketball_market_board drops the row
        # instead of scoring a structurally zero edge.
        betting = _betting_for_row({"home_spread": "-4.5", "away_spread": "4.5", "total": "218.5"})
        self.assertIsNone(betting["p_home_cover"])
        self.assertIsNone(betting["p_away_cover"])
        self.assertIsNone(betting["p_total_over"])
        self.assertIsNone(betting["p_total_under"])


class GameFromRowSidePriceTests(unittest.TestCase):
    def test_per_side_prices_flow_through_from_csv_columns(self) -> None:
        betting = _betting_for_row(
            {
                "home_spread": "-4.5",
                "away_spread": "4.5",
                "total": "218.5",
                "home_spread_price": "-108",
                "away_spread_price": "-112",
                "total_over_price": "-105",
                "total_under_price": "-115",
            }
        )
        self.assertEqual(betting["home_spread_price"], -108.0)
        self.assertEqual(betting["away_spread_price"], -112.0)
        self.assertEqual(betting["total_over_price"], -105.0)
        self.assertEqual(betting["total_under_price"], -115.0)

    def test_old_csv_without_price_columns_leaves_prices_none(self) -> None:
        betting = _betting_for_row({"home_spread": "-4.5", "total": "218.5"})
        self.assertIsNone(betting["home_spread_price"])
        self.assertIsNone(betting["away_spread_price"])
        self.assertIsNone(betting["total_over_price"])
        self.assertIsNone(betting["total_under_price"])


if __name__ == "__main__":
    unittest.main()
