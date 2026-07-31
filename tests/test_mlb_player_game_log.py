from __future__ import annotations

import csv
import gzip
import json
import os
import tempfile
import unittest

from syndicate.features.mlb.player_game_log import bootstrap_mlb_player_game_log
from syndicate.features.mlb.player_game_log import extract_game_log_rows


FINAL_FEED = {
    "gameData": {
        "status": {"abstractGameState": "Final"},
        "teams": {
            "away": {"abbreviation": "MIA"},
            "home": {"abbreviation": "NYM"},
        },
    },
    "liveData": {
        "boxscore": {
            "teams": {
                "away": {
                    "players": {
                        "ID691587": {
                            "person": {"id": 691587, "fullName": "Eury Pérez"},
                            "stats": {"pitching": {
                                "gamesStarted": 1, "inningsPitched": "6.0", "outs": 18,
                                "numberOfPitches": 92, "strikeOuts": 8, "baseOnBalls": 1,
                                "earnedRuns": 2, "hits": 4, "runs": 2, "homeRuns": 1,
                            }},
                        },
                        "ID700001": {
                            "person": {"id": 700001, "fullName": "Reliever Guy"},
                            "stats": {"pitching": {
                                "gamesStarted": 0, "inningsPitched": "1.0", "outs": 3,
                                "numberOfPitches": 12, "strikeOuts": 1, "baseOnBalls": 0,
                                "earnedRuns": 0, "hits": 0, "runs": 0, "homeRuns": 0,
                            }},
                        },
                    }
                },
                "home": {
                    "players": {
                        "ID222": {
                            "person": {"id": 222, "fullName": "Test Hitter"},
                            "stats": {"batting": {
                                "atBats": 4, "hits": 2, "runs": 1, "rbi": 3, "homeRuns": 1,
                                "baseOnBalls": 0, "strikeOuts": 1, "totalBases": 6,
                            }},
                        },
                        "ID223": {
                            # Pitcher-with-no-batting-appearance -- must not
                            # produce a spurious 0-AB batter row.
                            "person": {"id": 223, "fullName": "Bench Guy"},
                            "stats": {"batting": {"atBats": 0, "plateAppearances": 0}},
                        },
                    }
                },
            }
        }
    },
}

NOT_FINAL_FEED = {
    "gameData": {"status": {"abstractGameState": "Live"}, "teams": {"away": {}, "home": {}}},
    "liveData": {"boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {}}}}},
}


class ExtractGameLogRowsTests(unittest.TestCase):
    def test_final_game_extracts_starter_reliever_and_batter(self) -> None:
        pitcher_rows, batter_rows = extract_game_log_rows(FINAL_FEED, "2026-06-24", 823850)

        self.assertEqual(len(pitcher_rows), 2)
        starter = next(r for r in pitcher_rows if r["player_id"] == 691587)
        self.assertEqual(starter["player_name"], "Eury Pérez")
        self.assertEqual(starter["team"], "MIA")
        self.assertEqual(starter["opponent"], "NYM")
        self.assertEqual(starter["is_starter"], 1)
        self.assertEqual(starter["k"], 8)
        self.assertEqual(starter["ip"], "6.0")

        reliever = next(r for r in pitcher_rows if r["player_id"] == 700001)
        self.assertEqual(reliever["is_starter"], 0)

        self.assertEqual(len(batter_rows), 1)
        self.assertEqual(batter_rows[0]["player_id"], 222)
        self.assertEqual(batter_rows[0]["team"], "NYM")
        self.assertEqual(batter_rows[0]["opponent"], "MIA")

    def test_non_final_game_yields_nothing(self) -> None:
        pitcher_rows, batter_rows = extract_game_log_rows(NOT_FINAL_FEED, "2026-06-24", 1)
        self.assertEqual(pitcher_rows, [])
        self.assertEqual(batter_rows, [])


class BootstrapMlbPlayerGameLogTests(unittest.TestCase):
    def _write_feed(self, data_root: str, date_str: str, game_pk: int, feed: dict) -> None:
        game_dir = os.path.join(data_root, "raw", "statsapi", "feed_live", date_str[:4], date_str)
        os.makedirs(game_dir, exist_ok=True)
        path = os.path.join(game_dir, f"{game_pk}.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(feed, handle)

    def test_bootstrap_writes_csvs_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write_feed(tmp, "2026-06-24", 823850, FINAL_FEED)

            summary = bootstrap_mlb_player_game_log(tmp)
            self.assertEqual(summary["games_scanned"], 1)
            self.assertEqual(summary["games_new"], 1)
            self.assertEqual(summary["pitcher_rows_added"], 2)
            self.assertEqual(summary["batter_rows_added"], 1)

            pitcher_csv = os.path.join(tmp, "processed", "mlb_pitcher_game_log.csv")
            with open(pitcher_csv, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            names = {row["player_name"] for row in rows}
            self.assertIn("Eury Pérez", names)

            # Re-running with no new feed files must be a true no-op.
            second = bootstrap_mlb_player_game_log(tmp)
            self.assertEqual(second["games_scanned"], 1)
            self.assertEqual(second["games_new"], 0)
            self.assertEqual(second["pitcher_rows_added"], 0)
            self.assertEqual(second["batter_rows_added"], 0)
            self.assertEqual(second["pitcher_rows_total"], 2)

    def test_bootstrap_skips_non_final_games(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write_feed(tmp, "2026-06-25", 1, NOT_FINAL_FEED)
            summary = bootstrap_mlb_player_game_log(tmp)
            self.assertEqual(summary["games_scanned"], 1)
            self.assertEqual(summary["games_new"], 0)
            self.assertEqual(summary["pitcher_rows_total"], 0)

    def test_bootstrap_incrementally_adds_a_second_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write_feed(tmp, "2026-06-24", 823850, FINAL_FEED)
            bootstrap_mlb_player_game_log(tmp)

            second_feed = json.loads(json.dumps(FINAL_FEED))
            second_feed["liveData"]["boxscore"]["teams"]["away"]["players"]["ID691587"]["stats"]["pitching"]["strikeOuts"] = 3
            self._write_feed(tmp, "2026-06-30", 824338, second_feed)
            summary = bootstrap_mlb_player_game_log(tmp)

            self.assertEqual(summary["games_scanned"], 2)
            self.assertEqual(summary["games_new"], 1)
            self.assertEqual(summary["pitcher_rows_total"], 4)


if __name__ == "__main__":
    unittest.main()
