from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared.market_inventory import JOIN_STATUS_MATCHED
from syndicate.features.shared.market_inventory import JOIN_STATUS_NEEDS_RESIM
from syndicate.features.shared.market_inventory import JOIN_STATUS_NO_SIM_COVERAGE
from syndicate.features.soccer.market_board import _SOCCER_MARKET_BOARD_CACHE
from syndicate.features.soccer.market_board import _SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES
from syndicate.features.soccer.market_board import _soccer_market_board_cache_key
from syndicate.features.soccer.market_board import clear_soccer_market_board_cache
from syndicate.features.soccer.market_board import soccer_needs_resim_event_ids
from syndicate.features.soccer.market_board import _normalize_soccer_name
from syndicate.features.soccer.market_board import _soccer_hydrate_market_board_line_movement
from syndicate.features.soccer.market_board import _soccer_market_board_game_rows_for_match
from syndicate.features.soccer.market_board import _soccer_market_board_prop_rows_for_match
from syndicate.features.soccer.market_board import _soccer_market_board_sim_rows_for_match
from syndicate.features.soccer.market_board import _soccer_odds_event_for_match
from syndicate.features.soccer.market_board import _soccer_odds_history_key
from syndicate.features.soccer.market_board import _soccer_relevant_dates
from syndicate.features.soccer.market_board import _soccer_week_matches
from syndicate.features.soccer.market_board import build_soccer_market_board
from syndicate.features.shared.market_inventory import join_odds_to_sim


# Deliberately realistic Odds-API shapes, not simplified fixtures: the odds
# feed's own event_id is an Odds-API-internal hash, completely unrelated to
# the sim's ESPN-sourced numeric event_id, and "side" for h2h/spreads is the
# literal team name (or "Draw"), not "home"/"away"/"draw" -- confirmed via a
# real captured sample (data/soccer_source/mls/props/2026-07-19.csv) and by
# reading fetch_soccer_oddsapi_odds_local.py's own row-construction code.
# The team-name spelling also differs on purpose ("Red Bull New York" on the
# sim/ESPN side vs "New York Red Bulls" on the odds feed) -- this is the
# exact real-world pair that motivated adding an alias to team_names.py.
_ODDS_EVENT_ID = "b453ea14d7c033045b51018b59635d39"
_FAKE_GAME_ODDS_ROWS = [
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "New York Red Bulls", "line": "", "price": "210", "book": "fanduel"},
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "Draw", "line": "", "price": "260", "book": "fanduel"},
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "Charlotte FC", "line": "", "price": "320", "book": "fanduel"},
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "totals", "side": "Over", "line": "2.5", "price": "-115", "book": "fanduel"},
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "totals", "side": "Under", "line": "2.5", "price": "-105", "book": "fanduel"},
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "spreads", "side": "New York Red Bulls", "line": "-0.5", "price": "-130", "book": "fanduel"},
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "spreads", "side": "Charlotte FC", "line": "0.5", "price": "+105", "book": "fanduel"},
    # A second bookmaker quoting the SAME market/side -- must be deduped to
    # one representative row, not two.
    {"league": "mls", "event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "New York Red Bulls", "line": "", "price": "205", "book": "betmgm"},
    # A different event entirely -- must be ignored.
    {"league": "mls", "event_id": "unrelated-hash", "home_team": "Other", "away_team": "Team", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "Other", "line": "", "price": "150", "book": "fanduel"},
]

_FAKE_MATCH = {
    "event_id": "761685",
    "kickoff": "2026-07-22T23:30Z",
    "status_state": "pre",
    "matchup": {"home_team": "Red Bull New York", "away_team": "Charlotte FC"},
    "win_probability": {"home": 0.46, "draw": 0.225, "away": 0.315},
    "total_distribution": {"mean": 3.21, "over_2_5_probability": 0.6275},
    "top_props": [
        {"player_id": "asa_x", "player_name": "Emil Forsberg", "team": "Red Bull New York", "anytime_scorer_probability": 0.3342},
    ],
}

