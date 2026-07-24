from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.mlb.cards import _mlb_headshot_url
from syndicate.features.mlb.cards import _mlb_hydrate_market_board_line_movement
from syndicate.features.mlb.cards import _mlb_hydrate_market_board_live_projection
from syndicate.features.mlb.cards import _mlb_hydrate_market_board_prop_movement
from syndicate.features.mlb.cards import _mlb_live_lens_prop_rows_for_game
from syndicate.features.mlb.cards import _mlb_market_board_prop_rows_for_game
from syndicate.features.mlb.cards import _mlb_market_board_rows_for_game
from syndicate.features.mlb.cards import _mlb_odds_history_entries_for_player
from syndicate.features.mlb.cards import _mlb_odds_history_entries_for_teams
from syndicate.features.mlb.cards import _mlb_player_id_lookup_for_game
from syndicate.features.mlb.cards import _normalize_live_name
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

        # "market" is the disambiguated join key (see
        # _mlb_prop_join_market_key) -- build_mlb_market_board strips the
        # "::home" suffix back to "Pitcher Outs" for display.
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["market"], "Pitcher Outs::home")
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

        # Hitter props disambiguate the join key by player (no reliable
        # lineup-slot data exists), not team_side.
        self.assertEqual(len(odds_rows), 2)
        by_entity = {row["entity"]: row for row in odds_rows}
        self.assertEqual(by_entity["Alec Burleson"]["market"], "Hitter Hits::alec burleson")
        self.assertEqual(by_entity["Riley Greene"]["market"], "Hitter Total Bases::riley greene")
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

    def test_pitcher_prop_sim_row_carries_real_projected_stat_value(self) -> None:
        # 2026-07-24 fix: the board was showing sim_projection (edge, a
        # win-probability-shaped fraction rendered as a percent) as if it
        # were the projection -- the real projected stat count was sitting
        # right in the same raw row all along, under a stat-prefixed key
        # ("so_mean" for strikeouts), just never read. Confirmed live: a
        # Sugano strikeouts row carried both "edge": 0.278 and
        # "so_mean": 4.821 in the same object.
        markets = {
            "pitcherProps": [
                {
                    "pitcher_name": "Tomoyuki Sugano",
                    "market": "pitcher_props",
                    "prop": "strikeouts",
                    "selection": "over",
                    "market_line": 3.5,
                    "odds": "+106",
                    "edge": 0.27777743335399874,
                    "so_mean": 4.821,
                    "mean_support": 1.321,
                    "recommendation_tier": "official",
                    "team_side": "away",
                }
            ]
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)

        self.assertEqual(len(sim_rows), 1)
        self.assertAlmostEqual(sim_rows[0]["sim_projection"], 0.27777743335399874)
        self.assertAlmostEqual(sim_rows[0]["projected_value"], 4.821)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        self.assertAlmostEqual(inventory[0]["projected_value"], 4.821)

    def test_projected_value_is_none_when_no_mean_field_present(self) -> None:
        markets = {
            "hitterProps": [
                {"player_name": "Alec Burleson", "market": "hitter_hits", "selection": "over", "market_line": 1.5, "odds": "-110", "edge": 0.1}
            ]
        }
        _odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)
        self.assertIsNone(sim_rows[0]["projected_value"])

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


