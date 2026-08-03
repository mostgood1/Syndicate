from __future__ import annotations

import math
import unittest

from syndicate.features.wnba.cards import _line_from_recommendation_pick
from syndicate.features.wnba.cards import _source_betting
from syndicate.features.wnba.cards import _source_game_market_recommendations
from syndicate.features.wnba.cards import _stamp_game_level_projected


# Real production-shaped picks (recommendations_slate_2026-07-29.json).
ATS_PICK = {
    "market": "ATS",
    "team": "Golden State Valkyries",
    "display_pick": "Golden State Valkyries -5.0",
    "selection": "Golden State Valkyries",
    "price": -110.0,
    "score": 14.35,
    "ev_pct": 14.35,
    "win_prob": 0.66731,
    "p_win": 0.66731,
    "basketball_summary": "Model margin 9.3 vs market -5.0",
    "matchup": "GSV @ PHX",
}
TOTAL_PICK = {
    "market": "TOTAL",
    "team": "Total",
    "display_pick": "Over 156.5",
    "selection": "Over",
    "price": -110.0,
    "score": 4.03,
    "ev_pct": 4.03,
    "win_prob": 0.56411,
    "p_win": 0.56411,
    "basketball_summary": "Model total 160.5 vs line 156.5",
    "matchup": "GSV @ PHX",
}
PROP_PICK = {
    "market": "PROPS",
    "team": "GSV",
    "display_pick": "Gabby Williams OVER 1.5",
    "selection": "OVER 1.5",
    "projection": 1.98,
    "projected": 1.98,
    "odds": -118.0,
    "price": -118.0,
    "score": 18.9,
    "ev_pct": 18.9,
    "win_prob": 0.5413,
    "p_win": 0.5413,
    "matchup": "GSV @ PHX",
}


class LineFromRecommendationPickTests(unittest.TestCase):
    def test_ats_line_parsed_from_display_pick(self) -> None:
        self.assertEqual(_line_from_recommendation_pick(ATS_PICK), -5.0)

    def test_total_line_parsed_from_display_pick(self) -> None:
        self.assertEqual(_line_from_recommendation_pick(TOTAL_PICK), 156.5)


class SourceGameMarketRecommendationsTests(unittest.TestCase):
    # #131 follow-up, confirmed live 2026-07-29: WNBA (and, via the shared
    # home.py consumer, MLB) game-level board candidates (Moneyline/Total/
    # ATS) showed projected="-" and line=None for every pregame and live
    # game -- the same class of gap already fixed for props, just one layer
    # up in the game-market pipeline. recommendations_slate rows never carry
    # a structured "line" field for ANY pick type, and only PROPS picks carry
    # a structured "projection" -- ATS/Total picks only have the model number
    # embedded as prose in basketball_summary, backed by a real numeric
    # `score` (margin_mean/total_mean) one call-frame up that was computed
    # but never threaded onto the row.
    def test_line_populated_for_ats_and_total(self) -> None:
        rows = _source_game_market_recommendations([ATS_PICK, TOTAL_PICK])
        by_label = {row["market_label"]: row for row in rows}
        self.assertEqual(by_label["ATS"]["line"], -5.0)
        self.assertEqual(by_label["ATS"]["market_line"], -5.0)
        self.assertEqual(by_label["TOTAL"]["line"], 156.5)

    def test_projected_populated_directly_for_props(self) -> None:
        rows = _source_game_market_recommendations([PROP_PICK])
        self.assertEqual(rows[0]["projected"], 1.98)

    def test_projected_left_blank_for_ats_total_until_stamped(self) -> None:
        # This function alone has no access to the game's sim `score` dict --
        # confirms the split responsibility is deliberate, not an oversight.
        rows = _source_game_market_recommendations([ATS_PICK, TOTAL_PICK])
        self.assertTrue(all(row["projected"] is None for row in rows))

    def test_player_prop_market_codes_excluded_to_avoid_board_duplication(self) -> None:
        # Confirmed live 2026-08-01: recommendations_slate's per-game "picks"
        # list mixes real game markets (ATS/TOTAL) with player-prop picks
        # coded by stat (pts/reb/ast/pra/pa/pr/ra/threes/blk/stl/bs) -- this
        # function used to convert every one of them into a "game market
        # recommendation" row with no filter, duplicating whatever
        # prop_recommendations (a separate artifact) already surfaced
        # correctly for the same player/market/line. A player-prop pick must
        # never reach this list.
        player_prop_picks = [
            {**PROP_PICK, "market": code}
            for code in ("pts", "reb", "ast", "pra", "pa", "pr", "ra", "threes", "blk", "stl", "bs")
        ]
        rows = _source_game_market_recommendations([ATS_PICK, TOTAL_PICK, *player_prop_picks])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["market_label"] for row in rows}, {"ATS", "TOTAL"})


