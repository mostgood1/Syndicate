from __future__ import annotations

import unittest

from scripts.fetch_soccer_oddsapi_props_local import LEAGUE_SPORT_KEYS
from scripts.fetch_soccer_oddsapi_props_local import parse_event_to_rows


def _event_fixture() -> dict:
    return {
        "id": "evt123",
        "home_team": "Arsenal",
        "away_team": "Liverpool",
        "commence_time": "2026-08-15T14:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_goal_scorer_anytime",
                        "outcomes": [
                            {"name": "Yes", "description": "Bukayo Saka", "price": 150},
                            {"name": "Yes", "description": "Mohamed Salah", "price": 120},
                        ],
                    },
                    {
                        "key": "player_shots_on_target",
                        "outcomes": [
                            {"name": "Over", "description": "Bukayo Saka", "point": 1.5, "price": -110},
                            {"name": "Under", "description": "Bukayo Saka", "point": 1.5, "price": -120},
                        ],
                    },
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": -105},
                        ],
                    },
                ],
            }
        ],
    }


class FetchSoccerOddsApiPropsTests(unittest.TestCase):
    def test_league_sport_keys_cover_engine_leagues(self) -> None:
        for league in ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "mls"):
            self.assertIn(league, LEAGUE_SPORT_KEYS)

    def test_parse_event_to_rows_extracts_props(self) -> None:
        rows = parse_event_to_rows(_event_fixture(), league="epl")

        self.assertEqual(len(rows), 3)
        by_market = {}
        for row in rows:
            by_market.setdefault(row["market"], []).append(row)

        scorers = by_market["Anytime Goalscorer"]
        self.assertEqual({row["player"] for row in scorers}, {"Bukayo Saka", "Mohamed Salah"})
        saka_scorer = next(row for row in scorers if row["player"] == "Bukayo Saka")
        self.assertEqual(saka_scorer["over_price"], 150)
        self.assertEqual(saka_scorer["event"], "Liverpool @ Arsenal")
        self.assertEqual(saka_scorer["book"], "draftkings")

        sot_rows = by_market["Shots On Target"]
        self.assertEqual(len(sot_rows), 1)
        self.assertEqual(sot_rows[0]["line"], 1.5)
        self.assertEqual(sot_rows[0]["over_price"], -110)
        self.assertEqual(sot_rows[0]["under_price"], -120)

        # Non-player market keys are ignored.
        self.assertNotIn("h2h", by_market)


if __name__ == "__main__":
    unittest.main()
