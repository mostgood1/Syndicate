from __future__ import annotations

import unittest

from syndicate.features.shared.basketball_market_board import basketball_game_state
from syndicate.features.shared.basketball_market_board import basketball_market_board_rows_for_game
from syndicate.features.shared.basketball_market_board import build_basketball_market_board
from syndicate.features.shared.basketball_market_board import hydrate_live_prop_rows
from syndicate.features.shared.basketball_market_board import live_rows_by_event_id
from syndicate.features.shared.basketball_market_board import parse_raw_basketball_player_props_rows
from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NEEDS_RESIM
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
        # "market" is the disambiguated join key (see _prop_join_market_key)
        # -- build_basketball_market_board strips the "::<player>" suffix
        # back to "Threes" for display.
        self.assertEqual(odds_rows[0]["market"], "Threes::miles mcbride")
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


class LiveRowsByEventIdTests(unittest.TestCase):
    def test_reshapes_games_list_into_event_id_keyed_dict(self) -> None:
        payload = {
            "games": [
                {"event_id": "401585001", "rows": [{"player": "A", "stat": "pts"}]},
                {"event_id": "401585002", "rows": [{"player": "B", "stat": "reb"}]},
            ]
        }
        result = live_rows_by_event_id(payload)
        self.assertEqual(set(result), {"401585001", "401585002"})
        self.assertEqual(result["401585001"][0]["player"], "A")

    def test_non_dict_or_missing_games_produces_empty_result(self) -> None:
        self.assertEqual(live_rows_by_event_id(None), {})
        self.assertEqual(live_rows_by_event_id({}), {})
        self.assertEqual(live_rows_by_event_id({"games": "not-a-list"}), {})


class HydrateLivePropRowsTests(unittest.TestCase):
    def test_overlays_live_projection_and_actual_matched_by_player_and_stat(self) -> None:
        # Real captured shape (basketball_live_artifacts.py): live rows
        # carry player/stat/live_projection/actual with a stable event_id,
        # so an exact (player, stat) match is enough -- no fuzzy matching
        # needed the way MLB's market/line join requires.
        inventory = [
            {"market_type": "prop", "entity": "Miles McBride", "market": "Threes", "join_status": JOIN_STATUS_MATCHED},
            {"market_type": "game", "entity": None, "market": "Moneyline", "join_status": JOIN_STATUS_MATCHED},
        ]
        live_rows = [{"player": "Miles McBride", "stat": "threes", "live_projection": 2.4, "actual": 1}]
        hydrate_live_prop_rows(inventory, live_rows)

        self.assertEqual(inventory[0]["live_projection"], 2.4)
        self.assertEqual(inventory[0]["live_actual"], 1)
        # Game-market rows (entity=None) never match a player-keyed live row.
        self.assertNotIn("live_projection", inventory[1])

    def test_falls_back_to_camelcase_live_projection_key(self) -> None:
        inventory = [{"market_type": "prop", "entity": "Someone", "market": "Points", "join_status": JOIN_STATUS_MATCHED}]
        live_rows = [{"player": "Someone", "stat": "pts", "liveProjection": 14.2}]
        hydrate_live_prop_rows(inventory, live_rows)
        self.assertEqual(inventory[0]["live_projection"], 14.2)

    def test_no_live_rows_is_a_no_op(self) -> None:
        inventory = [{"market_type": "prop", "entity": "Someone", "market": "Points", "join_status": JOIN_STATUS_MATCHED}]
        hydrate_live_prop_rows(inventory, None)
        hydrate_live_prop_rows(inventory, [])
        self.assertNotIn("live_projection", inventory[0])

    def test_unmatched_player_or_stat_leaves_row_untouched(self) -> None:
        inventory = [{"market_type": "prop", "entity": "Someone", "market": "Points", "join_status": JOIN_STATUS_MATCHED}]
        live_rows = [{"player": "A Different Player", "stat": "pts", "live_projection": 14.2}]
        hydrate_live_prop_rows(inventory, live_rows)
        self.assertNotIn("live_projection", inventory[0])


class BuildBasketballMarketBoardLiveHydrationTests(unittest.TestCase):
    def test_board_overlays_live_projection_for_a_live_game(self) -> None:
        games = [
            {
                "gamePk": "1",
                "event_id": "401585001",
                "away": {"abbr": "SAS"},
                "home": {"abbr": "NYK"},
                "status": "Live",
                "prop_recommendations": {
                    "away": [{"player": "Miles McBride", "market": "threes", "side": "over", "line": 0.5, "price": -105.0, "p_win": 1.0}],
                    "home": [],
                },
            }
        ]
        live_player_lens_payload = {
            "games": [{"event_id": "401585001", "rows": [{"player": "Miles McBride", "stat": "threes", "live_projection": 2.0, "actual": 1}]}]
        }
        board = build_basketball_market_board(
            sport_slug="nba",
            selected_date="2026-07-23",
            games=games,
            live_player_lens_payload=live_player_lens_payload,
        )
        prop_row = board["games"][0]["rows"][0]
        self.assertEqual(prop_row["live_projection"], 2.0)
        self.assertEqual(prop_row["live_actual"], 1)

    def test_board_without_live_payload_has_no_live_fields(self) -> None:
        games = [{"gamePk": "1", "event_id": "1", "away": {"abbr": "SAS"}, "home": {"abbr": "NYK"}, "status": "Scheduled"}]
        board = build_basketball_market_board(sport_slug="nba", selected_date="2026-07-23", games=games)
        self.assertEqual(board["games"][0]["rows"], [])


