from __future__ import annotations

import unittest

from syndicate.features.mlb.cards import _tracked_game_lines_for_source_card
from syndicate.features.mlb.cards import _tracked_game_lines_index


class TrackedGameLinesDoubleheaderTests(unittest.TestCase):
    """#117 follow-up. _tracked_game_lines_index used to collapse a
    doubleheader's two games (same team pair, same day) into ONE indexed
    entry per (away, home) key -- whichever row scored higher on market
    completeness silently won, and the other game's real odds were
    discarded. Every card for either game then looked up the same single
    entry, so one game always displayed the other's market data. Confirmed
    live 2026-07-28 (CLE @ CIN, gamePk 824490 game 1 12:40 PM / gamePk 824489
    game 2 6:10 PM). Fix disambiguates by matching each candidate row's own
    commence_time against the specific game's known start time (gameDate).
    """

    def _game_lines_doc(self) -> dict:
        return {
            "date": "2026-07-28",
            "retrieved_at": "2026-07-28T20:00:00Z",
            "games": [
                {
                    "away_team": "Cleveland Guardians",
                    "home_team": "Cincinnati Reds",
                    "commence_time": "2026-07-28T17:42:00Z",
                    "markets": {"h2h": {"home_odds": -145, "away_odds": 125}},
                },
                {
                    "away_team": "Cleveland Guardians",
                    "home_team": "Cincinnati Reds",
                    "commence_time": "2026-07-28T23:10:00Z",
                    "markets": {"h2h": {"home_odds": 110, "away_odds": -130}},
                },
            ],
        }

    def _game(self, *, game_pk: int, game_date: str) -> dict:
        return {
            "gamePk": game_pk,
            "gameDate": game_date,
            "away": {"abbr": "CLE", "name": "Cleveland Guardians"},
            "home": {"abbr": "CIN", "name": "Cincinnati Reds"},
        }

    def test_each_doubleheader_game_gets_its_own_markets(self) -> None:
        index = _tracked_game_lines_index(self._game_lines_doc())

        game_one = self._game(game_pk=824490, game_date="2026-07-28T17:40:00Z")
        game_two = self._game(game_pk=824489, game_date="2026-07-28T23:10:00Z")

        lines_one = _tracked_game_lines_for_source_card(game_one, index)
        lines_two = _tracked_game_lines_for_source_card(game_two, index)

        self.assertEqual(lines_one["h2h"]["home_odds"], -145)
        self.assertEqual(lines_two["h2h"]["home_odds"], 110)
        self.assertNotEqual(lines_one["h2h"], lines_two["h2h"])
        # Internal disambiguation fields must not leak into the card payload.
        self.assertNotIn("_commence_time", lines_one)
        self.assertNotIn("_market_score", lines_one)

    def test_single_game_non_doubleheader_is_unaffected(self) -> None:
        doc = {
            "games": [
                {
                    "away_team": "Los Angeles Dodgers",
                    "home_team": "San Francisco Giants",
                    "commence_time": "2026-07-28T20:00:00Z",
                    "markets": {"h2h": {"home_odds": -110, "away_odds": -110}},
                }
            ]
        }
        index = _tracked_game_lines_index(doc)
        game = {
            "gamePk": 1,
            "gameDate": "2026-07-28T20:00:00Z",
            "away": {"abbr": "LAD", "name": "Los Angeles Dodgers"},
            "home": {"abbr": "SFG", "name": "San Francisco Giants"},
        }
        lines = _tracked_game_lines_for_source_card(game, index)
        self.assertEqual(lines["h2h"]["home_odds"], -110)

    def test_falls_back_to_market_score_when_this_games_start_time_is_unparseable(self) -> None:
        index = _tracked_game_lines_index(self._game_lines_doc())
        game = self._game(game_pk=824490, game_date="not-a-timestamp")
        lines = _tracked_game_lines_for_source_card(game, index)
        # No crash, and it returns SOME real entry (the higher-scoring one,
        # matching pre-fix behavior) rather than nothing at all.
        self.assertIn("h2h", lines)

    def test_no_match_for_unknown_team_pair_returns_empty(self) -> None:
        index = _tracked_game_lines_index(self._game_lines_doc())
        game = {
            "gamePk": 999,
            "gameDate": "2026-07-28T20:00:00Z",
            "away": {"abbr": "NYY", "name": "New York Yankees"},
            "home": {"abbr": "BOS", "name": "Boston Red Sox"},
        }
        self.assertEqual(_tracked_game_lines_for_source_card(game, index), {})


if __name__ == "__main__":
    unittest.main()