class MlbMarketBoardRawPropsFeedTests(unittest.TestCase):
    """The raw OddsAPI props feed (scripts/refresh_mlb_oddsapi.py) is a
    genuinely independent, unfiltered odds source -- every real quoted
    line, not just the recommendation engine's own picks. Real captured
    shape this session: Michael McGreevy had both "outs" (already
    recommended) and "hits_allowed" (not recommended at all) quoted live.
    """

    def test_probable_pitcher_gets_both_sides_for_a_stat_not_recommended(self) -> None:
        markets = {"pitcherProps": [{"pitcher_name": "Michael McGreevy", "prop": "outs", "selection": "over", "market_line": 17.5, "odds": "-145", "edge": 0.12}]}
        probable = {"home": {"fullName": "Michael McGreevy"}}
        raw_pitcher_lines = {
            "michael mcgreevy": {
                "outs": {"line": 17.5, "over_odds": "-145", "under_odds": "-105"},
                "hits_allowed": {"line": 4.5, "over_odds": "-120", "under_odds": "-130"},
            }
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(
            game_pk=1, markets=markets, probable=probable, raw_pitcher_market_lines=raw_pitcher_lines
        )

        # "market" is the disambiguated join key (team_side="home", since
        # McGreevy is this game's probable home starter) -- relabeled back
        # to "Pitcher Hits Allowed" only at the build_mlb_market_board layer.
        hits_allowed_rows = [row for row in odds_rows if row["market"] == "Pitcher Hits Allowed::home"]
        self.assertEqual(len(hits_allowed_rows), 2)
        self.assertEqual({row["side"] for row in hits_allowed_rows}, {"over", "under"})

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            if row["market"] == "Pitcher Hits Allowed::home":
                self.assertEqual(row["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)

    def test_raw_feed_does_not_duplicate_a_stat_already_recommended(self) -> None:
        # "outs" is quoted in BOTH the recommendation engine's pick and the
        # raw feed -- must produce exactly the raw feed's 2 rows (over +
        # under), not those 2 plus a 3rd single-sided fallback row.
        markets = {"pitcherProps": [{"pitcher_name": "Michael McGreevy", "prop": "outs", "selection": "over", "market_line": 17.5, "odds": "-145", "edge": 0.12}]}
        probable = {"home": {"fullName": "Michael McGreevy"}}
        raw_pitcher_lines = {"michael mcgreevy": {"outs": {"line": 17.5, "over_odds": "-145", "under_odds": "-105"}}}
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(
            game_pk=1, markets=markets, probable=probable, raw_pitcher_market_lines=raw_pitcher_lines
        )
        outs_rows = [row for row in odds_rows if row["market"] == "Pitcher Outs::home"]
        self.assertEqual(len(outs_rows), 2)
        self.assertEqual({row["side"] for row in outs_rows}, {"over", "under"})

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        matched = [row for row in inventory if row["market"] == "Pitcher Outs::home" and row["join_status"] == JOIN_STATUS_MATCHED]
        self.assertTrue(matched)

    def test_recommended_pitcher_stat_falls_back_when_raw_feed_lacks_it(self) -> None:
        # No raw feed at all for this stat -- must still surface via the
        # recommendation engine's own line, exactly like before this change.
        markets = {"pitcherProps": [{"pitcher_name": "Michael McGreevy", "prop": "outs", "selection": "over", "market_line": 17.5, "odds": "-145", "edge": 0.12}]}
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets, probable={}, raw_pitcher_market_lines={})
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["side"], "over")

    def test_hitter_with_existing_recommendation_gets_additional_raw_stats(self) -> None:
        # Real captured shape: raw hitter stat keys use a "batter_" prefix
        # ("batter_home_runs") -- must display as "Hitter Home Runs" to
        # match the recommendation-derived label convention, not "Batter
        # Home Runs".
        markets = {"hitterProps": [{"player_name": "Blaze Jordan", "market": "hitter_hits", "prop": "batter_hits", "selection": "under", "market_line": 0.5, "odds": "+110", "edge": 0.2}]}
        raw_hitter_lines = {
            "blaze jordan": {
                "batter_hits": {"line": 0.5, "over_odds": "+110", "under_odds": "-140"},
                "batter_home_runs": {"line": 0.5, "over_odds": "+250", "under_odds": "-320"},
            }
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets, raw_hitter_market_lines=raw_hitter_lines)

        hr_rows = [row for row in odds_rows if row["market"] == "Hitter Home Runs::blaze jordan"]
        self.assertEqual(len(hr_rows), 2)
        hits_rows = [row for row in odds_rows if row["market"] == "Hitter Hits::blaze jordan"]
        self.assertEqual(len(hits_rows), 2)  # raw feed covers both sides, no fallback duplicate

    def test_hitter_with_no_recommendation_coverage_at_all_is_not_surfaced(self) -> None:
        # Documented, bounded limitation: a hitter who never appears in
        # ANY recommendation tier and isn't the probable pitcher has no
        # roster signal to attribute them to this game by, so raw-feed-only
        # coverage for them is skipped rather than guessed.
        raw_hitter_lines = {"unrelated player": {"batter_hits": {"line": 1.5, "over_odds": "-110", "under_odds": "-110"}}}
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets={}, raw_hitter_market_lines=raw_hitter_lines)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_two_different_hitters_sharing_a_stat_never_produce_needs_resim(self) -> None:
        # Real bug found this session: with real production data, two
        # different hitters (Gleyber Torres, Zach McKinstry) both having an
        # RBI prop produced 56 false "needs resim" rows on one slate --
        # market_inventory's cross-entity check fired just because two
        # DIFFERENT real players share a stat, not because of any actual
        # lineup change. Confirms the join-key disambiguation fix holds.
        markets = {
            "hitterProps": [
                {"player_name": "Gleyber Torres", "market": "hitter_rbis", "prop": "batter_rbis", "selection": "over", "market_line": 0.5, "odds": "-110", "edge": 0.1},
                {"player_name": "Zach McKinstry", "market": "hitter_rbis", "prop": "batter_rbis", "selection": "over", "market_line": 0.5, "odds": "+105", "edge": 0.05},
            ]
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        statuses = {row["join_status"] for row in inventory}
        self.assertNotIn(JOIN_STATUS_NEEDS_RESIM, statuses)
        self.assertTrue(all(status == JOIN_STATUS_MATCHED for status in statuses))

    def test_two_different_starting_pitchers_sharing_a_stat_never_produce_needs_resim(self) -> None:
        # Same false-positive risk on the pitcher side if team_side weren't
        # used to disambiguate: two DIFFERENT starters (one per team) both
        # having a Strikeouts prop is normal, not a starter change.
        markets = {
            "pitcherProps": [
                {"pitcher_name": "Home Starter", "prop": "strikeouts", "selection": "over", "market_line": 5.5, "odds": "-110", "edge": 0.1, "team_side": "home"},
                {"pitcher_name": "Away Starter", "prop": "strikeouts", "selection": "over", "market_line": 4.5, "odds": "-115", "edge": 0.08, "team_side": "away"},
            ]
        }
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(game_pk=1, markets=markets)
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        statuses = {row["join_status"] for row in inventory}
        self.assertNotIn(JOIN_STATUS_NEEDS_RESIM, statuses)

    def test_same_side_starter_swap_still_produces_needs_resim(self) -> None:
        # The genuine signal this whole mechanism exists for: the sim
        # modeled one pitcher for the home side, but the current odds now
        # show a DIFFERENT pitcher for that SAME side -- team_side
        # disambiguation must not suppress this real case.
        markets = {"pitcherProps": [{"pitcher_name": "Original Starter", "prop": "strikeouts", "selection": "over", "market_line": 5.5, "odds": "-110", "edge": 0.1, "team_side": "home"}]}
        probable = {"home": {"fullName": "Replacement Starter"}}
        raw_pitcher_lines = {"replacement starter": {"strikeouts": {"line": 4.5, "over_odds": "-105", "under_odds": "-115"}}}
        odds_rows, sim_rows = _mlb_market_board_prop_rows_for_game(
            game_pk=1, markets=markets, probable=probable, raw_pitcher_market_lines=raw_pitcher_lines
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        replacement_rows = [row for row in inventory if row["entity"] == "Replacement Starter"]
        self.assertTrue(replacement_rows)
        self.assertTrue(all(row["join_status"] == JOIN_STATUS_NEEDS_RESIM for row in replacement_rows))


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

    def test_raw_props_feed_is_loaded_once_and_attributed_via_probable_pitcher(self) -> None:
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AZ"},
                "home": {"abbr": "STL"},
                "status": {"abstract": "Live"},
                "probable": {"home": {"fullName": "Michael McGreevy"}},
                "markets": {},
            }
        ]
        raw_pitcher_lines = {"michael mcgreevy": {"outs": {"line": 17.5, "over_odds": "-145", "under_odds": "-105"}}}
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch("syndicate.features.mlb.cards._pitcher_snapshot_market_lines", return_value=raw_pitcher_lines), patch(
            "syndicate.features.mlb.cards._hitter_snapshot_market_lines", return_value={}
        ):
            board = build_mlb_market_board("2026-07-23")

        rows = board["games"][0]["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["side"] for row in rows}, {"over", "under"})
        self.assertEqual(rows[0]["market"], "Pitcher Outs")
        self.assertEqual(rows[0]["entity"], "Michael McGreevy")


class BuildMlbMarketBoardLiveHydrationTests(unittest.TestCase):
    """Live-projection/live-actual-stat-count, team logos, and player
    headshots -- the fields the user asked for so a mid-game prop's current
    count ("prop is HRR, mid-game player has 2, it shows 2") is readable
    directly on the market board, not just in the curated Layer 2 view.
    """

    def test_team_logos_are_attached_from_existing_game_data(self) -> None:
        # No new lookup needed -- away/home dicts already carry a "logo"
        # URL from the same source the /mlb/cards page uses.
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AZ", "logo": "https://www.mlbstatic.com/team-logos/109.svg"},
                "home": {"abbr": "STL", "logo": "https://www.mlbstatic.com/team-logos/138.svg"},
                "status": {"abstract": "Preview"},
                "markets": {},
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ):
            board = build_mlb_market_board("2026-07-24")

        game = board["games"][0]
        self.assertEqual(game["away_logo"], "https://www.mlbstatic.com/team-logos/109.svg")
        self.assertEqual(game["home_logo"], "https://www.mlbstatic.com/team-logos/138.svg")

    def test_live_prop_row_is_hydrated_with_live_projection_and_actual(self) -> None:
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AZ"},
                "home": {"abbr": "STL"},
                "status": {"abstract": "Live"},
                "markets": {
                    "hitterProps": [
                        {
                            "player_name": "Riley Greene",
                            "market": "hitter_total_bases",
                            "prop": "batter_total_bases",
                            "selection": "over",
                            "market_line": 1.5,
                            "odds": "-105",
                            "edge": 0.05,
                        }
                    ]
                },
            }
        ]
        fake_live_lens_report = {
            "games": [
                {
                    "gamePk": 1,
                    "trackedProps": [
                        {
                            "playerName": "Riley Greene",
                            "marketLabel": "Hitter Total Bases",
                            "line": 1.5,
                            "liveProjection": 2.3,
                            "actual": 2,
                        }
                    ],
                }
            ]
        }
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch("syndicate.features.mlb.cards._mlb_live_lens_report", return_value=fake_live_lens_report):
            board = build_mlb_market_board("2026-07-24")

        row = board["games"][0]["rows"][0]
        self.assertEqual(row["live_projection"], 2.3)
        self.assertEqual(row["live_actual"], 2)

    def test_pregame_prop_row_is_not_hydrated_with_live_lens_data(self) -> None:
        # Live-lens rows only exist once a game has actually started -- a
        # pregame game must never call into the (possibly stale) report.
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AZ"},
                "home": {"abbr": "STL"},
                "status": {"abstract": "Preview"},
                "markets": {
                    "hitterProps": [
                        {
                            "player_name": "Riley Greene",
                            "market": "hitter_total_bases",
                            "prop": "batter_total_bases",
                            "selection": "over",
                            "market_line": 1.5,
                            "odds": "-105",
                            "edge": 0.05,
                        }
                    ]
                },
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch("syndicate.features.mlb.cards._mlb_live_lens_prop_rows_for_game") as mock_live_rows:
            board = build_mlb_market_board("2026-07-24")

        mock_live_rows.assert_not_called()
        row = board["games"][0]["rows"][0]
        self.assertNotIn("live_projection", row)
        self.assertNotIn("live_actual", row)

    def test_prop_row_entity_is_hydrated_with_headshot_via_roster_id_lookup(self) -> None:
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AZ"},
                "home": {"abbr": "STL"},
                "status": {"abstract": "Preview"},
                "markets": {
                    "hitterProps": [
                        {
                            "player_name": "Riley Greene",
                            "market": "hitter_total_bases",
                            "prop": "batter_total_bases",
                            "selection": "over",
                            "market_line": 1.5,
                            "odds": "-105",
                            "edge": 0.05,
                        }
                    ]
                },
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch(
            "syndicate.features.mlb.cards._mlb_player_id_lookup_for_game", return_value={"riley greene": 691026}
        ):
            board = build_mlb_market_board("2026-07-24")

        row = board["games"][0]["rows"][0]
        self.assertEqual(row["headshot_url"], _mlb_headshot_url(691026))

    def test_game_market_rows_are_not_hydrated_with_headshots(self) -> None:
        # Game-level rows (entity=None, e.g. Moneyline) have no player to
        # attribute a headshot to.
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "KC"},
                "home": {"abbr": "DET"},
                "status": {"abstract": "Preview"},
                "markets": {"ml": {"selection": "home", "model_prob": 0.695, "odds": "-229"}},
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch(
            "syndicate.features.mlb.cards._mlb_player_id_lookup_for_game", return_value={"someone": 123}
        ):
            board = build_mlb_market_board("2026-07-24")

        row = board["games"][0]["rows"][0]
        self.assertNotIn("headshot_url", row)


