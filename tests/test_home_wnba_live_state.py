"""A live WNBA chip must carry its quarter and clock, and never a projection.

Every fixture row below is copied from production on 2026-08-26 via
`/api/ops/wnba/status-trace?date=2026-08-26`, section `local_live_state_payload`
-- which is exactly what `build_live_state_payload` hands
`_apply_wnba_live_scores`:

    {"away_pts": 65.0, "home_pts": 38.0, "in_progress": true,
     "period": 3, "clock": "5:23", "status": "5:23 - 3rd"}

TWO DEFECTS, ONE FUNCTION, BOTH USER-REPORTED.

1. `live_state` was built from five keys and dropped `period`/`clock`.
   `_live_status_token`'s basketball branch reads exactly those two, so the chip
   rendered the bare string `LIVE` while every MLB chip beside it read `TOP 5`.

2. `#160`'s projection guard gates on whether the GAME is underway, not on
   whether the NUMBER is an observation. A tipped-off game whose ESPN boxscore
   has not matched yet is `in_progress: true` with `away_pts` still holding the
   SmartSim projection -- reported as `GSV 85.43 / CON 68.94` on the strip.
"""
from __future__ import annotations

import unittest
from unittest import mock

from syndicate.blueprints import home
from syndicate.features.shared.game_chip_scoreboard import build_game_chip


LIVE_ROW = {
    "away": "GSV",
    "home": "CON",
    "away_pts": 65.0,
    "home_pts": 38.0,
    "in_progress": True,
    "final": False,
    "period": 3,
    "clock": "5:23",
    "status": "5:23 - 3rd",
}

# Same game, before the ESPN boxscore row matched: cards.py falls back to the
# SmartSim projection, and the fractional part is what gives it away.
PROJECTION_ROW = dict(LIVE_ROW, away_pts=85.43, home_pts=68.94)

PREGAME_ROW = {
    "away": "TOR",
    "home": "SEA",
    "away_pts": 0.0,
    "home_pts": 0.0,
    "in_progress": False,
    "final": False,
    "period": None,
    "clock": "0.0",
    "status": "8/26 - 10:00 PM EDT",
}


def _game(away="GSV", home_="CON"):
    return {
        "event_id": "401857176",
        "away_tri": away,
        "home_tri": home_,
        "away": {"abbr": away, "name": away},
        "home": {"abbr": home_, "name": home_},
        "status": {},
    }


def _apply(row, game=None):
    payload = {"games": [row]}
    with mock.patch("syndicate.features.wnba.cards.build_live_state_payload", return_value=payload):
        return home._apply_wnba_live_scores([game or _game(row["away"], row["home"])], "2026-08-26")


class LiveWnbaChipCarriesTheClock(unittest.TestCase):
    def test_period_and_clock_reach_live_state(self):
        state = _apply(LIVE_ROW)[0]["live_state"]
        self.assertEqual(state["period"], 3)
        self.assertEqual(state["clock"], "5:23")

    def test_the_chip_renders_quarter_and_clock(self):
        # The whole point: `Q3 5:23`, not `LIVE`.
        chip = build_game_chip("wnba", _apply(LIVE_ROW)[0])
        self.assertEqual(chip["status_token"], "Q3 5:23")
        self.assertEqual(chip["state"], "live")

    def test_a_pregame_game_still_reports_no_period(self):
        state = _apply(PREGAME_ROW, _game("TOR", "SEA"))[0]["live_state"]
        self.assertIsNone(state["period"])
        self.assertFalse(state["in_progress"])


class AProjectionIsNotAScore(unittest.TestCase):
    def test_an_integral_live_score_is_kept(self):
        game = _apply(LIVE_ROW)[0]
        self.assertEqual(game["away"]["score"], 65)
        self.assertEqual(game["home"]["score"], 38)

    def test_a_fractional_live_score_is_refused(self):
        # `in_progress` is True here, so `#160`'s gate passes and only the
        # integrality check can stop it.
        game = _apply(PROJECTION_ROW)[0]
        self.assertNotIn("score", game["away"])
        self.assertNotIn("score", game["home"])

    def test_a_refused_score_does_not_reach_the_chip(self):
        chip = build_game_chip("wnba", _apply(PROJECTION_ROW)[0])
        self.assertIsNone(chip["away"]["score"])
        self.assertIsNone(chip["home"]["score"])

    def test_a_fractional_value_is_refused_not_rounded(self):
        # Rounding would turn a fabricated 85.43 into a plausible 85 and destroy
        # the only evidence that it was never an observation.
        game = _apply(PROJECTION_ROW)[0]
        self.assertNotEqual(game["away"].get("score"), 85)

    def test_pregame_scores_are_still_suppressed(self):
        # `#160`'s original case, which must keep working.
        game = _apply(PREGAME_ROW, _game("TOR", "SEA"))[0]
        self.assertNotIn("score", game["away"])
        self.assertNotIn("score", game["home"])


if __name__ == "__main__":
    unittest.main()
