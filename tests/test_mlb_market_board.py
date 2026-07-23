from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.mlb.cards import _mlb_market_board_rows_for_game
from syndicate.features.mlb.cards import build_mlb_market_board
from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NO_SIM_COVERAGE
from syndicate.features.shared.market_inventory import join_odds_to_sim


class MlbMarketBoardRowsTests(unittest.TestCase):
    def test_bare_odds_moneyline_and_totals_produce_no_coverage_rows(self) -> None:
        # Real captured shape this session: 4 of 5 MLB games on a slate had
        # only a bare odds quote (no recommendation-engine coverage) --
        # every quoted side must still show up, just unscored.
        markets = {
            "ml": {"away_odds": "+250", "home_odds": "-350"},
            "totals": {"line": 8.5, "over_odds": "-120", "under_odds": "-110"},
        }
        odds_rows, sim_rows = _mlb_market_board_rows_for_game(game_pk=824406, markets=markets)
        self.assertEqual(sim_rows, [])
        self.assertEqual(len(odds_rows), 4)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        self.assertEqual(len(inventory), 4)
        for row in inventory:
            self.assertEqual(row["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)
            self.assertTrue(row["is_eligible"])

    def test_recommendation_shaped_moneyline_matches_its_own_side_only(self) -> None:
        # Real captured shape this session: KC @ DET's markets.ml carried a
        # genuine recommendation (selection="home", model_prob=0.695,
        # odds=-229) with no separate away_odds field at all.
        markets = {"ml": {"selection": "home", "model_prob": 0.695, "odds": "-229"}}
        odds_rows, sim_rows = _mlb_market_board_rows_for_game(game_pk=824247, markets=markets)

        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["side"], "home")
        self.assertEqual(len(sim_rows), 1)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_MATCHED)
        self.assertAlmostEqual(inventory[0]["sim_projection"], 0.695)

    def test_totals_with_model_prob_matches(self) -> None:
        markets = {"totals": {"line": 8.5, "over_odds": "-115", "under_odds": "-105", "model_prob": 0.55}}
        odds_rows, sim_rows = _mlb_market_board_rows_for_game(game_pk=1, markets=markets)
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        self.assertEqual(len(inventory), 2)
        for row in inventory:
            self.assertEqual(row["join_status"], JOIN_STATUS_MATCHED)

    def test_no_markets_produces_no_rows(self) -> None:
        odds_rows, sim_rows = _mlb_market_board_rows_for_game(game_pk=1, markets={})
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])


class BuildMlbMarketBoardTests(unittest.TestCase):
    def test_relabels_synthetic_moneyline_market_keys_for_display(self) -> None:
        fake_games = [
            {
                "gamePk": 824247,
                "away": {"abbr": "KC"},
                "home": {"abbr": "DET"},
                "status": {"abstract": "Preview"},
                "detail": "7:10 PM CT",
                "startTime": "2026-07-23T22:41:00Z",
                "markets": {"ml": {"selection": "home", "model_prob": 0.695, "odds": "-229"}},
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload",
            return_value={"games": fake_games},
        ):
            board = build_mlb_market_board("2026-07-23")

        self.assertEqual(board["date"], "2026-07-23")
        self.assertEqual(len(board["games"]), 1)
        game = board["games"][0]
        self.assertEqual(game["matchup"], "KC @ DET")
        self.assertEqual(game["game_state"], "preview")
        self.assertEqual(len(game["rows"]), 1)
        self.assertEqual(game["rows"][0]["market"], "Moneyline")

    def test_game_with_no_markets_still_appears_with_empty_rows(self) -> None:
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "SD"},
                "home": {"abbr": "ATL"},
                "status": {},
                "markets": {},
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload",
            return_value={"games": fake_games},
        ):
            board = build_mlb_market_board("2026-07-23")

        self.assertEqual(len(board["games"]), 1)
        self.assertEqual(board["games"][0]["rows"], [])
        self.assertEqual(board["games"][0]["game_state"], "pregame")


if __name__ == "__main__":
    unittest.main()
