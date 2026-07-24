from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NO_SIM_COVERAGE
from syndicate.features.soccer.market_board import _normalize_soccer_name
from syndicate.features.soccer.market_board import _soccer_hydrate_market_board_line_movement
from syndicate.features.soccer.market_board import _soccer_market_board_game_rows_for_match
from syndicate.features.soccer.market_board import _soccer_market_board_prop_rows_for_match
from syndicate.features.soccer.market_board import _soccer_market_board_sim_rows_for_match
from syndicate.features.soccer.market_board import _soccer_odds_history_key
from syndicate.features.soccer.market_board import build_soccer_market_board
from syndicate.features.shared.market_inventory import join_odds_to_sim


_FAKE_GAME_ODDS_ROWS = [
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "home", "line": "", "price": "210", "book": "fanduel"},
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "draw", "line": "", "price": "260", "book": "fanduel"},
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "away", "line": "", "price": "320", "book": "fanduel"},
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "totals", "side": "over", "line": "2.5", "price": "-115", "book": "fanduel"},
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "totals", "side": "under", "line": "2.5", "price": "-105", "book": "fanduel"},
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "spreads", "side": "home", "line": "-0.5", "price": "-130", "book": "fanduel"},
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "spreads", "side": "away", "line": "0.5", "price": "+105", "book": "fanduel"},
    # A second bookmaker quoting the SAME market/side -- must be deduped to
    # one representative row, not two.
    {"league": "mls", "event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "home", "line": "", "price": "205", "book": "betmgm"},
    # A different event entirely -- must be ignored.
    {"league": "mls", "event_id": "999", "home_team": "Other", "away_team": "Team", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "home", "line": "", "price": "150", "book": "fanduel"},
]

_FAKE_MATCH = {
    "event_id": "1",
    "kickoff": "2026-07-22T23:30Z",
    "status_state": "pre",
    "matchup": {"home_team": "Columbus Crew", "away_team": "New York City FC"},
    "win_probability": {"home": 0.46, "draw": 0.225, "away": 0.315},
    "total_distribution": {"mean": 3.21, "over_2_5_probability": 0.6275},
    "top_props": [
        {"player_id": "asa_x", "player_name": "Diego Rossi", "team": "Columbus Crew", "anytime_scorer_probability": 0.3342},
    ],
}

_FAKE_PROPS_ROWS = [
    {"league": "mls", "player": "Diego Rossi", "market": "Anytime Goalscorer", "market_key": "player_goal_scorer_anytime", "line": "", "over_price": "250", "under_price": "", "book": "betmgm", "event": "x", "event_id": "1", "game_time": "2026-07-22T23:30:00Z", "home_team": "Columbus Crew", "away_team": "New York City FC"},
    {"league": "mls", "player": "Some Defender", "market": "Shots On Target", "market_key": "player_shots_on_target", "line": "0.5", "over_price": "150", "under_price": "-200", "book": "betmgm", "event": "x", "event_id": "1", "game_time": "2026-07-22T23:30:00Z", "home_team": "Columbus Crew", "away_team": "New York City FC"},
]


class NormalizeSoccerNameTests(unittest.TestCase):
    def test_strips_accents_and_case(self) -> None:
        self.assertEqual(_normalize_soccer_name("Álvarez"), "alvarez")
        self.assertEqual(_normalize_soccer_name("  Diego   Rossi "), "diego rossi")