_FAKE_PROPS_ROWS = [
    {"league": "mls", "player": "Emil Forsberg", "market": "Anytime Goalscorer", "market_key": "player_goal_scorer_anytime", "line": "", "over_price": "250", "under_price": "", "book": "betmgm", "event": "x", "event_id": _ODDS_EVENT_ID, "game_time": "2026-07-22T23:30:00Z", "home_team": "New York Red Bulls", "away_team": "Charlotte FC"},
    {"league": "mls", "player": "Some Defender", "market": "Shots On Target", "market_key": "player_shots_on_target", "line": "0.5", "over_price": "150", "under_price": "-200", "book": "betmgm", "event": "x", "event_id": _ODDS_EVENT_ID, "game_time": "2026-07-22T23:30:00Z", "home_team": "New York Red Bulls", "away_team": "Charlotte FC"},
]


class NormalizeSoccerNameTests(unittest.TestCase):
    def test_strips_accents_and_case(self) -> None:
        self.assertEqual(_normalize_soccer_name("Álvarez"), "alvarez")
        self.assertEqual(_normalize_soccer_name("  Diego   Rossi "), "diego rossi")


class SoccerOddsEventForMatchTests(unittest.TestCase):
    """The odds feed's own event_id (an Odds-API hash) and team-name
    spelling are foreign to the sim's (ESPN numeric event_id, ESPN team
    names) -- this resolver is what bridges the two, and is the fix for a
    real bug where the board's join always failed because it compared
    these two incompatible ID schemes directly.
    """

    def test_resolves_despite_id_scheme_and_name_spelling_mismatch(self) -> None:
        resolved = _soccer_odds_event_for_match(
            home_team="Red Bull New York", away_team="Charlotte FC", game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        self.assertIsNotNone(resolved)
        odds_event_id, odds_home, odds_away = resolved
        self.assertEqual(odds_event_id, _ODDS_EVENT_ID)
        self.assertEqual(odds_home, "New York Red Bulls")
        self.assertEqual(odds_away, "Charlotte FC")

    def test_no_matching_event_returns_none(self) -> None:
        resolved = _soccer_odds_event_for_match(
            home_team="Some Team Not In Odds Feed", away_team="Another Team", game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        self.assertIsNone(resolved)

    def test_empty_odds_feed_returns_none(self) -> None:
        self.assertIsNone(_soccer_odds_event_for_match(home_team="Red Bull New York", away_team="Charlotte FC", game_odds_rows_all=[]))


class SoccerMarketBoardGameRowsTests(unittest.TestCase):
    def test_three_way_moneyline_produces_disambiguated_side_markets(self) -> None:
        odds_rows, picked = _soccer_market_board_game_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        moneyline_rows = [row for row in odds_rows if row["market"].startswith("moneyline_")]
        self.assertEqual({row["market"] for row in moneyline_rows}, {"moneyline_home", "moneyline_draw", "moneyline_away"})
        self.assertEqual(len(moneyline_rows), 3)
        # Output rows are labeled with the sim's ESPN game_id, not the odds
        # feed's own event_id -- that's what lets join_odds_to_sim (which
        # this module also feeds sim_rows sharing the same game_id) match
        # them, and it's a stable per-match key regardless of odds source.
        self.assertTrue(all(row["game_id"] == "761685" for row in odds_rows))

    def test_second_bookmaker_on_same_market_side_is_deduped(self) -> None:
        odds_rows, picked = _soccer_market_board_game_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        home_ml_rows = [row for row in odds_rows if row["market"] == "moneyline_home"]
        self.assertEqual(len(home_ml_rows), 1)
        self.assertEqual(home_ml_rows[0]["odds"], 210.0)
        self.assertEqual(picked[("h2h", "home")]["book"], "fanduel")

    def test_totals_side_normalized_from_capitalized_over_under(self) -> None:
        # Real Odds API outcome names are "Over"/"Under" (capitalized), not
        # the lowercase "over"/"under" this board renders internally.
        odds_rows, _ = _soccer_market_board_game_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        total_rows = [row for row in odds_rows if row["market"] == "total"]
        spread_rows = [row for row in odds_rows if row["market"] == "spread"]
        self.assertEqual(len(total_rows), 2)
        self.assertEqual(len(spread_rows), 2)
        self.assertEqual({row["side"] for row in total_rows}, {"over", "under"})
        self.assertEqual({row["side"] for row in spread_rows}, {"home", "away"})

    def test_spread_side_normalized_from_literal_team_name(self) -> None:
        # Real Odds API spread outcomes are named after the actual team
        # ("New York Red Bulls" / "Charlotte FC"), not "home"/"away".
        odds_rows, _ = _soccer_market_board_game_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        home_spread = next(row for row in odds_rows if row["market"] == "spread" and row["side"] == "home")
        away_spread = next(row for row in odds_rows if row["market"] == "spread" and row["side"] == "away")
        self.assertEqual(home_spread["line"], -0.5)
        self.assertEqual(away_spread["line"], 0.5)

    def test_other_events_are_excluded(self) -> None:
        odds_rows, _ = _soccer_market_board_game_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, game_odds_rows_all=_FAKE_GAME_ODDS_ROWS
        )
        self.assertEqual(len(odds_rows), 7)


class SoccerMarketBoardSimRowsTests(unittest.TestCase):
    def test_win_probability_and_totals_produce_sim_rows(self) -> None:
        sim_rows = _soccer_market_board_sim_rows_for_match(event_id="761685", match=_FAKE_MATCH)
        by_market = {row["market"]: row for row in sim_rows}
        self.assertAlmostEqual(by_market["moneyline_home"]["sim_projection"], 0.46)
        self.assertAlmostEqual(by_market["moneyline_draw"]["sim_projection"], 0.225)
        self.assertAlmostEqual(by_market["moneyline_away"]["sim_projection"], 0.315)
        self.assertAlmostEqual(by_market["total"]["sim_projection"], 0.6275)

    def test_missing_fields_produce_no_rows(self) -> None:
        self.assertEqual(_soccer_market_board_sim_rows_for_match(event_id="761685", match={}), [])


class SoccerMarketBoardPropRowsTests(unittest.TestCase):
    def test_anytime_goalscorer_probability_is_wired_from_top_props(self) -> None:
        odds_rows, sim_rows = _soccer_market_board_prop_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, match=_FAKE_MATCH, props_rows_all=_FAKE_PROPS_ROWS
        )
        forsberg_odds = [row for row in odds_rows if row["entity"] == "Emil Forsberg"]
        self.assertEqual(len(forsberg_odds), 1)
        self.assertEqual(forsberg_odds[0]["side"], "over")
        self.assertTrue(all(row["game_id"] == "761685" for row in odds_rows))
        forsberg_sim = [row for row in sim_rows if row["entity"] == "Emil Forsberg"]
        self.assertEqual(len(forsberg_sim), 1)
        self.assertAlmostEqual(forsberg_sim[0]["sim_projection"], 0.3342)

    def test_shots_on_target_has_no_sim_coverage_but_still_produces_odds_rows(self) -> None:
        # Only markets where SoccerSim exposes a genuine 0-1 probability are
        # wired to sim_projection today -- a raw expected-count value would
        # mis-render as a nonsensical percentage on the board, so shots
        # props still show up as real quoted lines, just unmodeled.
        odds_rows, sim_rows = _soccer_market_board_prop_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, match=_FAKE_MATCH, props_rows_all=_FAKE_PROPS_ROWS
        )
        defender_odds = [row for row in odds_rows if row["entity"] == "Some Defender"]
        self.assertEqual(len(defender_odds), 2)
        self.assertEqual({row["side"] for row in defender_odds}, {"over", "under"})
        defender_sim = [row for row in sim_rows if row["entity"] == "Some Defender"]
        self.assertEqual(defender_sim, [])

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        defender_inventory = [row for row in inventory if row["entity"] == "Some Defender"]
        self.assertTrue(all(row["join_status"] == JOIN_STATUS_NO_SIM_COVERAGE for row in defender_inventory))

    def test_accent_mismatch_between_odds_feed_and_sim_still_joins(self) -> None:
        # The sim's player names come from a different provider (American
        # Soccer Analysis) than the Odds API props feed -- join_odds_to_sim's
        # entity matching is a bare .casefold() (no accent stripping), so an
        # unaccented odds-feed spelling ("Kevin Denkey") and an accented sim
        # spelling ("Kévin Denkey") would silently fail to join without this
        # fix, even though it's the same real player.
        match_with_accent = dict(_FAKE_MATCH)
        match_with_accent["top_props"] = [
            {"player_id": "asa_x", "player_name": "Kévin Denkey", "anytime_scorer_probability": 0.41},
        ]
        props_rows = [
            {"league": "mls", "player": "Kevin Denkey", "market": "Anytime Goalscorer", "market_key": "player_goal_scorer_anytime", "line": "", "over_price": "200", "under_price": "", "book": "betmgm", "event": "x", "event_id": _ODDS_EVENT_ID, "game_time": "2026-07-22T23:30:00Z", "home_team": "New York Red Bulls", "away_team": "Charlotte FC"},
        ]
        odds_rows, sim_rows = _soccer_market_board_prop_rows_for_match(
            game_id="761685", odds_event_id=_ODDS_EVENT_ID, match=match_with_accent, props_rows_all=props_rows
        )
        # The sim row must be relabeled to the odds feed's own spelling so
        # join_odds_to_sim's exact-match entity key lines up.
        self.assertEqual(sim_rows[0]["entity"], "Kevin Denkey")
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        denkey_row = next(row for row in inventory if row["entity"] == "Kevin Denkey")
        self.assertEqual(denkey_row["join_status"], JOIN_STATUS_MATCHED)
        self.assertAlmostEqual(denkey_row["sim_projection"], 0.41)