class MlbLiveLensPropRowsForGameTests(unittest.TestCase):
    def test_returns_tracked_props_for_matching_game_pk(self) -> None:
        report = {"games": [{"gamePk": 5, "trackedProps": [{"playerName": "A"}]}, {"gamePk": 6, "trackedProps": [{"playerName": "B"}]}]}
        rows = _mlb_live_lens_prop_rows_for_game(report, 5)
        self.assertEqual(rows, [{"playerName": "A"}])

    def test_falls_back_to_props_key_when_tracked_props_missing(self) -> None:
        report = {"games": [{"gamePk": 5, "props": [{"playerName": "A"}]}]}
        rows = _mlb_live_lens_prop_rows_for_game(report, 5)
        self.assertEqual(rows, [{"playerName": "A"}])

    def test_no_matching_game_returns_empty_list(self) -> None:
        report = {"games": [{"gamePk": 5, "trackedProps": [{"playerName": "A"}]}]}
        self.assertEqual(_mlb_live_lens_prop_rows_for_game(report, 999), [])


class MlbHydrateMarketBoardLiveProjectionTests(unittest.TestCase):
    def test_fuzzy_name_and_market_and_line_match_hydrates_row(self) -> None:
        row = {"entity": "Riley Greene", "market": "Hitter Total Bases", "line": 1.5}
        live_rows = [{"playerName": "Riley Greene", "marketLabel": "Hitter Total Bases", "line": 1.5, "liveProjection": 2.3, "actual": 2}]
        _mlb_hydrate_market_board_live_projection(row, live_rows)
        self.assertEqual(row["live_projection"], 2.3)
        self.assertEqual(row["live_actual"], 2)

    def test_mismatched_line_does_not_hydrate(self) -> None:
        row = {"entity": "Riley Greene", "market": "Hitter Total Bases", "line": 1.5}
        live_rows = [{"playerName": "Riley Greene", "marketLabel": "Hitter Total Bases", "line": 2.5, "liveProjection": 2.3, "actual": 2}]
        _mlb_hydrate_market_board_live_projection(row, live_rows)
        self.assertNotIn("live_projection", row)

    def test_no_entity_does_not_hydrate(self) -> None:
        row = {"entity": None, "market": "Moneyline", "line": None}
        live_rows = [{"playerName": "Riley Greene", "marketLabel": "Hitter Total Bases", "line": 1.5, "liveProjection": 2.3, "actual": 2}]
        _mlb_hydrate_market_board_live_projection(row, live_rows)
        self.assertNotIn("live_projection", row)


