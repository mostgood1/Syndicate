from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nfl.cards import _NFL_MARKET_BOARD_DISPLAY_LABELS
from syndicate.features.nfl.cards import _game_from_smartsim_projection
from syndicate.features.nfl.cards import _game_from_snapshot_bundle
from syndicate.features.nfl.cards import _nfl_cover_probability
from syndicate.features.nfl.cards import _nfl_market_board_rows_for_game
from syndicate.features.nfl.cards import _nfl_prices_from_lines_entry
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
    def test_all_markets_present_with_both_sides_and_prices(self) -> None:
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
            spread_away_line=1.5,
            spread_home_price=-108,
            spread_away_price=-112,
            total_over_price=-110,
            total_under_price=-110,
        )
        odds_markets = sorted(row["market"] for row in odds_rows)
        self.assertEqual(odds_markets, ["moneyline_away", "moneyline_home", "spread_away", "spread_home", "total", "total"])
        sim_markets = sorted(row["market"] for row in sim_rows)
        self.assertEqual(sim_markets, ["moneyline_away", "moneyline_home", "spread_away", "spread_home", "total"])
        moneyline_home_sim = next(row for row in sim_rows if row["market"] == "moneyline_home")
        self.assertEqual(moneyline_home_sim["sim_projection"], 0.533)
        self.assertEqual(moneyline_home_sim["model_side"], "home")
        spread_home_odds = next(row for row in odds_rows if row["market"] == "spread_home")
        self.assertEqual(spread_home_odds["odds"], -108)
        self.assertEqual(spread_home_odds["line"], -1.5)
        spread_away_odds = next(row for row in odds_rows if row["market"] == "spread_away")
        self.assertEqual(spread_away_odds["odds"], -112)
        self.assertEqual(spread_away_odds["line"], 1.5)
        total_sides = sorted(row["side"] for row in odds_rows if row["market"] == "total")
        self.assertEqual(total_sides, ["over", "under"])
        for row in odds_rows:
            if row["market"] == "total":
                self.assertEqual(row["odds"], -110)
        spread_home_sim = next(row for row in sim_rows if row["market"] == "spread_home")
        spread_away_sim = next(row for row in sim_rows if row["market"] == "spread_away")
        self.assertEqual(spread_home_sim["projected_value"], 1.3)
        self.assertIsInstance(spread_home_sim["sim_projection"], float)
        self.assertAlmostEqual(spread_home_sim["sim_projection"] + spread_away_sim["sim_projection"], 1.0)

    def test_spread_cover_probability_uses_negated_bet_notation_line(self) -> None:
        # Home favored by 10.5 (bet notation -10.5) with a model margin of
        # +10.5 is a coin flip, NOT near-certainty. The original pass fed
        # the bet-notation line straight into P(margin > line), producing
        # P(margin > -10.5) ~= 0.94 for this exact shape.
        _odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id="g1",
            home_moneyline=None,
            away_moneyline=None,
            spread_line=-10.5,
            total_line=None,
            model_margin=10.5,
            model_total=None,
            model_margin_stdev=13.0,
            model_total_stdev=None,
            home_win_probability=None,
        )
        spread_home_sim = next(row for row in sim_rows if row["market"] == "spread_home")
        self.assertAlmostEqual(spread_home_sim["sim_projection"], 0.5, places=6)

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
        self.assertEqual(len(odds_rows), 2)
        self.assertEqual(sorted(row["market"] for row in odds_rows), ["spread_away", "spread_home"])
        # The away line is derived as the negation when no explicit away
        # point is available.
        spread_away = next(row for row in odds_rows if row["market"] == "spread_away")
        self.assertEqual(spread_away["line"], 3.0)
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
        spread_rows = [row for row in inventory if row["market"] == "spread_home"]
        self.assertEqual(spread_rows[0]["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)

    def test_total_over_under_share_one_sim_row_with_complement(self) -> None:
        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id="g1",
            home_moneyline=None,
            away_moneyline=None,
            spread_line=None,
            total_line=44.5,
            model_margin=None,
            model_total=47.0,
            model_margin_stdev=None,
            model_total_stdev=10.0,
            home_win_probability=None,
            total_over_price=-105,
            total_under_price=-115,
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        over_row = next(row for row in inventory if row["side"] == "over")
        under_row = next(row for row in inventory if row["side"] == "under")
        self.assertEqual(over_row["join_status"], JOIN_STATUS_MATCHED)
        self.assertEqual(under_row["join_status"], JOIN_STATUS_MATCHED)
        self.assertGreater(over_row["sim_projection"], 0.5)
        self.assertAlmostEqual(over_row["sim_projection"] + under_row["sim_projection"], 1.0)
        self.assertEqual(over_row["odds"], -105)
        self.assertEqual(under_row["odds"], -115)


class NflPricesFromLinesEntryTests(unittest.TestCase):
    _ENTRY = {
        "moneyline": {"home": -485, "away": 370},
        "total_runs": {"line": 47.5, "over": -110, "under": -105},
        "run_line": {"home": -10.5},
        "markets": [
            {"key": "h2h", "outcomes": [{"name": "Arizona Cardinals", "price": 370}, {"name": "Dallas Cowboys", "price": -485}]},
            {"key": "spreads", "outcomes": [{"name": "Arizona Cardinals", "price": -110, "point": 10.5}, {"name": "Dallas Cowboys", "price": -108, "point": -10.5}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 47.5}, {"name": "Under", "price": -105, "point": 47.5}]},
        ],
    }

    def test_extracts_per_side_prices(self) -> None:
        prices = _nfl_prices_from_lines_entry(self._ENTRY, home_full_name="Dallas Cowboys", away_full_name="Arizona Cardinals")
        self.assertEqual(prices["spread_home_line"], -10.5)
        self.assertEqual(prices["spread_home_price"], -108)
        self.assertEqual(prices["spread_away_line"], 10.5)
        self.assertEqual(prices["spread_away_price"], -110)
        self.assertEqual(prices["total_over_price"], -110)
        self.assertEqual(prices["total_under_price"], -105)

    def test_flat_fields_only_still_yields_lines(self) -> None:
        entry = {"run_line": {"home": -3.0}, "total_runs": {"line": 44.5, "over": -110, "under": -110}}
        prices = _nfl_prices_from_lines_entry(entry, home_full_name="A", away_full_name="B")
        self.assertEqual(prices["spread_home_line"], -3.0)
        self.assertEqual(prices["spread_away_line"], 3.0)
        self.assertIsNone(prices["spread_home_price"])
        self.assertEqual(prices["total_over_price"], -110)

    def test_none_entry_is_all_none(self) -> None:
        prices = _nfl_prices_from_lines_entry(None, home_full_name="A", away_full_name="B")
        self.assertTrue(all(value is None for value in prices.values()))


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


class GameFromSmartsimProjectionBoardContractTests(unittest.TestCase):
    """Coverage for the Tier 1 fix to _game_from_smartsim_projection: real
    data must reach game_board_contract.py's shared sim/betting/
    probability_rows inputs, the only thing that was missing -- not a new
    computation, just plumbing the projection's own fields through."""

    @staticmethod
    def _projection() -> SmartSimNflProjection:
        return SmartSimNflProjection(
            game_id="2025_10_ARI_SEA", season=2025, week=10, home_team="SEA", away_team="ARI",
            home_score_mean=23.2, away_score_mean=21.9, margin_mean=1.3, total_mean=45.1,
            margin_stdev=14.0, total_stdev=11.4, home_win_rate=0.612, seeds_used=300,
            profile_name="nfl_v1", rating_source="test", generated_at="2026-01-01T00:00:00Z",
        )

    def test_sim_periods_and_score_come_from_projection_fields(self) -> None:
        with patch("syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=None):
            game = _game_from_smartsim_projection(self._projection(), 2025, 10)
        full = game["sim"]["periods"]["full"]
        self.assertEqual(full["away_mean"], 21.9)
        self.assertEqual(full["home_mean"], 23.2)
        self.assertEqual(full["total_mean"], 45.1)
        self.assertEqual(full["margin_mean"], 1.3)
        self.assertAlmostEqual(full["p_home_win"], 0.612)
        self.assertEqual(game["sim"]["score"]["away_mean"], 21.9)
        self.assertEqual(game["sim"]["score"]["home_mean"], 23.2)

    def test_betting_always_carries_the_models_own_win_probability(self) -> None:
        with patch("syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=None):
            game = _game_from_smartsim_projection(self._projection(), 2025, 10)
        self.assertAlmostEqual(game["betting"]["p_home_win"], 0.612)
        # No real market line was found -- never fabricate one.
        self.assertNotIn("home_spread", game["betting"])
        self.assertNotIn("total", game["betting"])

    def test_betting_carries_the_real_market_line_when_one_was_found(self) -> None:
        fake_lines = {"run_line": {"home": -1.5}, "total_runs": {"line": 45.5}}
        with patch("syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=fake_lines):
            game = _game_from_smartsim_projection(self._projection(), 2025, 10)
        self.assertEqual(game["betting"]["home_spread"], -1.5)
        self.assertEqual(game["betting"]["total"], 45.5)

    def test_probability_rows_built_from_home_win_rate(self) -> None:
        with patch("syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=None):
            game = _game_from_smartsim_projection(self._projection(), 2025, 10)
        row = game["probability_rows"][0]
        self.assertEqual(row["label"], "Full Game")
        self.assertAlmostEqual(row["home_pct"], 61.2)
        self.assertAlmostEqual(row["away_pct"], 38.8)

    def test_prop_recommendations_intentionally_left_unset(self) -> None:
        # See the comment in _game_from_smartsim_projection: no real
        # home/away team-side attribution exists for NFL player props here,
        # so this must not be forced/fabricated.
        with patch("syndicate.features.nfl.cards._nfl_real_lines_for_matchup", return_value=None):
            game = _game_from_smartsim_projection(self._projection(), 2025, 10)
        self.assertNotIn("prop_recommendations", game)


class GameFromSnapshotBundleBoardContractTests(unittest.TestCase):
    """_game_from_snapshot_bundle reads the legacy upcoming_recs_*.csv
    snapshot shape (type/confidence/ev_pct/odds -- no score projection, no
    numeric market line, no pick side), so unlike the two SmartSim-backed
    card builders above it deliberately does NOT populate sim/betting/
    probability_rows -- there is no real, non-fabricated source for any of
    them in this data shape. This locks down that intentional omission."""

    def test_sim_betting_probability_rows_are_not_fabricated(self) -> None:
        bundle = {
            "game_date": "2025-12-25",
            "away_team": "Denver Broncos",
            "home_team": "Kansas City Chiefs",
            "rows": [{"type": "SPREAD", "confidence": "High", "ev_pct": 37.2, "odds": -110}],
            "top_row": {"type": "SPREAD", "confidence": "High", "ev_pct": 37.2, "odds": -110},
            "top_ev": 37.2,
            "confidence": "High",
        }
        game = _game_from_snapshot_bundle(bundle, 2025, 17)
        self.assertNotIn("sim", game)
        self.assertNotIn("betting", game)
        self.assertNotIn("probability_rows", game)
        self.assertNotIn("prop_recommendations", game)


if __name__ == "__main__":
    unittest.main()