class SoccerMarketBoardGameRowsTests(unittest.TestCase):
    def test_three_way_moneyline_produces_disambiguated_side_markets(self) -> None:
        odds_rows, picked = _soccer_market_board_game_rows_for_match(event_id="1", game_odds_rows_all=_FAKE_GAME_ODDS_ROWS)
        moneyline_rows = [row for row in odds_rows if row["market"].startswith("moneyline_")]
        self.assertEqual({row["market"] for row in moneyline_rows}, {"moneyline_home", "moneyline_draw", "moneyline_away"})
        self.assertEqual(len(moneyline_rows), 3)

    def test_second_bookmaker_on_same_market_side_is_deduped(self) -> None:
        odds_rows, picked = _soccer_market_board_game_rows_for_match(event_id="1", game_odds_rows_all=_FAKE_GAME_ODDS_ROWS)
        home_ml_rows = [row for row in odds_rows if row["market"] == "moneyline_home"]
        self.assertEqual(len(home_ml_rows), 1)
        self.assertEqual(home_ml_rows[0]["odds"], 210.0)
        self.assertEqual(picked[("h2h", "home")]["book"], "fanduel")

    def test_totals_and_spreads_are_included(self) -> None:
        odds_rows, _ = _soccer_market_board_game_rows_for_match(event_id="1", game_odds_rows_all=_FAKE_GAME_ODDS_ROWS)
        total_rows = [row for row in odds_rows if row["market"] == "total"]
        spread_rows = [row for row in odds_rows if row["market"] == "spread"]
        self.assertEqual(len(total_rows), 2)
        self.assertEqual(len(spread_rows), 2)
        self.assertEqual({row["side"] for row in total_rows}, {"over", "under"})

    def test_other_events_are_excluded(self) -> None:
        odds_rows, _ = _soccer_market_board_game_rows_for_match(event_id="1", game_odds_rows_all=_FAKE_GAME_ODDS_ROWS)
        self.assertTrue(all(row["game_id"] == "1" for row in odds_rows))
        self.assertEqual(len(odds_rows), 7)


class SoccerMarketBoardSimRowsTests(unittest.TestCase):
    def test_win_probability_and_totals_produce_sim_rows(self) -> None:
        sim_rows = _soccer_market_board_sim_rows_for_match(event_id="1", match=_FAKE_MATCH)
        by_market = {row["market"]: row for row in sim_rows}
        self.assertAlmostEqual(by_market["moneyline_home"]["sim_projection"], 0.46)
        self.assertAlmostEqual(by_market["moneyline_draw"]["sim_projection"], 0.225)
        self.assertAlmostEqual(by_market["moneyline_away"]["sim_projection"], 0.315)
        self.assertAlmostEqual(by_market["total"]["sim_projection"], 0.6275)

    def test_missing_fields_produce_no_rows(self) -> None:
        self.assertEqual(_soccer_market_board_sim_rows_for_match(event_id="1", match={}), [])


class SoccerMarketBoardPropRowsTests(unittest.TestCase):
    def test_anytime_goalscorer_probability_is_wired_from_top_props(self) -> None:
        odds_rows, sim_rows = _soccer_market_board_prop_rows_for_match(event_id="1", match=_FAKE_MATCH, props_rows_all=_FAKE_PROPS_ROWS)
        rossi_odds = [row for row in odds_rows if row["entity"] == "Diego Rossi"]
        self.assertEqual(len(rossi_odds), 1)
        self.assertEqual(rossi_odds[0]["side"], "over")
        rossi_sim = [row for row in sim_rows if row["entity"] == "Diego Rossi"]
        self.assertEqual(len(rossi_sim), 1)
        self.assertAlmostEqual(rossi_sim[0]["sim_projection"], 0.3342)

    def test_shots_on_target_has_no_sim_coverage_but_still_produces_odds_rows(self) -> None:
        # Only markets where SoccerSim exposes a genuine 0-1 probability are
        # wired to sim_projection today -- a raw expected-count value would
        # mis-render as a nonsensical percentage on the board, so shots
        # props still show up as real quoted lines, just unmodeled.
        odds_rows, sim_rows = _soccer_market_board_prop_rows_for_match(event_id="1", match=_FAKE_MATCH, props_rows_all=_FAKE_PROPS_ROWS)
        defender_odds = [row for row in odds_rows if row["entity"] == "Some Defender"]
        self.assertEqual(len(defender_odds), 2)
        self.assertEqual({row["side"] for row in defender_odds}, {"over", "under"})
        defender_sim = [row for row in sim_rows if row["entity"] == "Some Defender"]
        self.assertEqual(defender_sim, [])

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        defender_inventory = [row for row in inventory if row["entity"] == "Some Defender"]
        self.assertTrue(all(row["join_status"] == JOIN_STATUS_NO_SIM_COVERAGE for row in defender_inventory))