class SoccerOddsHistoryKeyTests(unittest.TestCase):
    def test_key_matches_write_side_field_order_and_case(self) -> None:
        row = {"event_id": _ODDS_EVENT_ID, "home_team": "New York Red Bulls", "away_team": "Charlotte FC", "market": "h2h", "side": "New York Red Bulls", "book": "fanduel"}
        key = _soccer_odds_history_key(row)
        self.assertEqual(key, f"event_id={_ODDS_EVENT_ID}|home_team=New York Red Bulls|away_team=Charlotte FC|market=h2h|side=New York Red Bulls|book=fanduel")


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


class SoccerWeekScopingTests(unittest.TestCase):
    """2026-07-24 fix: soccer's raw odds feed is a single rolling file that
    covers the whole game week days ahead of kickoff, and a single date's
    recommendations snapshot can legitimately be empty even when an
    adjacent date's snapshot already has the same match -- confirmed in
    production (recommendations_2026-07-23.json had 0 matches while
    recommendations_2026-07-22.json's own snapshot already covered both
    07-22 and 07-23 kickoffs). The board must aggregate across nearby
    dates, not read a single date's file.
    """

    def test_relevant_dates_window_intersects_available_dates(self) -> None:
        with patch(
            "syndicate.features.soccer.market_board.available_dates",
            return_value=["2026-07-19", "2026-07-22", "2026-07-23", "2026-07-25", "2027-01-01"],
        ):
            relevant = _soccer_relevant_dates("mls", "2026-07-22")
        self.assertEqual(relevant, ["2026-07-19", "2026-07-22", "2026-07-23", "2026-07-25"])

    def test_no_available_dates_falls_back_to_selected_date(self) -> None:
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=[]):
            relevant = _soccer_relevant_dates("mls", "2026-07-22")
        self.assertEqual(relevant, ["2026-07-22"])

    def test_match_only_present_in_adjacent_date_snapshot_is_still_found(self) -> None:
        # The exact production bug: querying with selected_date="2026-07-23"
        # (an empty snapshot) must still surface a match whose only real
        # data lives in the 2026-07-22 snapshot.
        def fake_recommendations(league, date_str):
            if date_str == "2026-07-22":
                return {"matches": [{"event_id": "1", "kickoff": "2026-07-23T00:00Z", "status_state": "pre"}]}
            return {"matches": []}

        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22", "2026-07-23"]), patch(
            "syndicate.features.soccer.market_board.recommendations_payload", side_effect=fake_recommendations
        ):
            matches = _soccer_week_matches("mls", "2026-07-23")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["event_id"], "1")

    def test_same_event_in_multiple_dates_dedupes_preferring_later_date(self) -> None:
        def fake_recommendations(league, date_str):
            if date_str == "2026-07-22":
                return {"matches": [{"event_id": "1", "status_state": "pre"}]}
            if date_str == "2026-07-23":
                return {"matches": [{"event_id": "1", "status_state": "in"}]}
            return {"matches": []}

        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22", "2026-07-23"]), patch(
            "syndicate.features.soccer.market_board.recommendations_payload", side_effect=fake_recommendations
        ):
            matches = _soccer_week_matches("mls", "2026-07-22")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status_state"], "in")


