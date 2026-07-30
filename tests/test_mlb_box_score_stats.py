from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.mlb.box_score_stats import final_stat_value
from syndicate.features.mlb.box_score_stats import load_final_feed


FEED = {
    "liveData": {
        "boxscore": {
            "teams": {
                "away": {
                    "players": {
                        "ID111": {
                            "person": {"id": 111, "fullName": "Test Pitcher"},
                            "stats": {"pitching": {"strikeOuts": 7, "hits": 4, "outs": 18, "earnedRuns": 2, "baseOnBalls": 1}},
                        }
                    }
                },
                "home": {
                    "players": {
                        "ID222": {
                            "person": {"id": 222, "fullName": "Test Hitter"},
                            "stats": {"batting": {"hits": 2, "runs": 1, "rbi": 3, "homeRuns": 1, "totalBases": 6}},
                        }
                    }
                },
            }
        }
    }
}


class FinalStatValueTests(unittest.TestCase):
    def test_pitcher_stats_resolve_by_player_id(self) -> None:
        self.assertEqual(final_stat_value(FEED, group="pitcher", stat="strikeouts", player_name="wrong name", player_id=111), 7.0)
        self.assertEqual(final_stat_value(FEED, group="pitcher", stat="outs", player_name="wrong name", player_id=111), 18.0)
        self.assertEqual(final_stat_value(FEED, group="pitcher", stat="hits_allowed", player_name="wrong name", player_id=111), 4.0)
        self.assertEqual(final_stat_value(FEED, group="pitcher", stat="earned_runs", player_name="wrong name", player_id=111), 2.0)
        self.assertEqual(final_stat_value(FEED, group="pitcher", stat="walks_allowed", player_name="wrong name", player_id=111), 1.0)

    def test_pitcher_stats_fall_back_to_normalized_name(self) -> None:
        self.assertEqual(final_stat_value(FEED, group="pitcher", stat="strikeouts", player_name="Test Pitcher"), 7.0)

    def test_hitter_combined_stat_sums_hits_runs_rbi(self) -> None:
        self.assertEqual(final_stat_value(FEED, group="hitter", stat="hits_runs_rbis", player_name="Test Hitter", player_id=222), 6.0)

    def test_hitter_simple_stats(self) -> None:
        self.assertEqual(final_stat_value(FEED, group="hitter", stat="hits", player_name="Test Hitter", player_id=222), 2.0)
        self.assertEqual(final_stat_value(FEED, group="hitter", stat="home_runs", player_name="Test Hitter", player_id=222), 1.0)
        self.assertEqual(final_stat_value(FEED, group="hitter", stat="total_bases", player_name="Test Hitter", player_id=222), 6.0)

    def test_unknown_player_returns_none(self) -> None:
        self.assertIsNone(final_stat_value(FEED, group="pitcher", stat="strikeouts", player_name="Nobody"))

    def test_outs_falls_back_to_innings_pitched_when_outs_field_missing(self) -> None:
        feed = {
            "liveData": {
                "boxscore": {
                    "teams": {
                        "away": {"players": {"ID333": {"person": {"id": 333, "fullName": "IP Pitcher"}, "stats": {"pitching": {"inningsPitched": "5.2"}}}}},
                        "home": {"players": {}},
                    }
                }
            }
        }
        self.assertEqual(final_stat_value(feed, group="pitcher", stat="outs", player_name="IP Pitcher", player_id=333), 17.0)


class LoadFinalFeedTests(unittest.TestCase):
    def test_reads_cached_json_file(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "824001.json"
            cache_path.write_text(json.dumps(FEED), encoding="utf-8")
            with patch("syndicate.features.mlb.box_score_stats.raw_feed_live_path", return_value=cache_path):
                payload = load_final_feed("2026-07-23", 824001)
        self.assertEqual(payload, FEED)

    def test_missing_cache_and_fetch_disabled_returns_none(self) -> None:
        with patch("syndicate.features.mlb.box_score_stats.raw_feed_live_path", return_value=None):
            self.assertIsNone(load_final_feed("2026-07-23", 824001, fetch_if_missing=False))


if __name__ == "__main__":
    unittest.main()
