from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.mlb.cards import _mlb_market_board_prop_rows_for_game
from syndicate.features.mlb.cards import _mlb_market_board_rows_for_game
from syndicate.features.mlb.cards import build_mlb_market_board
from syndicate.features.mlb.cards import mlb_needs_resim_game_pks
from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NEEDS_RESIM
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


class MlbMarketBoardPropRowsTests(unittest.TestCase):
    def test_pitcher_prop_uses_prop_field_for_display_label(self) -> None:
        # Real captured shape this session: markets.pitcherProps entries
        # carry a generic market="pitcher_props" but the specific stat is
        # in prop="outs" -- the display label must combine them.
        markets = {
            "pitcherProps": [
                {
                    "pitcher_name": "Michael McGreevy",
                    "market": "pitcher_props",
                    "prop": "outs",
                    "selection": "over",
                    "market_line": 17.5,
                    "odds": "-145",
                    "edge": 0.12193146979260594,
                    "recommendation_tier": "official",
                    "team_side": "home",
                }
            ]
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)

        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["market"], "Pitcher Outs")
        self.assertEqual(odds_rows[0]["entity"], "Michael McGreevy")
        self.assertEqual(odds_rows[0]["side"], "over")
        self.assertEqual(odds_rows[0]["line"], 17.5)
        self.assertEqual(odds_rows[0]["market_type"], "prop")

        self.assertEqual(len(sim_rows), 1)
        self.assertAlmostEqual(sim_rows[0]["sim_projection"], 0.12193146979260594)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_MATCHED)

    def test_hitter_prop_market_field_is_already_a_good_display_label(self) -> None:
        # Real captured shape this session: markets.hitterProps entries
        # already carry a specific market like "hitter_hits" or
        # "hitter_total_bases" -- unlike pitcher props, no combining with
        # `prop` is needed, just title-casing.
        markets = {
            "hitterProps": [
                {
                    "player_name": "Alec Burleson",
                    "market": "hitter_hits",
                    "prop": "batter_hits",
                    "selection": "under",
                    "market_line": 2.5,
                    "odds": "+110",
                    "edge": 0.49579165598970387,
                    "recommendation_tier": "official",
                },
                {
                    "player_name": "Riley Greene",
                    "market": "hitter_total_bases",
                    "prop": "batter_total_bases",
                    "selection": "over",
                    "market_line": 1.5,
                    "odds": "-105",
                    "edge": 0.009546647124084873,
                    "recommendation_tier": "official",
                },
            ]
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)

        self.assertEqual(len(odds_rows), 2)
        by_entity = {row["entity"]: row for row in odds_rows}
        self.assertEqual(by_entity["Alec Burleson"]["market"], "Hitter Hits")
        self.assertEqual(by_entity["Riley Greene"]["market"], "Hitter Total Bases")
        self.assertEqual(len(sim_rows), 2)

    def test_extra_prop_tiers_are_also_included(self) -> None:
        markets = {
            "extraPitcherProps": [
                {
                    "pitcher_name": "Someone Else",
                    "prop": "strikeouts",
                    "selection": "over",
                    "market_line": 5.5,
                    "odds": "-110",
                    "edge": 0.03,
                    "recommendation_tier": "candidate",
                }
            ],
            "extraHitterProps": [
                {
                    "player_name": "Another Player",
                    "market": "hitter_rbis",
                    "selection": "over",
                    "market_line": 0.5,
                    "odds": "+120",
                    "edge": 0.05,
                    "recommendation_tier": "candidate",
                }
            ],
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)
        self.assertEqual(len(odds_rows), 2)
        entities = {row["entity"] for row in odds_rows}
        self.assertEqual(entities, {"Someone Else", "Another Player"})

    def test_rows_missing_entity_or_selection_are_skipped(self) -> None:
        markets = {
            "hitterProps": [
                {"player_name": "", "market": "hitter_hits", "selection": "over", "odds": "-110", "edge": 0.1},
                {"player_name": "Nobody Selection", "market": "hitter_hits", "selection": "push", "odds": "-110", "edge": 0.1},
            ]
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)
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

    def test_prop_rows_are_merged_alongside_game_market_rows(self) -> None:
        fake_games = [
            {
                "gamePk": 824247,
                "away": {"abbr": "KC"},
                "home": {"abbr": "DET"},
                "status": {"abstract": "Preview"},
                "markets": {
                    "ml": {"selection": "home", "model_prob": 0.695, "odds": "-229"},
                    "pitcherProps": [
                        {
                            "pitcher_name": "Michael McGreevy",
                            "market": "pitcher_props",
                            "prop": "outs",
                            "selection": "over",
                            "market_line": 17.5,
                            "odds": "-145",
                            "edge": 0.12,
                        }
                    ],
                },
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload",
            return_value={"games": fake_games},
        ):
            board = build_mlb_market_board("2026-07-23")

        rows = board["games"][0]["rows"]
        self.assertEqual(len(rows), 2)
        by_market_type = {row["market_type"]: row for row in rows}
        self.assertEqual(by_market_type["game"]["market"], "Moneyline")
        self.assertEqual(by_market_type["prop"]["market"], "Pitcher Outs")
        self.assertEqual(by_market_type["prop"]["entity"], "Michael McGreevy")
        self.assertEqual(by_market_type["prop"]["join_status"], JOIN_STATUS_MATCHED)


class MlbNeedsResimGamePksTests(unittest.TestCase):
    def test_returns_game_pks_with_at_least_one_needs_resim_row(self) -> None:
        fake_board = {
            "date": "2026-07-23",
            "games": [
                {"gamePk": 111, "rows": [{"join_status": JOIN_STATUS_MATCHED}]},
                {
                    "gamePk": 222,
                    "rows": [
                        {"join_status": JOIN_STATUS_MATCHED},
                        {"join_status": JOIN_STATUS_NEEDS_RESIM, "join_note": "Sim projected a different pitcher"},
                    ],
                },
            ],
        }
        with patch("syndicate.features.mlb.cards.build_mlb_market_board", return_value=fake_board):
            result = mlb_needs_resim_game_pks("2026-07-23")
        self.assertEqual(result, ["222"])

    def test_no_needs_resim_rows_returns_empty_list(self) -> None:
        fake_board = {"date": "2026-07-23", "games": [{"gamePk": 111, "rows": [{"join_status": JOIN_STATUS_MATCHED}]}]}
        with patch("syndicate.features.mlb.cards.build_mlb_market_board", return_value=fake_board):
            result = mlb_needs_resim_game_pks("2026-07-23")
        self.assertEqual(result, [])

    def test_multiple_games_with_mismatches_are_sorted(self) -> None:
        fake_board = {
            "date": "2026-07-23",
            "games": [
                {"gamePk": 300, "rows": [{"join_status": JOIN_STATUS_NEEDS_RESIM}]},
                {"gamePk": 100, "rows": [{"join_status": JOIN_STATUS_NEEDS_RESIM}]},
            ],
        }
        with patch("syndicate.features.mlb.cards.build_mlb_market_board", return_value=fake_board):
            result = mlb_needs_resim_game_pks("2026-07-23")
        self.assertEqual(result, ["100", "300"])


if __name__ == "__main__":
    unittest.main()