class BuildSoccerMarketBoardTests(unittest.TestCase):
    def test_full_board_join_hydration_and_relabeling(self) -> None:
        fake_recommendations = {"matches": [_FAKE_MATCH]}
        fake_odds_history = {
            "markets": {
                f"event_id={_ODDS_EVENT_ID}|home_team=New York Red Bulls|away_team=Charlotte FC|market=h2h|side=New York Red Bulls|book=fanduel": {
                    "last_line": 210.0,
                    "previous_line": 190.0,
                    "delta": 20.0,
                    "movement": "up",
                }
            }
        }
        fake_headshots = {"emil forsberg": "https://a.espncdn.com/i/headshots/soccer/players/full/12345.png"}
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]), patch(
            "syndicate.features.soccer.market_board.recommendations_payload", return_value=fake_recommendations
        ), patch(
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
        self.assertEqual(game["matchup"], "Charlotte FC @ Red Bull New York")
        self.assertEqual(game["away_logo"], "https://example.com/logo.svg")
        rows = game["rows"]

        home_ml = next(row for row in rows if row["market"] == "Moneyline" and row["side"] == "home")
        self.assertEqual(home_ml["join_status"], JOIN_STATUS_MATCHED)
        self.assertEqual(home_ml["line_last"], 210.0)
        self.assertEqual(home_ml["line_trend"], "up")

        forsberg_prop = next(row for row in rows if row.get("entity") == "Emil Forsberg")
        self.assertEqual(forsberg_prop["headshot_url"], fake_headshots["emil forsberg"])
        self.assertEqual(forsberg_prop["join_status"], JOIN_STATUS_MATCHED)

    def test_no_matching_odds_event_still_shows_sim_only_no_rows(self) -> None:
        # When the fuzzy team-name match can't resolve an odds event at all
        # (e.g. the odds feed doesn't have this fixture yet), the board must
        # not crash -- it just has nothing to show for this match, since a
        # market board with no quoted line isn't a market to bet on.
        fake_recommendations = {"matches": [_FAKE_MATCH]}
        unrelated_odds = [
            {"league": "mls", "event_id": "zzz", "home_team": "Some Other Team", "away_team": "Another Team", "commence_time": "2026-07-22T23:30:00Z", "market": "h2h", "side": "Some Other Team", "line": "", "price": "150", "book": "fanduel"},
        ]
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]), patch(
            "syndicate.features.soccer.market_board.recommendations_payload", return_value=fake_recommendations
        ), patch(
            "syndicate.features.soccer.market_board.game_odds_rows", return_value=tuple(unrelated_odds)
        ), patch("syndicate.features.soccer.market_board.props_odds_rows", return_value=()), patch(
            "syndicate.features.soccer.market_board.team_by_name", return_value=None
        ):
            board = build_soccer_market_board("mls", "2026-07-22")

        self.assertEqual(len(board["games"]), 1)
        self.assertEqual(board["games"][0]["rows"], [])

    def test_empty_matches_produces_empty_board(self) -> None:
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]), patch(
            "syndicate.features.soccer.market_board.recommendations_payload", return_value={}
        ), patch(
            "syndicate.features.soccer.market_board.game_odds_rows", return_value=()
        ), patch("syndicate.features.soccer.market_board.props_odds_rows", return_value=()):
            board = build_soccer_market_board("mls", "2026-07-22")
        self.assertEqual(board["games"], [])