class MlbPlayerIdLookupForGameTests(unittest.TestCase):
    def test_builds_name_to_id_lookup_from_roster_snapshot(self) -> None:
        fake_roster_payload = {
            "away": {
                "lineup": {"batters": [{"id": 691026, "name": "Riley Greene"}]},
                "pitcher": {"id": 592866, "name": "Away Starter"},
            },
            "home": {
                "lineup": {"batters": [{"id": 700000, "name": "Home Batter"}]},
                "pitcher": {"id": 800000, "name": "Home Starter"},
            },
        }
        with patch("syndicate.features.mlb.cards._hr_load_roster_game_payload", return_value=fake_roster_payload), patch(
            "syndicate.features.mlb.cards._hr_lineup_batters",
            side_effect=lambda side_doc: side_doc.get("lineup", {}).get("batters", []),
        ), patch(
            "syndicate.features.mlb.cards._hr_profile_player_id", side_effect=lambda profile: profile.get("id")
        ), patch(
            "syndicate.features.mlb.cards._hr_profile_player_name", side_effect=lambda profile: profile.get("name")
        ), patch(
            "syndicate.features.mlb.cards._hr_side_pitcher_profile",
            side_effect=lambda side_doc: side_doc.get("pitcher"),
        ):
            lookup = _mlb_player_id_lookup_for_game("2026-07-24", 1)

        self.assertEqual(lookup[_normalize_live_name("Riley Greene")], 691026)
        self.assertEqual(lookup[_normalize_live_name("Away Starter")], 592866)
        self.assertEqual(lookup[_normalize_live_name("Home Batter")], 700000)
        self.assertEqual(lookup[_normalize_live_name("Home Starter")], 800000)

    def test_no_roster_payload_returns_empty_lookup(self) -> None:
        with patch("syndicate.features.mlb.cards._hr_load_roster_game_payload", return_value=None):
            self.assertEqual(_mlb_player_id_lookup_for_game("2026-07-24", 1), {})


