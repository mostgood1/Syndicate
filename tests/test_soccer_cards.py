from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import cards


class MatchToGameTests(unittest.TestCase):
    def test_simulated_match_renders_real_metrics(self) -> None:
        match = {
            "event_id": "123",
            "match_id": "123",
            "status_state": "pre",
            "kickoff": "2026-08-21T19:00Z",
            "simulations": 200,
            "matchup": {"home_team": "Arsenal", "away_team": "Chelsea"},
            "win_probability": {"home": 0.55, "draw": 0.25, "away": 0.20},
            "team_projection": {"home_mean": 1.8, "away_mean": 1.1, "total_mean": 2.9, "margin_mean": 0.7},
            "total_distribution": {"both_teams_scored_probability": 0.52, "over_2_5_probability": 0.48},
            "volume_projection": {
                "home_shots": 14.0, "away_shots": 10.0,
                "home_shots_on_target": 5.0, "away_shots_on_target": 3.5,
                "home_corners": 6.0, "away_corners": 4.0,
            },
            "top_props": [],
        }
        with patch.object(cards, "team_by_name", return_value=None):
            game = cards._match_to_game(match, league="epl", week=1, season=2026)
        self.assertEqual(game["home"]["name"], "Arsenal")
        self.assertEqual(game["away"]["name"], "Chelsea")
        metrics = {m["label"]: m["value"] for m in game["metrics"]}
        self.assertEqual(metrics["Home win"], "55.0%")
        self.assertEqual(metrics["Draw"], "25.0%")
        self.assertEqual(metrics["Away win"], "20.0%")
        self.assertIn("/soccer/epl/game/123?week=1&season=2026", game["href"])
        self.assertEqual(game["panels"][0]["eyebrow"], "Match projection")
        # #162: stamped so downstream candidate/chip builders can show the
        # specific league ("EPL") instead of the generic "Soccer" label.
        self.assertEqual(game["league"], "epl")
        self.assertEqual(game["league_display"], "EPL")

    def test_unsimulated_fixture_shows_placeholder_card(self) -> None:
        fixture = {
            "event_id": "999",
            "home_team": "Newcastle United",
            "away_team": "Fulham",
            "status_state": "pre",
            "date": "2026-08-22T15:00Z",
        }
        with patch.object(cards, "team_by_name", return_value=None):
            game = cards._unsimulated_game(fixture, league="epl", week=1, season=2026)
        self.assertEqual(game["home"]["name"], "Newcastle United")
        self.assertEqual(game["metrics"][0]["value"], "-")
        self.assertEqual(game["panels"][0]["eyebrow"], "Not yet simulated")
        self.assertIn("has not been simulated yet", game["summary"])
        self.assertEqual(game["league"], "epl")
        self.assertEqual(game["league_display"], "EPL")

    def test_team_roster_href_uses_directory_id_when_matched(self) -> None:
        with patch.object(cards, "team_by_name", return_value={"team_id": "359", "abbreviation": "ARS"}):
            self.assertEqual(cards._team_roster_href("Arsenal", "epl"), "/soccer/epl/team/359/roster")

    def test_team_roster_href_is_none_when_unmatched(self) -> None:
        with patch.object(cards, "team_by_name", return_value=None):
            self.assertIsNone(cards._team_roster_href("Unknown FC", "epl"))