class ParseRawBasketballPlayerPropsRowsTests(unittest.TestCase):
    def test_aggregates_flat_rows_into_line_over_under_shape(self) -> None:
        # Real documented shape (scripts/fetch_basketball_oddsapi_props_local.py):
        # one row per bookmaker/market/Over-or-Under outcome.
        rows = [
            {"player_name": "Miles McBride", "market": "player_points", "outcome_name": "Over", "point": 12.5, "price": -110, "bookmaker": "draftkings"},
            {"player_name": "Miles McBride", "market": "player_points", "outcome_name": "Under", "point": 12.5, "price": -110, "bookmaker": "draftkings"},
            {"player_name": "Miles McBride", "market": "player_threes", "outcome_name": "Over", "point": 2.5, "price": -120, "bookmaker": "fanduel"},
        ]
        result = parse_raw_basketball_player_props_rows(rows)
        self.assertIn("miles mcbride", result)
        self.assertEqual(result["miles mcbride"]["points"], {"line": 12.5, "over_odds": -110, "under_odds": -110})
        self.assertEqual(result["miles mcbride"]["threes"]["over_odds"], -120)
        self.assertIsNone(result["miles mcbride"]["threes"]["under_odds"])

    def test_second_bookmaker_for_same_stat_does_not_override_first(self) -> None:
        rows = [
            {"player_name": "A Player", "market": "player_points", "outcome_name": "Over", "point": 20.5, "price": -115},
            {"player_name": "A Player", "market": "player_points", "outcome_name": "Over", "point": 20.5, "price": -105},
        ]
        result = parse_raw_basketball_player_props_rows(rows)
        self.assertEqual(result["a player"]["points"]["over_odds"], -115)

    def test_rows_missing_player_or_invalid_outcome_are_skipped(self) -> None:
        rows = [
            {"player_name": "", "market": "player_points", "outcome_name": "Over", "point": 1, "price": -110},
            {"player_name": "Someone", "market": "player_points", "outcome_name": "Push", "point": 1, "price": -110},
        ]
        result = parse_raw_basketball_player_props_rows(rows)
        self.assertEqual(result, {})


class BasketballMarketBoardRawPropsFeedTests(unittest.TestCase):
    def test_raw_feed_covers_both_sides_for_a_player_with_existing_recommendation(self) -> None:
        prop_recommendations = {"away": [{"player": "Miles McBride", "market": "threes", "side": "over", "line": 2.5, "price": -105.0, "p_win": 0.6}], "home": []}
        raw_player_props = {"miles mcbride": {"threes": {"line": 2.5, "over_odds": -120, "under_odds": -110}, "points": {"line": 12.5, "over_odds": -110, "under_odds": -110}}}
        odds_rows, sim_rows = basketball_market_board_rows_for_game(
            game_pk=1, betting={}, prop_recommendations=prop_recommendations, raw_player_props=raw_player_props
        )
        threes_rows = [row for row in odds_rows if row["market"].startswith("Threes::")]
        self.assertEqual(len(threes_rows), 2)
        self.assertEqual({row["side"] for row in threes_rows}, {"over", "under"})
        points_rows = [row for row in odds_rows if row["market"].startswith("Points::")]
        self.assertEqual(len(points_rows), 2)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        matched = [row for row in inventory if row["market"].startswith("Threes::") and row["join_status"] == JOIN_STATUS_MATCHED]
        self.assertTrue(matched)
        no_cov = [row for row in inventory if row["market"].startswith("Points::") and row["join_status"] == JOIN_STATUS_NO_SIM_COVERAGE]
        self.assertTrue(no_cov)

    def test_recommendation_falls_back_when_raw_feed_lacks_that_stat(self) -> None:
        prop_recommendations = {"away": [{"player": "Miles McBride", "market": "threes", "side": "over", "line": 2.5, "price": -105.0, "p_win": 0.6}], "home": []}
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting={}, prop_recommendations=prop_recommendations, raw_player_props={})
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["side"], "over")

    def test_player_with_no_recommendation_coverage_is_not_surfaced(self) -> None:
        raw_player_props = {"unrelated player": {"points": {"line": 10.5, "over_odds": -110, "under_odds": -110}}}
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting={}, prop_recommendations={}, raw_player_props=raw_player_props)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_two_different_players_sharing_a_stat_never_produce_needs_resim(self) -> None:
        # Real bug found for MLB this session (56 false positives on real
        # production data) confirmed to apply equally here: two different
        # players both having a Points prop must never be mistaken for the
        # same slot having a different occupant.
        prop_recommendations = {
            "away": [{"player": "Player A", "market": "pts", "side": "over", "line": 10.5, "price": -110.0, "p_win": 0.55}],
            "home": [{"player": "Player B", "market": "pts", "side": "over", "line": 15.5, "price": -105.0, "p_win": 0.52}],
        }
        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=1, betting={}, prop_recommendations=prop_recommendations)
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        statuses = {row["join_status"] for row in inventory}
        self.assertNotIn(JOIN_STATUS_NEEDS_RESIM, statuses)
        self.assertTrue(all(status == JOIN_STATUS_MATCHED for status in statuses))


if __name__ == "__main__":
    unittest.main()
