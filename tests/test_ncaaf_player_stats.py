from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.ncaaf import player_stats


_COLUMNS = (
    "season",
    "week",
    "game_id",
    "player_id",
    "player_name",
    "team",
    "passing_completions",
    "passing_attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_attempts",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "anytime_td",
    "source_system",
    "source_snapshot_date",
)


def _row(**overrides) -> dict:
    row = {column: "" for column in _COLUMNS}
    row.update(
        {
            "season": "2025",
            "week": "1",
            "game_id": "401752675",
            "player_id": "QB1",
            "player_name": "P.One",
            "team": "Illinois State",
            "passing_completions": "0",
            "passing_attempts": "0",
            "passing_yards": "0",
            "passing_tds": "0",
            "interceptions": "0",
            "rushing_attempts": "0",
            "rushing_yards": "0",
            "rushing_tds": "0",
            "receptions": "0",
            "receiving_yards": "0",
            "receiving_tds": "0",
            "anytime_td": "0",
            "source_system": "cfbd",
            "source_snapshot_date": "2026-08-05",
        }
    )
    row.update(overrides)
    return row


class NcaafPlayerStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.snapshot_path = Path(self._tmp.name) / "ncaaf_player_game_stats_snapshot.csv"
        self._path_patch = patch.object(player_stats, "player_game_stats_snapshot_path", return_value=self.snapshot_path)
        self._path_patch.start()
        self.addCleanup(self._path_patch.stop)
        player_stats.load_player_game_rows.cache_clear()
        player_stats.player_name_index.cache_clear()

    def _write_snapshot(self, rows: list[dict]) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with self.snapshot_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        player_stats.load_player_game_rows.cache_clear()
        player_stats.player_name_index.cache_clear()

    def test_no_snapshot_file_returns_empty(self) -> None:
        self.assertEqual(player_stats.load_player_game_rows(2025), ())
        self.assertEqual(player_stats.player_game_log(2025, "QB1"), [])

    def test_player_game_log_reads_merged_stat_row(self) -> None:
        self._write_snapshot(
            [
                _row(
                    week="1",
                    game_id="G1",
                    player_id="QB1",
                    passing_yards="220",
                    passing_attempts="30",
                    passing_tds="2",
                    interceptions="1",
                    rushing_attempts="4",
                    rushing_yards="10",
                ),
                _row(week="2", game_id="G2", player_id="QB1", passing_yards="180", passing_attempts="25"),
            ]
        )
        log = player_stats.player_game_log(2025, "QB1")
        self.assertEqual(len(log), 2)
        week1 = log[0]
        self.assertEqual(week1["passing_yards"], 220.0)
        self.assertEqual(week1["passing_attempts"], 30.0)
        self.assertEqual(week1["passing_tds"], 2.0)
        self.assertEqual(week1["interceptions"], 1.0)
        self.assertEqual(week1["rushing_yards"], 10.0)

    def test_anytime_td_stat_is_read_directly(self) -> None:
        self._write_snapshot(
            [_row(week="1", game_id="G1", player_id="RB1", rushing_tds="1", anytime_td="1")]
        )
        log = player_stats.player_game_log(2025, "RB1")
        self.assertEqual(log[0]["anytime_td"], 1.0)

    def test_player_rate_requires_at_least_two_games(self) -> None:
        self._write_snapshot([_row(week="1", game_id="G1", player_id="QB1", passing_yards="200")])
        mean, stdev, n = player_stats.player_rate(2025, 2, "QB1", "passing_yards")
        self.assertIsNone(mean)
        self.assertEqual(n, 1)

    def test_player_rate_excludes_current_and_later_weeks(self) -> None:
        self._write_snapshot(
            [
                _row(week="1", game_id="G1", player_id="QB1", passing_yards="200"),
                _row(week="2", game_id="G2", player_id="QB1", passing_yards="220"),
                _row(week="5", game_id="G5", player_id="QB1", passing_yards="999"),
            ]
        )
        mean, stdev, n = player_stats.player_rate(2025, 3, "QB1", "passing_yards")
        self.assertEqual(n, 2)
        self.assertAlmostEqual(mean, 210.0)

    def test_resolve_player_id_matches_full_display_name(self) -> None:
        # Unlike NFL's pbp (first-initial.last-name), CFBD's /games/players
        # athletes already carry the full display name -- no short-name
        # bridging needed.
        self._write_snapshot(
            [_row(week="1", game_id="G1", player_id="4878284", player_name="Tommy Rittenhouse", passing_yards="22")]
        )
        self.assertEqual(player_stats.resolve_player_id(2025, "Tommy Rittenhouse"), "4878284")
        self.assertEqual(player_stats.resolve_player_id(2025, "  tommy rittenhouse  "), "4878284")
        self.assertIsNone(player_stats.resolve_player_id(2025, "Nobody Real"))

    def test_final_stat_value_returns_real_settled_value(self) -> None:
        self._write_snapshot([_row(week="1", game_id="G1", player_id="QB1", passing_yards="200")])
        self.assertEqual(player_stats.final_stat_value(2025, "G1", "QB1", "passing_yards"), 200.0)
        self.assertIsNone(player_stats.final_stat_value(2025, "no_such_game", "QB1", "passing_yards"))

    def test_load_player_game_rows_filters_to_requested_season(self) -> None:
        self._write_snapshot(
            [
                _row(season="2025", week="1", game_id="G1", player_id="QB1", passing_yards="200"),
                _row(season="2026", week="1", game_id="G9", player_id="QB1", passing_yards="999"),
            ]
        )
        rows_2025 = player_stats.load_player_game_rows(2025)
        self.assertEqual(len(rows_2025), 1)
        self.assertEqual(rows_2025[0]["passing_yards"], 200.0)


if __name__ == "__main__":
    unittest.main()