class MlbOddsHistoryEntriesForTeamsTests(unittest.TestCase):
    def test_exact_team_and_market_type_match(self) -> None:
        odds_history = {
            "markets": {
                "event_id=abc|home_team=Detroit Tigers|away_team=Kansas City Royals|market=h2h|bookmaker=fanduel": {
                    "last_line": -229.0,
                    "previous_line": -210.0,
                    "delta": -19.0,
                    "movement": "down",
                },
                "event_id=abc|home_team=Detroit Tigers|away_team=Kansas City Royals|market=totals|bookmaker=fanduel": {
                    "last_line": 8.5,
                },
            }
        }
        entries = _mlb_odds_history_entries_for_teams(odds_history, "Kansas City Royals", "Detroit Tigers", "h2h")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["last_line"], -229.0)

    def test_no_match_returns_empty_list(self) -> None:
        odds_history = {"markets": {"event_id=abc|home_team=Detroit Tigers|away_team=Kansas City Royals|market=h2h|bookmaker=fanduel": {"last_line": -229.0}}}
        self.assertEqual(_mlb_odds_history_entries_for_teams(odds_history, "Arizona Diamondbacks", "St. Louis Cardinals", "h2h"), [])

    def test_missing_team_names_returns_empty_list(self) -> None:
        odds_history = {"markets": {"event_id=abc|home_team=Detroit Tigers|away_team=Kansas City Royals|market=h2h|bookmaker=fanduel": {"last_line": -229.0}}}
        self.assertEqual(_mlb_odds_history_entries_for_teams(odds_history, "", "", "h2h"), [])