class MarketDataForMatchTests(unittest.TestCase):
    # #150. _market_data_for_match originally only captured p_home_win/
    # p_away_win/total/home_spread -- enough for this module's own sim-vs-
    # line display, but not enough for home.py's _game_bet_candidates_from_
    # game, which reads this same "betting" dict to build the cross-sport
    # board's "game" candidates: it needs real price/edge (home_ml/away_ml/
    # *_ev) to show anything but blank odds, and specifically gates Spread-
    # candidate creation on home_puck_line/away_puck_line (not home_spread).
    _ROWS = (
        {"home": "Arsenal", "away": "Chelsea", "market": "ML", "side": "home", "line": "", "price": "-150", "market_probability": "0.62", "ev": "0.04"},
        {"home": "Arsenal", "away": "Chelsea", "market": "ML", "side": "away", "line": "", "price": "400", "market_probability": "0.20", "ev": "-0.02"},
        {"home": "Arsenal", "away": "Chelsea", "market": "TOTAL", "side": "over", "line": "2.5", "price": "-110", "market_probability": "0.55", "ev": "0.05"},
        {"home": "Arsenal", "away": "Chelsea", "market": "TOTAL", "side": "under", "line": "2.5", "price": "-110", "market_probability": "0.45", "ev": "-0.05"},
        {"home": "Arsenal", "away": "Chelsea", "market": "SPREAD", "side": "home", "line": "-0.5", "price": "-120", "market_probability": "0.58", "ev": "0.03"},
        {"home": "Arsenal", "away": "Chelsea", "market": "SPREAD", "side": "away", "line": "0.5", "price": "-105", "market_probability": "0.42", "ev": "-0.01"},
    )

    def test_ml_total_spread_rows_populate_price_and_ev_fields(self) -> None:
        with patch.object(cards, "picks_rows", return_value=self._ROWS):
            betting = cards._market_data_for_match("epl", "2026-08-21", "Arsenal", "Chelsea")
        self.assertEqual(betting["p_home_win"], 0.62)
        self.assertEqual(betting["p_away_win"], 0.20)
        self.assertEqual(betting["home_ml"], -150.0)
        self.assertEqual(betting["away_ml"], 400.0)
        self.assertEqual(betting["home_ml_ev"], 0.04)
        self.assertEqual(betting["away_ml_ev"], -0.02)
        self.assertEqual(betting["total"], 2.5)
        self.assertEqual(betting["odds"], -110.0)
        self.assertEqual(betting["p_total_over"], 0.55)
        self.assertEqual(betting["p_total_under"], 0.45)
        self.assertEqual(betting["over_ev"], 0.05)
        self.assertEqual(betting["under_ev"], -0.05)
        # home_spread is kept for game_board_contract's own sim-vs-line
        # comparison; home_puck_line/away_puck_line are the new keys
        # _game_bet_candidates_from_game actually gates Spread creation on.
        self.assertEqual(betting["home_spread"], -0.5)
        self.assertEqual(betting["home_puck_line"], -0.5)
        self.assertEqual(betting["away_puck_line"], 0.5)
        self.assertEqual(betting["p_home_cover"], 0.58)
        self.assertEqual(betting["p_away_cover"], 0.42)
        self.assertEqual(betting["home_spread_ev"], 0.03)
        self.assertEqual(betting["away_spread_ev"], -0.01)

    def test_no_matching_rows_returns_empty_dict(self) -> None:
        with patch.object(cards, "picks_rows", return_value=self._ROWS):
            betting = cards._market_data_for_match("epl", "2026-08-21", "Manchester City", "Everton")
        self.assertEqual(betting, {})

    def test_closest_to_pickem_spread_line_wins_on_both_sides(self) -> None:
        rows = self._ROWS + (
            {"home": "Arsenal", "away": "Chelsea", "market": "SPREAD", "side": "home", "line": "-0.25", "price": "-115", "market_probability": "0.53", "ev": "0.01"},
            {"home": "Arsenal", "away": "Chelsea", "market": "SPREAD", "side": "away", "line": "0.25", "price": "-110", "market_probability": "0.47", "ev": "0.0"},
        )
        with patch.object(cards, "picks_rows", return_value=rows):
            betting = cards._market_data_for_match("epl", "2026-08-21", "Arsenal", "Chelsea")
        self.assertEqual(betting["home_puck_line"], -0.25)
        self.assertEqual(betting["away_puck_line"], 0.25)


class WeekGamesMergeTests(unittest.TestCase):
    def test_merges_real_schedule_with_simulated_output_by_event_id(self) -> None:
        fixtures = [
            {"event_id": "1", "home_team": "Arsenal", "away_team": "Chelsea", "date": "2026-08-21T19:00Z", "status_state": "pre"},
            {"event_id": "2", "home_team": "Everton", "away_team": "Fulham", "date": "2026-08-22T15:00Z", "status_state": "pre"},
        ]
        simulated_payload = {
            "matches": [
                {
                    "event_id": "1",
                    "match_id": "1",
                    "status_state": "pre",
                    "matchup": {"home_team": "Arsenal", "away_team": "Chelsea"},
                    "win_probability": {"home": 0.5, "draw": 0.3, "away": 0.2},
                    "team_projection": {"home_mean": 1.5, "away_mean": 1.0, "total_mean": 2.5, "margin_mean": 0.5},
                    "total_distribution": {},
                    "volume_projection": {},
                    "top_props": [],
                }
            ]
        }
        with patch.object(cards, "week_matches", return_value=fixtures), \
             patch.object(cards, "week_date_list", return_value=["2026-08-21", "2026-08-22"]), \
             patch.object(cards, "recommendations_payload", side_effect=lambda league, date: simulated_payload if date == "2026-08-21" else {}), \
             patch.object(cards, "team_by_name", return_value=None):
            games = cards.week_games("epl", 1, 2026)
        self.assertEqual(len(games), 2)
        simulated_game = next(g for g in games if g["gamePk"] == "1")
        unsimulated_game = next(g for g in games if g["gamePk"] == "2")
        self.assertEqual(simulated_game["panels"][0]["eyebrow"], "Match projection")
        self.assertEqual(unsimulated_game["panels"][0]["eyebrow"], "Not yet simulated")

    def test_no_fixtures_returns_empty_list(self) -> None:
        with patch.object(cards, "week_matches", return_value=[]):
            self.assertEqual(cards.week_games("epl", 1, 2026), [])


if __name__ == "__main__":
    unittest.main()


class AbbreviationFallbackTests(unittest.TestCase):
    """`#355`. A directory miss used to emit an all-caps initialism that no
    reader and no join could tell from a real tri-code -- and soccer tri-codes
    already collide across leagues, which `game_chip_scoreboard._side_name`
    documents. `_abbr('Leeds', 'mls')` returned 'LEE'; 'LEE' appears in exactly
    one file in this repo, `epl_team_branding.csv`, as Leeds United.
    """

    def test_directory_hit_still_returns_the_real_tricode(self) -> None:
        self.assertEqual(cards._abbr("CF Montréal", "mls"), "MTL")
        self.assertEqual(cards._abbr("Leeds United", "epl"), "LEE")

    def test_directory_miss_does_not_emit_a_tricode_shaped_label(self) -> None:
        label = cards._abbr("Leeds", "mls")
        self.assertNotEqual(label, "LEE")
        self.assertFalse(
            label.isupper() and len(label) <= 3,
            f"{label!r} is shaped like a directory tri-code but was invented from the name",
        )

    def test_empty_team_is_still_tbd(self) -> None:
        self.assertEqual(cards._abbr("", "mls"), "TBD")