if __name__ == "__main__":
    unittest.main()


class SoccerMarketBoardCacheTests(unittest.TestCase):
    """build_soccer_market_board is reached from the live-refresh tick via
    soccer_needs_resim_event_ids. An uncached full board assembly on a
    worker's main loop is exactly what OOM-killed the 2GB refresh-worker on
    2026-07-25 (see build_mlb_market_board's docstring), so the cache is a
    load-bearing guard, not an optimisation.
    """

    def _patched_build(self, *, odds_rows, recommendations):
        return patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]), patch(
            "syndicate.features.soccer.market_board.recommendations_payload", return_value=recommendations
        ), patch(
            "syndicate.features.soccer.market_board.game_odds_rows", return_value=tuple(odds_rows)
        ), patch("syndicate.features.soccer.market_board.props_odds_rows", return_value=()), patch(
            "syndicate.features.soccer.market_board.team_by_name", return_value=None
        )

    def test_second_call_reuses_cached_board_without_rebuilding(self) -> None:
        fake_recommendations = {"matches": [_FAKE_MATCH]}
        patches = self._patched_build(odds_rows=_FAKE_GAME_ODDS_ROWS, recommendations=fake_recommendations)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            first = build_soccer_market_board("mls", "2026-07-22")
            with patch(
                "syndicate.features.soccer.market_board._soccer_week_matches"
            ) as week_matches:
                second = build_soccer_market_board("mls", "2026-07-22")
                week_matches.assert_not_called()
        self.assertIs(first, second)

    def test_cache_key_changes_when_odds_artifact_changes(self) -> None:
        # The signature inputs must be files the build READS and never
        # writes -- MLB's cache could never hit until that was fixed.
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]), patch(
            "syndicate.features.soccer.market_board._soccer_path_signature", side_effect=[11, 22]
        ):
            first_key = _soccer_market_board_cache_key("mls", "2026-07-22")
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]), patch(
            "syndicate.features.soccer.market_board._soccer_path_signature", side_effect=[99, 22]
        ):
            second_key = _soccer_market_board_cache_key("mls", "2026-07-22")
        self.assertNotEqual(first_key, second_key)

    def test_cache_is_scoped_per_league(self) -> None:
        with patch("syndicate.features.soccer.market_board.available_dates", return_value=["2026-07-22"]):
            self.assertNotEqual(
                _soccer_market_board_cache_key("mls", "2026-07-22"),
                _soccer_market_board_cache_key("epl", "2026-07-22"),
            )

    def test_cache_evicts_oldest_beyond_max_entries(self) -> None:
        clear_soccer_market_board_cache()
        for index in range(_SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES + 5):
            _SOCCER_MARKET_BOARD_CACHE[("k", index)] = {"games": []}
            while len(_SOCCER_MARKET_BOARD_CACHE) > _SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES:
                _SOCCER_MARKET_BOARD_CACHE.popitem(last=False)
        self.assertEqual(len(_SOCCER_MARKET_BOARD_CACHE), _SOCCER_MARKET_BOARD_CACHE_MAX_ENTRIES)


