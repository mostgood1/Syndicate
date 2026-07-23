from __future__ import annotations

import unittest

from syndicate.features.shared.basketball_market_board import basketball_game_state
from syndicate.features.shared.basketball_market_board import basketball_market_board_rows_for_game
from syndicate.features.shared.basketball_market_board import build_basketball_market_board
from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NO_SIM_COVERAGE
from syndicate.features.shared.market_inventory import join_odds_to_sim


class BasketballGameStateTests(unittest.TestCase):
    def test_nba_bare_string_status(self) -> None:
        # Real captured shape: NBA's game["status"] is a plain string.
        self.assertEqual(basketball_game_state({"status": "Live"}), "live")
        self.assertEqual(basketball_game_state({"status": "Final"}), "final")
        self.assertEqual(basketball_game_state({"status": "Scheduled"}), "pregame")

    def test_wnba_status_dict(self) -> None:
        # Real captured shape: WNBA's game["status"] is a dict carrying the
        # same vocabulary under a "status" key.
        self.assertEqual(basketball_game_state({"status": {"status": "Live"}}), "live")
        self.assertEqual(basketball_game_state({"status": {"status": "Final"}}), "final")

    def test_missing_status_defaults_to_pregame(self) -> None:
        self.assertEqual(basketball_game_state({}), "pregame")


class BasketballMarketBoardRowsTests(unittest.TestCase):
    def test_moneyline_only_when_spread_and_total_prices_are_absent(self) -> None:
        # Real captured shape: game_cards_{date}.csv never carries spread
        # or total book prices for NBA/WNBA today -- only moneyline has a
        # genuine quoted price.
        betting = {
            "home_ml": -180.0,
            "away_ml": 155.0,
            "home_spread": -4.5,
            "away_spread": 4.5,
            "total": 165.5,
            "p_home_win": 0.64,
            "p_away_win": 0.36,
            "p_home_cover": 0.5,
            "p_away_cover": 0.5,
            "p_total_over": 0.5,
            "p_total_under": 0.5,
        }
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting=betting, prop_recommendations={})
        self.assertEqual(len(odds_rows), 2)
        self.assertEqual({row["market"] for row in odds_rows}, {"moneyline_home", "moneyline_away"})
        self.assertEqual(len(sim_rows), 2)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            self.assertEqual(row["join_status"], JOIN_STATUS_MATCHED)

    def test_spread_and_total_rows_appear_once_a_real_price_exists(self) -> None:
        betting = {
            "home_spread": -4.5,
            "away_spread": 4.5,
            "home_spread_price": -110.0,
            "away_spread_price": -110.0,
            "p_home_cover": 0.52,
            "p_away_cover": 0.48,
            "total": 165.5,
            "total_over_price": -105.0,
            "total_under_price": -115.0,
            "p_total_over": 0.55,
            "p_total_under": 0.45,
        }
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting=betting, prop_recommendations={})
        markets = {row["market"] for row in odds_rows}
        self.assertEqual(markets, {"spread_home", "spread_away", "total"})
        self.assertEqual(len(odds_rows), 4)  # total has both over+under
        self.assertEqual(len(sim_rows), 4)

    def test_prop_row_uses_player_field_and_stat_display_label(self) -> None:
        # Real captured shape this session: cards_props_snapshot entries
        # carry player/market/side/line/price/p_win/edge.
        prop_recommendations = {
            "away": [
                {
                    "player": "Miles McBride",
                    "team": "NYK",
                    "opponent": "SAS",
                    "market": "threes",
                    "side": "OVER",
                    "line": 0.5,
                    "price": -105.0,
                    "edge": 0.4534,
                    "ev_pct": 88.5,
                    "p_win": 1.0,
                    "tier": "High",
                }
            ],
            "home": [],
        }
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting={}, prop_recommendations=prop_recommendations)
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["entity"], "Miles McBride")
        self.assertEqual(odds_rows[0]["market"], "Threes")
        self.assertEqual(odds_rows[0]["side"], "over")
        self.assertEqual(odds_rows[0]["market_type"], "prop")
        self.assertEqual(len(sim_rows), 1)
        self.assertAlmostEqual(sim_rows[0]["sim_projection"], 1.0)  # p_win preferred over edge

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_MATCHED)

    def test_prop_row_falls_back_to_edge_when_p_win_absent(self) -> None:
        prop_recommendations = {"away": [{"player": "Someone", "market": "reb", "side": "under", "line": 6.5, "price": -110.0, "edge": 0.12}]}
        _, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting={}, prop_recommendations=prop_recommendations)
        self.assertAlmostEqual(sim_rows[0]["sim_projection"], 0.12)

    def test_props_missing_player_or_invalid_side_are_skipped(self) -> None:
        prop_recommendations = {
            "away": [
                {"player": "", "market": "pts", "side": "over", "price": -110.0},
                {"player": "Nobody Push", "market": "pts", "side": "push", "price": -110.0},
            ]
        }
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting={}, prop_recommendations=prop_recommendations)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_no_data_produces_no_rows(self) -> None:
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting=None, prop_recommendations=None)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])


class BuildBasketballMarketBoardTests(unittest.TestCase):
    def test_relabels_synthetic_market_keys_and_reports_game_state(self) -> None:
        games = [
            {
                "gamePk": "0022600123",
                "away": {"abbr": "SAS"},
                "home": {"abbr": "NYK"},
                "status": "Live",
                "detail": "Q3 4:12",
                "betting": {"home_ml": -180.0, "away_ml": 155.0, "p_home_win": 0.64, "p_away_win": 0.36},
                "prop_recommendations": {
                    "away": [{"player": "Miles McBride", "market": "threes", "side": "over", "line": 0.5, "price": -105.0, "p_win": 1.0}],
                    "home": [],
                },
            }
        ]
        board = build_basketball_market_board(sport_slug="nba", selected_date="2026-07-23", games=games)

        self.assertEqual(board["sport"], "nba")
        self.assertEqual(len(board["games"]), 1)
        game = board["games"][0]
        self.assertEqual(game["matchup"], "SAS @ NYK")
        self.assertEqual(game["game_state"], "live")
        rows = game["rows"]
        self.assertEqual(len(rows), 3)
        by_type = {row["market_type"]: row for row in rows}
        self.assertEqual(by_type["game"]["market"], "Moneyline")
        self.assertEqual(by_type["prop"]["market"], "Threes")
        self.assertEqual(by_type["prop"]["entity"], "Miles McBride")

    def test_game_with_no_betting_or_props_still_appears_with_empty_rows(self) -> None:
        games = [{"gamePk": "1", "away": {"abbr": "SAS"}, "home": {"abbr": "NYK"}, "status": "Scheduled"}]
        board = build_basketball_market_board(sport_slug="wnba", selected_date="2026-07-23", games=games)
        self.assertEqual(len(board["games"]), 1)
        self.assertEqual(board["games"][0]["rows"], [])
        self.assertEqual(board["games"][0]["game_state"], "pregame")

    def test_no_coverage_row_when_odds_exist_without_model(self) -> None:
        games = [
            {
                "gamePk": "1",
                "away": {"abbr": "SAS"},
                "home": {"abbr": "NYK"},
                "status": "Scheduled",
                "betting": {"home_ml": -180.0, "away_ml": 155.0},
            }
        ]
        board = build_basketball_market_board(sport_slug="nba", selected_date="2026-07-23", games=games)
        rows = board["games"][0]["rows"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)


if __name__ == "__main__":
    unittest.main()