class SoccerOddsHistoryKeyTests(unittest.TestCase):
    def test_key_matches_write_side_field_order_and_case(self) -> None:
        row = {"event_id": "1", "home_team": "Columbus Crew", "away_team": "New York City FC", "market": "h2h", "side": "home", "book": "fanduel"}
        key = _soccer_odds_history_key(row)
        self.assertEqual(key, "event_id=1|home_team=Columbus Crew|away_team=New York City FC|market=h2h|side=home|book=fanduel")


class SoccerHydrateMarketBoardLineMovementTests(unittest.TestCase):
    def test_hydrates_from_entry(self) -> None:
        row: dict[str, object] = {}
        entry = {"last_line": 210.0, "previous_line": 190.0, "delta": 20.0, "movement": "up"}
        _soccer_hydrate_market_board_line_movement(row, entry)
        self.assertEqual(row["line_last"], 210.0)
        self.assertEqual(row["line_trend"], "up")

    def test_no_entry_does_not_hydrate(self) -> None:
        row: dict[str, object] = {}
        _soccer_hydrate_market_board_line_movement(row, None)
        self.assertEqual(row, {})


class BuildSoccerMarketBoardTests(unittest.TestCase):
    def test_full_board_join_hydration_and_relabeling(self) -> None:
        fake_recommendations = {"matches": [_FAKE_MATCH]}
        fake_odds_history = {
            "markets": {
                "event_id=1|home_team=Columbus Crew|away_team=New York City FC|market=h2h|side=home|book=fanduel": {
                    "last_line": 210.0,
                    "previous_line": 190.0,
                    "delta": 20.0,
                    "movement": "up",
                }
            }
        }
        fake_headshots = {"diego rossi": "https://a.espncdn.com/i/headshots/soccer/players/full/12345.png"}
        with patch("syndicate.features.soccer.market_board.recommendations_payload", return_value=fake_recommendations), patch(
            "syndicate.features.soccer.market_board.game_odds_rows", return_value=tuple(_FAKE_GAME_ODDS_ROWS)
        ), patch("syndicate.features.soccer.market_board.props_odds_rows", return_value=tuple(_FAKE_PROPS_ROWS)), patch(
            "syndicate.features.soccer.market_board._soccer_headshot_lookup", return_value=fake_headshots
        ), patch(
            "syndicate.features.soccer.market_board._soccer_odds_history_payload", return_value=fake_odds_history
        ), patch(
            "syndicate.features.soccer.market_board.team_by_name", return_value={"logo_url": "https://example.com/logo.svg"}
        ):
            board = build_soccer_market_board("mls", "2026-07-22")

        self.assertEqual(board["league"], "mls")
        game = board["games"][0]
        self.assertEqual(game["matchup"], "New York City FC @ Columbus Crew")
        self.assertEqual(game["away_logo"], "https://example.com/logo.svg")
        rows = game["rows"]

        home_ml = next(row for row in rows if row["market"] == "Moneyline" and row["side"] == "home")
        self.assertEqual(home_ml["join_status"], JOIN_STATUS_MATCHED)
        self.assertEqual(home_ml["line_last"], 210.0)
        self.assertEqual(home_ml["line_trend"], "up")

        rossi_prop = next(row for row in rows if row.get("entity") == "Diego Rossi")
        self.assertEqual(rossi_prop["headshot_url"], fake_headshots["diego rossi"])
        self.assertEqual(rossi_prop["join_status"], JOIN_STATUS_MATCHED)

    def test_empty_matches_produces_empty_board(self) -> None:
        with patch("syndicate.features.soccer.market_board.recommendations_payload", return_value={}), patch(
            "syndicate.features.soccer.market_board.game_odds_rows", return_value=()
        ), patch("syndicate.features.soccer.market_board.props_odds_rows", return_value=()):
            board = build_soccer_market_board("mls", "2026-07-22")
        self.assertEqual(board["games"], [])


if __name__ == "__main__":
    unittest.main()