class StampGameLevelProjectedTests(unittest.TestCase):
    def test_stamps_margin_mean_onto_ats_and_total_mean_onto_total(self) -> None:
        rows = _source_game_market_recommendations([ATS_PICK, TOTAL_PICK])
        _stamp_game_level_projected(rows, {"margin_mean": 9.3, "total_mean": 160.5})
        by_label = {row["market_label"]: row for row in rows}
        self.assertEqual(by_label["ATS"]["projected"], 9.3)
        self.assertEqual(by_label["TOTAL"]["projected"], 160.5)

    def test_does_not_overwrite_an_already_populated_projected(self) -> None:
        rows = _source_game_market_recommendations([PROP_PICK])
        _stamp_game_level_projected(rows, {"margin_mean": 9.3, "total_mean": 160.5})
        self.assertEqual(rows[0]["projected"], 1.98)

    def test_missing_score_leaves_projected_none_without_crashing(self) -> None:
        rows = _source_game_market_recommendations([ATS_PICK, TOTAL_PICK])
        _stamp_game_level_projected(rows, {})
        self.assertTrue(all(row["projected"] is None for row in rows))


class SourceBettingProjectedFieldsTests(unittest.TestCase):
    # Same field previously computed only to derive the market line itself
    # (home_spread/total) and then discarded -- home.py's Moneyline/Total
    # candidate builder reads betting.get("projected_total") directly now.
    def test_projected_total_and_margin_exposed_even_when_book_line_present(self) -> None:
        betting = _source_betting({"home_spread": -3.5, "total": 165.5, "margin_mean": 9.3, "total_mean": 160.5})
        self.assertEqual(betting["projected_margin"], 9.3)
        self.assertEqual(betting["projected_total"], 160.5)
        # Real book line is untouched by the presence of a model projection.
        self.assertEqual(betting["home_spread"], -3.5)
        self.assertEqual(betting["total"], 165.5)

    def test_projected_total_ignored_when_degenerate(self) -> None:
        betting = _source_betting({"total_mean": 0.5})
        self.assertIsNone(betting["projected_total"])


class SourceBettingProbabilityPriorityTests(unittest.TestCase):
    # 2026-08-02 end-to-end assessment: the fallback chain used to try the
    # book's own vig-inclusive moneyline (implied probability) BEFORE the
    # sim-margin transform, so whenever a moneyline existed the "model"
    # probability WAS the market price and edge was structurally zero.
    def test_sim_margin_probability_outranks_market_implied(self) -> None:
        betting = _source_betting({"home_ml": "-200", "away_ml": "170", "pred_margin": "1.0"})
        expected = 1.0 / (1.0 + math.exp(-1.0 / 6.5))
        self.assertAlmostEqual(betting["p_home_win"], expected, places=9)
        self.assertAlmostEqual(betting["p_away_win"], 1.0 - expected, places=9)
        # The old (buggy) value this must never regress to.
        self.assertNotAlmostEqual(betting["p_home_win"], 200.0 / 300.0, places=3)

    def test_explicit_probability_columns_still_outrank_everything(self) -> None:
        betting = _source_betting({"p_home_win": "0.61", "home_ml": "-200", "pred_margin": "8.0"})
        self.assertAlmostEqual(betting["p_home_win"], 0.61, places=9)
        self.assertAlmostEqual(betting["p_away_win"], 0.39, places=9)

    def test_market_implied_is_the_last_resort_without_any_sim_signal(self) -> None:
        betting = _source_betting({"home_ml": "-200", "away_ml": "170"})
        self.assertAlmostEqual(betting["p_home_win"], 200.0 / 300.0, places=9)
        self.assertAlmostEqual(betting["p_away_win"], 100.0 / 270.0, places=9)

    def test_margin_mean_alias_feeds_the_sim_branch_too(self) -> None:
        betting = _source_betting({"home_ml": "-200", "margin_mean": "-2.0"})
        expected = 1.0 / (1.0 + math.exp(2.0 / 6.5))
        self.assertAlmostEqual(betting["p_home_win"], expected, places=9)


class SourceBettingSidePriceTests(unittest.TestCase):
    def test_per_side_prices_flow_through_from_csv_columns(self) -> None:
        betting = _source_betting(
            {
                "home_spread": "-4.5",
                "away_spread": "4.5",
                "total": "164.5",
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
        self.assertEqual(betting["away_spread"], 4.5)

    def test_old_csv_without_price_columns_leaves_prices_none(self) -> None:
        betting = _source_betting({"home_spread": "-4.5", "total": "164.5"})
        self.assertIsNone(betting["home_spread_price"])
        self.assertIsNone(betting["away_spread_price"])
        self.assertIsNone(betting["total_over_price"])
        self.assertIsNone(betting["total_under_price"])
        # away_spread still derived from the home line for display parity.
        self.assertEqual(betting["away_spread"], 4.5)


if __name__ == "__main__":
    unittest.main()