class MlbHydrateMarketBoardLineMovementTests(unittest.TestCase):
    def test_hydrates_last_previous_and_delta_from_first_entry_with_data(self) -> None:
        row: dict[str, object] = {}
        entries = [{"last_line": 8.5, "previous_line": 9.0, "delta": -0.5, "movement": "down"}]
        _mlb_hydrate_market_board_line_movement(row, entries)
        self.assertEqual(row["line_last"], 8.5)
        self.assertEqual(row["line_previous"], 9.0)
        self.assertEqual(row["line_delta"], -0.5)
        self.assertEqual(row["line_trend"], "down")

    def test_computes_delta_when_missing(self) -> None:
        row: dict[str, object] = {}
        entries = [{"last_line": 8.5, "previous_line": 9.0, "delta": None, "movement": "flat"}]
        _mlb_hydrate_market_board_line_movement(row, entries)
        self.assertAlmostEqual(row["line_delta"], -0.5)

    def test_no_entries_does_not_hydrate(self) -> None:
        row: dict[str, object] = {}
        _mlb_hydrate_market_board_line_movement(row, [])
        self.assertEqual(row, {})

    def test_entry_with_no_line_data_is_skipped(self) -> None:
        row: dict[str, object] = {}
        entries = [{"last_line": None, "previous_line": None}, {"last_line": 8.5, "previous_line": 9.0, "delta": -0.5, "movement": "down"}]
        _mlb_hydrate_market_board_line_movement(row, entries)
        self.assertEqual(row["line_last"], 8.5)