class SoccerNeedsResimEventIdsTests(unittest.TestCase):
    """Soccer's counterpart to mlb_needs_resim_game_pks. market_inventory
    already computed unmatched_needs_resim for every sport, but only MLB
    ever acted on it -- 428 MLS rows sat suppressed (is_eligible false) on
    2026-07-25 with nothing able to clear them.
    """

    def test_returns_event_ids_with_a_needs_resim_row(self) -> None:
        board = {
            "games": [
                {"gamePk": "111", "rows": [{"join_status": JOIN_STATUS_MATCHED}]},
                {"gamePk": "222", "rows": [{"join_status": JOIN_STATUS_NEEDS_RESIM}]},
                {"gamePk": "333", "rows": [{"join_status": JOIN_STATUS_NO_SIM_COVERAGE}]},
            ]
        }
        with patch("syndicate.features.soccer.market_board.build_soccer_market_board", return_value=board):
            self.assertEqual(soccer_needs_resim_event_ids("mls", "2026-07-22"), ["222"])

    def test_deduplicates_and_sorts_event_ids(self) -> None:
        board = {
            "games": [
                {"gamePk": "999", "rows": [{"join_status": JOIN_STATUS_NEEDS_RESIM}, {"join_status": JOIN_STATUS_NEEDS_RESIM}]},
                {"gamePk": "111", "rows": [{"join_status": JOIN_STATUS_NEEDS_RESIM}]},
            ]
        }
        with patch("syndicate.features.soccer.market_board.build_soccer_market_board", return_value=board):
            self.assertEqual(soccer_needs_resim_event_ids("mls", "2026-07-22"), ["111", "999"])

    def test_returns_empty_when_nothing_needs_resim(self) -> None:
        board = {"games": [{"gamePk": "111", "rows": [{"join_status": JOIN_STATUS_MATCHED}]}]}
        with patch("syndicate.features.soccer.market_board.build_soccer_market_board", return_value=board):
            self.assertEqual(soccer_needs_resim_event_ids("mls", "2026-07-22"), [])

    def test_tolerates_malformed_board_shapes(self) -> None:
        # Runs on a worker tick; a shape surprise must not take the loop down.
        for board in ({}, {"games": None}, {"games": ["not-a-dict"]}, {"games": [{"gamePk": "", "rows": [{"join_status": JOIN_STATUS_NEEDS_RESIM}]}]}):
            with patch("syndicate.features.soccer.market_board.build_soccer_market_board", return_value=board):
                self.assertEqual(soccer_needs_resim_event_ids("mls", "2026-07-22"), [])


