from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf.cards import _NCAAF_MARKET_BOARD_DISPLAY_LABELS
from syndicate.features.ncaaf.cards import _ncaaf_cover_probability
from syndicate.features.ncaaf.cards import _ncaaf_market_board_rows_for_game
from syndicate.features.ncaaf.cards import build_ncaaf_market_board
from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NO_SIM_COVERAGE
from syndicate.features.shared.market_inventory import join_odds_to_sim


class NcaafCoverProbabilityTests(unittest.TestCase):
    def test_no_stdev_returns_none(self) -> None:
        self.assertIsNone(_ncaaf_cover_probability(line=6.5, mean=4.2, stdev=None))
        self.assertIsNone(_ncaaf_cover_probability(line=6.5, mean=4.2, stdev=0))

    def test_mean_above_line_favors_over_half(self) -> None:
        prob = _ncaaf_cover_probability(line=0.0, mean=7.0, stdev=13.5)
        self.assertGreater(prob, 0.5)
        self.assertLess(prob, 1.0)


class NcaafMarketBoardRowsTests(unittest.TestCase):
    def test_all_markets_present(self) -> None:
        odds_rows, sim_rows = _ncaaf_market_board_rows_for_game(
            game_id="g1",
            market_margin=-6.5,
            market_total=49.5,
            home_moneyline=-235,
            away_moneyline=195,
            model_margin=-4.2,
            model_total=51.0,
            model_margin_stdev=13.5,
            model_total_stdev=9.0,
            home_win_probability=0.68,
        )
        odds_markets = sorted(row["market"] for row in odds_rows)
        self.assertEqual(odds_markets, ["moneyline_away", "moneyline_home", "spread", "total"])
        sim_markets = sorted(row["market"] for row in sim_rows)
        self.assertEqual(sim_markets, ["moneyline_away", "moneyline_home", "spread", "total"])
        moneyline_home_sim = next(row for row in sim_rows if row["market"] == "moneyline_home")
        self.assertEqual(moneyline_home_sim["sim_projection"], 0.68)
        self.assertEqual(moneyline_home_sim["model_side"], "home")
        moneyline_away_sim = next(row for row in sim_rows if row["market"] == "moneyline_away")
        self.assertAlmostEqual(moneyline_away_sim["sim_projection"], 0.32)
        spread_sim = next(row for row in sim_rows if row["market"] == "spread")
        self.assertEqual(spread_sim["projected_value"], -4.2)
        self.assertIsInstance(spread_sim["sim_projection"], float)
        total_sim = next(row for row in sim_rows if row["market"] == "total")
        self.assertEqual(total_sim["projected_value"], 51.0)
        self.assertIsInstance(total_sim["sim_projection"], float)

    def test_spread_and_total_without_stdev_have_no_fabricated_probability(self) -> None:
        # No stdev available (e.g. no SmartSim 2.0 shadow data yet) --
        # projected_value still carries the raw point estimate, but
        # sim_projection must never be a raw point value misread as a
        # percentage by the board.
        _odds_rows, sim_rows = _ncaaf_market_board_rows_for_game(
            game_id="g1",
            market_margin=-6.5,
            market_total=49.5,
            home_moneyline=None,
            away_moneyline=None,
            model_margin=-4.2,
            model_total=57.9,
            home_win_probability=None,
        )
        spread_sim = next(row for row in sim_rows if row["market"] == "spread")
        self.assertIsNone(spread_sim["sim_projection"])
        self.assertEqual(spread_sim["projected_value"], -4.2)
        total_sim = next(row for row in sim_rows if row["market"] == "total")
        self.assertIsNone(total_sim["sim_projection"])
        self.assertEqual(total_sim["projected_value"], 57.9)

    def test_no_data_produces_no_rows(self) -> None:
        odds_rows, sim_rows = _ncaaf_market_board_rows_for_game(
            game_id="g1",
            market_margin=None,
            market_total=None,
            home_moneyline=None,
            away_moneyline=None,
            model_margin=None,
            model_total=None,
            home_win_probability=None,
        )
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_market_line_without_model_signal_has_no_sim_row(self) -> None:
        # A real quoted spread/total should still show up as an odds row
        # even when no model projection resolved for it -- never silently
        # dropped just because the sim side is missing.
        odds_rows, sim_rows = _ncaaf_market_board_rows_for_game(
            game_id="g1",
            market_margin=-3.0,
            market_total=None,
            home_moneyline=None,
            away_moneyline=None,
            model_margin=None,
            model_total=None,
            home_win_probability=None,
        )
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["market"], "spread")
        self.assertEqual(sim_rows, [])

    def test_join_odds_to_sim_round_trip(self) -> None:
        odds_rows, sim_rows = _ncaaf_market_board_rows_for_game(
            game_id="g1",
            market_margin=-6.5,
            market_total=None,
            home_moneyline=-235,
            away_moneyline=195,
            model_margin=None,
            model_total=None,
            home_win_probability=0.68,
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        moneyline_rows = [row for row in inventory if row["market"] == "moneyline_home"]
        self.assertEqual(moneyline_rows[0]["join_status"], JOIN_STATUS_MATCHED)
        spread_rows = [row for row in inventory if row["market"] == "spread"]
        self.assertEqual(spread_rows[0]["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)


class NcaafMarketBoardBuilderTests(unittest.TestCase):
    def test_build_ncaaf_market_board_shapes_games(self) -> None:
        fake_context = {
            "date": "week_1",
            "using_sample_data": False,
            "source_path": "/tmp/fake.json",
            "games": [
                {
                    "gamePk": "1_UNLV_Sam_Houston",
                    "away": {"abbr": "UNL", "name": "UNLV"},
                    "home": {"abbr": "SHU", "name": "Sam Houston"},
                    "shared_is_live": False,
                    "ncaaf_card": {
                        "scoreboard": {
                            "blend_margin": -4.2,
                            "blend_total": 51.0,
                            "home_win_probability": 0.68,
                        }
                    },
                }
            ],
        }
        fake_lines_index = {
            ("sam houston", "unlv"): {
                "market_margin": -6.5,
                "market_total": 49.5,
                "home_moneyline": -235,
                "away_moneyline": 195,
            }
        }
        with patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1, 2]),
        ), patch(
            "syndicate.features.ncaaf.cards.build_smartsim_cards_page_context",
            return_value=fake_context,
        ), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_market_lines",
            return_value=fake_lines_index,
        ):
            board = build_ncaaf_market_board(1)

        self.assertEqual(board["week"], 1)
        self.assertEqual(board["season"], 2025)
        self.assertEqual(board["available_weeks"], [1, 2])
        self.assertEqual(len(board["games"]), 1)
        game = board["games"][0]
        self.assertEqual(game["matchup"], "UNL @ SHU")
        self.assertEqual(game["game_state"], "pregame")
        markets = sorted({row["market"] for row in game["rows"]})
        self.assertEqual(markets, sorted(set(_NCAAF_MARKET_BOARD_DISPLAY_LABELS.values())))


if __name__ == "__main__":
    unittest.main()