class MlbOddsHistoryEntriesForPlayerTests(unittest.TestCase):
    def test_matches_player_and_fuzzy_market_label_across_both_sides(self) -> None:
        odds_history = {
            "markets": {
                "player_name=shane drohan|market=strikeouts|selection=over": {"last_line": 5.5, "last_odds": -125},
                "player_name=shane drohan|market=strikeouts|selection=under": {"last_line": 5.5, "last_odds": -102},
                "player_name=shane drohan|market=outs|selection=over": {"last_line": 17.5, "last_odds": -130},
            }
        }
        entries = _mlb_odds_history_entries_for_player(odds_history, "Shane Drohan", "Pitcher Strikeouts")
        self.assertEqual(len(entries), 2)
        sides = {entry["_side"] for entry in entries}
        self.assertEqual(sides, {"over", "under"})

    def test_no_match_for_different_player_returns_empty(self) -> None:
        odds_history = {"markets": {"player_name=shane drohan|market=strikeouts|selection=over": {"last_line": 5.5}}}
        self.assertEqual(_mlb_odds_history_entries_for_player(odds_history, "Someone Else", "Strikeouts"), [])

    def test_missing_player_or_market_returns_empty(self) -> None:
        odds_history = {"markets": {"player_name=shane drohan|market=strikeouts|selection=over": {"last_line": 5.5}}}
        self.assertEqual(_mlb_odds_history_entries_for_player(odds_history, "", "Strikeouts"), [])
        self.assertEqual(_mlb_odds_history_entries_for_player(odds_history, "Shane Drohan", ""), [])