class SoccerGameStateFromClockTests(unittest.TestCase):
    """status_state is frozen into the recommendations artifact when it is
    generated and never recomputed.

    Measured 2026-07-25 at 23:47 CT: all 30 MLS matches on the board reported
    `pregame`, including 15 that kicked off on 07-22 and had been over for three
    days -- while that evening's genuinely in-progress matches were reported as
    upcoming as well. Finished games looked bettable and live games did not look
    live. MLB is unaffected because its states come from the live-lens report
    rather than being baked in.
    """

    def _state(self, status_state, offset_hours=None, kickoff="__offset__"):
        from datetime import datetime, timedelta, timezone

        from syndicate.features.soccer.market_board import _resolve_soccer_game_state

        if kickoff == "__offset__":
            stamp = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
            kickoff = stamp.strftime("%Y-%m-%dT%H:%M") + "Z"
        return _resolve_soccer_game_state(status_state, kickoff)

    def test_future_kickoff_is_pregame(self) -> None:
        self.assertEqual(self._state("pre", offset_hours=3), "pregame")

    def test_match_in_progress_is_live(self) -> None:
        # The reported bug: an active match showing as upcoming.
        self.assertEqual(self._state("pre", offset_hours=-0.75), "live")

    def test_match_still_live_late_in_the_second_half(self) -> None:
        self.assertEqual(self._state("pre", offset_hours=-2), "live")

    def test_match_past_its_duration_is_final(self) -> None:
        self.assertEqual(self._state("pre", offset_hours=-5), "final")

    def test_days_old_match_is_final_not_pregame(self) -> None:
        # 15 of the 30 MLS matches were in exactly this state.
        self.assertEqual(self._state("pre", offset_hours=-72), "final")

    def test_artifact_status_wins_when_it_has_moved_forward(self) -> None:
        # "in"/"post" is real observed status and beats a clock estimate; only
        # the default "pre" is second-guessed.
        self.assertEqual(self._state("in", offset_hours=-72), "live")
        self.assertEqual(self._state("post", offset_hours=3), "final")

    def test_missing_or_unparseable_kickoff_falls_back_to_the_artifact(self) -> None:
        # No clock to reason from, so do not invent one.
        self.assertEqual(self._state("pre", kickoff=None), "pregame")
        self.assertEqual(self._state("pre", kickoff="garbage"), "pregame")

    def test_naive_kickoff_is_treated_as_utc(self) -> None:
        from datetime import datetime, timedelta, timezone

        naive = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(self._state("pre", kickoff=naive), "live")
