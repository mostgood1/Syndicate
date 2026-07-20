from __future__ import annotations

import unittest

from syndicate.features.soccer.ingestion.match_history import LEAGUE_HISTORY_CODES
from syndicate.features.soccer.ingestion.match_history import normalize_match_history
from syndicate.features.soccer.ingestion.match_history import season_code
from syndicate.features.soccer.ingestion.match_history import to_benchmark_match_records
from syndicate.features.soccer.ingestion.player_history import normalize_asa_players
from syndicate.features.soccer.ingestion.player_history import normalize_understat_players
from syndicate.features.soccer.ingestion.player_history import normalize_understat_team_history

_MATCH_CSV = """Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,HTHG,HTAG,HS,AS,HST,AST,HC,AC,HF,AF,HY,AY,HR,AR,B365H,B365D,B365A,AvgH,AvgD,AvgA
E0,15/08/2025,Arsenal,Liverpool,2,1,1,1,15,11,6,4,7,4,10,12,1,2,0,0,2.1,3.4,3.6,2.05,3.45,3.55
E0,16/08/2025,Everton,Fulham,0,0,0,0,9,8,2,3,5,6,11,9,2,1,0,0,2.5,3.2,2.9,2.45,3.25,2.95
"""


class SoccerMatchHistoryTests(unittest.TestCase):
    def test_season_code(self) -> None:
        self.assertEqual(season_code(2025), "2526")
        self.assertEqual(season_code(2023), "2324")

    def test_league_codes_cover_big_five(self) -> None:
        for league in ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1"):
            self.assertIn(league, LEAGUE_HISTORY_CODES)

    def test_normalize_match_history(self) -> None:
        rows = normalize_match_history(_MATCH_CSV, league="epl", season=2025)

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["home_team"], "Arsenal")
        self.assertEqual(first["home_goals"], 2)
        self.assertEqual(first["ht_home_goals"], 1)
        self.assertEqual(first["home_shots"], 15)
        self.assertEqual(first["home_shots_on_target"], 6)
        self.assertEqual(first["home_corners"], 7)
        self.assertAlmostEqual(first["odds_home"], 2.05)

    def test_to_benchmark_match_records_splits_halves(self) -> None:
        rows = normalize_match_history(_MATCH_CSV, league="epl", season=2025)
        records = to_benchmark_match_records(rows)

        self.assertEqual(len(records), 2)
        record = records[0]
        self.assertEqual(record.home_goals, 2)
        self.assertEqual(record.half_home_goals, (1, 1))
        self.assertEqual(record.half_away_goals, (1, 0))
        self.assertEqual(record.shots, 26)
        self.assertEqual(record.shots_on_target, 10)
        self.assertEqual(record.corners, 11)
        self.assertEqual(record.metadata["league"], "epl")


class SoccerPlayerHistoryTests(unittest.TestCase):
    def test_normalize_understat_players(self) -> None:
        raw = [
            {
                "id": "8260",
                "player_name": "Erling Haaland",
                "games": "35",
                "time": "2979",
                "goals": "27",
                "xG": "28.795",
                "assists": "8",
                "xA": "5.507",
                "shots": "125",
                "key_passes": "25",
                "position": "F S",
                "team_title": "Manchester City",
            },
            {"id": "1", "player_name": "Bench Player", "games": "3", "time": "90", "shots": "1", "position": "M"},
        ]
        rows = normalize_understat_players(raw, league="epl", season=2025)

        self.assertEqual(len(rows), 1)  # bench player under minimum minutes
        row = rows[0]
        self.assertEqual(row["player_name"], "Erling Haaland")
        self.assertAlmostEqual(row["shots_per90"], 125 / 2979 * 90, places=3)
        self.assertAlmostEqual(row["xg_per90"], 28.795 / 2979 * 90, places=3)
        self.assertAlmostEqual(row["expected_minutes_share"], 2979 / (35 * 90), places=3)
        self.assertFalse(row["is_goalkeeper"])

    def test_normalize_understat_team_history(self) -> None:
        league_data = {
            "teams": {
                "88": {
                    "id": "88",
                    "title": "Manchester City",
                    "history": [
                        {
                            "h_a": "h",
                            "xG": 2.4,
                            "xGA": 0.7,
                            "npxG": 2.1,
                            "npxGA": 0.7,
                            "ppda": {"att": 220, "def": 25},
                            "ppda_allowed": {"att": 300, "def": 20},
                            "deep": 12,
                            "deep_allowed": 3,
                            "scored": 3,
                            "missed": 0,
                            "xpts": 2.7,
                            "pts": 3,
                            "result": "w",
                            "date": "2025-08-16 15:00:00",
                        }
                    ],
                }
            }
        }
        rows = normalize_understat_team_history(league_data, league="epl", season=2025)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["team"], "Manchester City")
        self.assertAlmostEqual(row["ppda"], 8.8)
        self.assertAlmostEqual(row["xg_for"], 2.4)
        self.assertEqual(row["goals_for"], 3)
        self.assertEqual(row["result"], "w")

    def test_normalize_asa_players(self) -> None:
        raw = [
            {
                "player_id": "abc",
                "player_name": "MLS Striker",
                "position": "FW",
                "team_id": ["team1"],
                "minutes_played": 1800,
                "shots": 60,
                "xgoals": 9.5,
                "xassists": 3.1,
                "goals": 10,
                "primary_assists": 4,
                "key_passes": 30,
            }
        ]
        rows = normalize_asa_players(raw, season=2026)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["league"], "mls")
        self.assertAlmostEqual(row["shots_per90"], 3.0)
        self.assertAlmostEqual(row["xg_per90"], 9.5 / 1800 * 90, places=3)
        self.assertFalse(row["is_goalkeeper"])


if __name__ == "__main__":
    unittest.main()