class MlbHydrateMarketBoardPropMovementTests(unittest.TestCase):
    def test_hydrates_line_and_odds_movement_for_matching_side(self) -> None:
        row: dict[str, object] = {"side": "over"}
        entries = [
            {
                "_side": "over",
                "last_line": 5.5,
                "previous_line": 4.5,
                "delta": 1.0,
                "movement": "up",
                "last_odds": -125,
                "history": [{"last_odds": -110}, {"last_odds": -125}],
            },
            {"_side": "under", "last_line": 5.5, "previous_line": 4.5, "last_odds": -102, "history": []},
        ]
        _mlb_hydrate_market_board_prop_movement(row, entries)
        self.assertEqual(row["line_last"], 5.5)
        self.assertEqual(row["line_previous"], 4.5)
        self.assertEqual(row["line_delta"], 1.0)
        self.assertEqual(row["line_trend"], "up")
        self.assertEqual(row["odds_last"], -125)
        self.assertEqual(row["odds_previous"], -110)
        self.assertAlmostEqual(row["odds_delta"], -15.0)
        self.assertEqual(row["odds_trend"], "down")

    def test_only_matches_entry_for_the_rows_own_side(self) -> None:
        row: dict[str, object] = {"side": "under"}
        entries = [
            {"_side": "over", "last_line": 5.5, "previous_line": 4.5, "last_odds": -125, "history": []},
            {"_side": "under", "last_line": 5.5, "previous_line": 4.5, "last_odds": -102, "history": []},
        ]
        _mlb_hydrate_market_board_prop_movement(row, entries)
        self.assertEqual(row["odds_last"], -102)

    def test_no_entries_does_not_hydrate(self) -> None:
        row: dict[str, object] = {"side": "over"}
        _mlb_hydrate_market_board_prop_movement(row, [])
        self.assertEqual(row, {"side": "over"})

    def test_odds_delta_flat_when_no_prior_history(self) -> None:
        row: dict[str, object] = {"side": "over"}
        entries = [{"_side": "over", "last_line": 5.5, "previous_line": 4.5, "last_odds": -125, "history": [{"last_odds": -125}]}]
        _mlb_hydrate_market_board_prop_movement(row, entries)
        self.assertIsNone(row["odds_previous"])
        self.assertIsNone(row["odds_delta"])
        self.assertEqual(row["odds_trend"], "flat")


class BuildMlbMarketBoardLineMovementWiringTests(unittest.TestCase):
    def test_game_market_row_is_hydrated_with_line_movement(self) -> None:
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "KC", "name": "Kansas City Royals"},
                "home": {"abbr": "DET", "name": "Detroit Tigers"},
                "status": {"abstract": "Preview"},
                "markets": {"ml": {"selection": "home", "model_prob": 0.695, "odds": "-229"}},
            }
        ]
        fake_odds_history = {
            "markets": {
                "event_id=abc|home_team=Detroit Tigers|away_team=Kansas City Royals|market=h2h|bookmaker=fanduel": {
                    "last_line": -229.0,
                    "previous_line": -200.0,
                    "delta": -29.0,
                    "movement": "down",
                }
            }
        }
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch("syndicate.features.mlb.cards._mlb_odds_history_payload", return_value=fake_odds_history):
            board = build_mlb_market_board("2026-07-23")

        row = board["games"][0]["rows"][0]
        self.assertEqual(row["line_last"], -229.0)
        self.assertEqual(row["line_trend"], "down")

    def test_prop_row_is_not_hydrated_with_line_movement(self) -> None:
        fake_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AZ", "name": "Arizona Diamondbacks"},
                "home": {"abbr": "STL", "name": "St. Louis Cardinals"},
                "status": {"abstract": "Preview"},
                "markets": {
                    "hitterProps": [
                        {
                            "player_name": "Riley Greene",
                            "market": "hitter_total_bases",
                            "prop": "batter_total_bases",
                            "selection": "over",
                            "market_line": 1.5,
                            "odds": "-105",
                            "edge": 0.05,
                        }
                    ]
                },
            }
        ]
        with patch("syndicate.features.mlb.cards.build_cards_page_context", return_value={"games": fake_games}), patch(
            "syndicate.features.mlb.cards.source_cards_api_payload", return_value={"games": fake_games}
        ), patch(
            "syndicate.features.mlb.cards._mlb_odds_history_entries_for_teams"
        ) as mock_entries:
            board = build_mlb_market_board("2026-07-23")

        mock_entries.assert_not_called()
        row = board["games"][0]["rows"][0]
        self.assertNotIn("line_last", row)


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
