from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nfl.cards import _NFL_MARKET_BOARD_DISPLAY_LABELS
from syndicate.features.nfl.cards import _nfl_cover_probability
from syndicate.features.nfl.cards import _nfl_market_board_rows_for_game
from syndicate.features.nfl.cards import build_nfl_market_board
from syndicate.features.nfl.smartsim2_projection import SmartSimNflProjection
from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NO_SIM_COVERAGE
from syndicate.features.shared.market_inventory import join_odds_to_sim


class NflCoverProbabilityTests(unittest.TestCase):
    def test_no_stdev_returns_none(self) -> None:
        self.assertIsNone(_nfl_cover_probability(line=3.5, mean=1.3, stdev=None))
        self.assertIsNone(_nfl_cover_probability(line=3.5, mean=1.3, stdev=0))

    def test_mean_above_line_favors_over_half(self) -> None:
        prob = _nfl_cover_probability(line=0.0, mean=5.0, stdev=13.0)
        self.assertGreater(prob, 0.5)
        self.assertLess(prob, 1.0)


class NflMarketBoardRowsTests(unittest.TestCase):
    def test_all_markets_present(self) -> None:
        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id="g1",
            home_moneyline=-125,
            away_moneyline=105,
            spread_line=-1.5,
            total_line=45.5,
            model_margin=1.3,
            model_total=45.1,
            model_margin_stdev=14.0,
            model_total_stdev=11.4,
            home_win_probability=0.533,
        )
        odds_markets = sorted(row["market"] for row in odds_rows)
        self.assertEqual(odds_markets, ["moneyline_away", "moneyline_home", "spread", "total"])
        sim_markets = sorted(row["market"] for row in sim_rows)
        self.assertEqual(sim_markets, ["moneyline_away", "moneyline_home", "spread", "total"])
        moneyline_home_sim = next(row for row in sim_rows if row["market"] == "moneyline_home")
        self.assertEqual(moneyline_home_sim["sim_projection"], 0.533)
        self.assertEqual(moneyline_home_sim["model_side"], "home")
        spread_sim = next(row for row in sim_rows if row["market"] == "spread")
        self.assertEqual(spread_sim["projected_value"], 1.3)
        self.assertIsInstance(spread_sim["sim_projection"], float)

    def test_no_data_produces_no_rows(self) -> None:
        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id="g1",
            home_moneyline=None,
            away_moneyline=None,
            spread_line=None,
            total_line=None,
            model_margin=None,
            model_total=None,
            model_margin_stdev=None,
            model_total_stdev=None,
            home_win_probability=None,
        )
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_market_line_without_model_signal_has_no_sim_row(self) -> None:
        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id="g1",
            home_moneyline=None,
            away_moneyline=None,
            spread_line=-3.0,
            total_line=None,
            model_margin=None,
            model_total=None,
            model_margin_stdev=None,
            model_total_stdev=None,
            home_win_probability=None,
        )
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["market"], "spread")
        self.assertEqual(sim_rows, [])

    def test_join_odds_to_sim_round_trip(self) -> None:
        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id="g1",
            home_moneyline=-125,
            away_moneyline=105,
            spread_line=-1.5,
            total_line=None,
            model_margin=None,
            model_total=None,
            model_margin_stdev=None,
            model_total_stdev=None,
            home_win_probability=0.533,
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        moneyline_rows = [row for row in inventory if row["market"] == "moneyline_home"]
        self.assertEqual(moneyline_rows[0]["join_status"], JOIN_STATUS_MATCHED)
        spread_rows = [row for row in inventory if row["market"] == "spread"]
        self.assertEqual(spread_rows[0]["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)


class NflMarketBoardBuilderTests(unittest.TestCase):
    def test_build_nfl_market_board_shapes_games(self) -> None:
        projection = SmartSimNflProjection(
            game_id="2025_10_ARI_SEA", season=2025, week=10, home_team="SEA", away_team="ARI",
            home_score_mean=23.2, away_score_mean=21.9, margin_mean=1.3, total_mean=45.1,
            margin_stdev=14.0, total_stdev=11.4, home_win_rate=0.533, seeds_used=300,
            profile_name="nfl_v1", rating_source="test", generated_at="2026-01-01T00:00:00Z",
        )
        fake_lines = {"moneyline": {"home": -125, "away": 105}, "run_line": {"home": -1.5}, "total_runs": {"line": 45.5}}

        class FakeBranding:
            def __init__(self, abbr, name):
                self.abbreviation = abbr
                self.display_name = name
                self.logo_url = f"https://example.test/{abbr}.png"

        def fake_resolve_branding(code):
            return {"SEA": FakeBranding("SEA", "Seattle Seahawks"), "ARI": FakeBranding("ARI", "Arizona Cardinals")}.get(code)

        with patch(
            "syndicate.features.nfl.cards.read_projection_artifact", return_value=(projection,),
        ), patch(
            "syndicate.features.nfl.cards.nfl_projection_available_weeks", return_value=[9, 10],
        ), patch(
            "syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=fake_lines,
        ), patch(
            "syndicate.features.nfl.cards._resolve_branding", side_effect=fake_resolve_branding,
        ):
            board = build_nfl_market_board(2025, 10)

        self.assertEqual(board["season"], 2025)
        self.assertEqual(board["week"], 10)
        self.assertEqual(board["available_weeks"], [9, 10])
        self.assertEqual(len(board["games"]), 1)
        game = board["games"][0]
        self.assertEqual(game["matchup"], "ARI @ SEA")
        self.assertEqual(game["game_state"], "pregame")
        markets = sorted({row["market"] for row in game["rows"]})
        self.assertEqual(markets, sorted(set(_NFL_MARKET_BOARD_DISPLAY_LABELS.values())))

    def test_build_nfl_market_board_folds_in_prop_rows(self) -> None:
        projection = SmartSimNflProjection(
            game_id="2025_22_SEA_NE", season=2025, week=22, home_team="NE", away_team="SEA",
            home_score_mean=23.2, away_score_mean=21.9, margin_mean=1.3, total_mean=45.1,
            margin_stdev=14.0, total_stdev=11.4, home_win_rate=0.533, seeds_used=300,
            profile_name="nfl_v1", rating_source="test", generated_at="2026-01-01T00:00:00Z",
        )

        class FakeBranding:
            def __init__(self, abbr, name):
                self.abbreviation = abbr
                self.display_name = name
                self.logo_url = f"https://example.test/{abbr}.png"

        def fake_resolve_branding(code):
            return {"NE": FakeBranding("NE", "New England Patriots"), "SEA": FakeBranding("SEA", "Seattle Seahawks")}.get(code)

        props_key = "Seattle Seahawks|New England Patriots"
        fake_props_odds = [{"game_id": props_key, "market": "passing_yards", "period": "full_game", "entity": "Drake Maye", "side": "over", "line": 230.5, "odds": -110.0, "market_type": "prop"}]
        fake_props_sim = [{"game_id": props_key, "market": "passing_yards", "period": "full_game", "entity": "Drake Maye", "sim_projection": 0.55, "projected_value": 240.0, "sim_source": "nfl_season_rate"}]

        with patch(
            "syndicate.features.nfl.cards.read_projection_artifact", return_value=(projection,),
        ), patch(
            "syndicate.features.nfl.cards.nfl_projection_available_weeks", return_value=[22],
        ), patch(
            "syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=None,
        ), patch(
            "syndicate.features.nfl.cards._resolve_branding", side_effect=fake_resolve_branding,
        ), patch(
            "syndicate.features.nfl.cards.nfl_props_rows_for_week", return_value=(fake_props_odds, fake_props_sim),
        ):
            board = build_nfl_market_board(2025, 22)

        game = board["games"][0]
        prop_rows = [row for row in game["rows"] if row["market_type"] == "prop"]
        self.assertEqual(len(prop_rows), 1)
        self.assertEqual(prop_rows[0]["entity"], "Drake Maye")
        self.assertEqual(prop_rows[0]["market"], "passing_yards")
        self.assertEqual(prop_rows[0]["game_id"], "2025_22_SEA_NE")
        self.assertEqual(prop_rows[0]["sim_projection"], 0.55)


if __name__ == "__main__":
    unittest.main()
