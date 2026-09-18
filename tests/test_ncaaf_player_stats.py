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

    # -- the cache is keyed by the FILE (mtime/size), not the season ---------

    def _rewrite_without_cache_clear(self, rows: list[dict]) -> None:
        """A publish landing on disk: the file changes, nobody clears a cache."""
        with self.snapshot_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        # Force a distinct mtime even on a coarse-clock filesystem.
        stat = self.snapshot_path.stat()
        os.utime(self.snapshot_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    def test_a_republished_snapshot_is_read_without_a_restart(self) -> None:
        """The old season-keyed lru_cache served the boot-time reading until a
        deploy. A new week landing on disk must reach every reader on the next
        call -- rows, the name index and the per-player log alike."""
        self._write_snapshot([_row(season="2026", week="1", game_id="G1", player_id="QB1",
                                   player_name="Arch Manning", passing_yards="200")])
        self.assertEqual(len(player_stats.load_player_game_rows(2026)), 1)
        self.assertEqual(len(player_stats.player_game_log(2026, "QB1")), 1)
        self.assertIsNone(player_stats.resolve_player_id(2026, "New Guy"))

        self._rewrite_without_cache_clear([
            _row(season="2026", week="1", game_id="G1", player_id="QB1", player_name="Arch Manning", passing_yards="200"),
            _row(season="2026", week="2", game_id="G2", player_id="QB1", player_name="Arch Manning", passing_yards="310"),
            _row(season="2026", week="2", game_id="G2", player_id="WR9", player_name="New Guy", receptions="5"),
        ])
        self.assertEqual(len(player_stats.load_player_game_rows(2026)), 3)
        self.assertEqual([g["passing_yards"] for g in player_stats.player_game_log(2026, "QB1")], [200.0, 310.0])
        self.assertEqual(player_stats.resolve_player_id(2026, "New Guy"), "WR9")

    def test_an_unchanged_file_is_parsed_once(self) -> None:
        self._write_snapshot([_row(season="2026", week="1", game_id="G1", player_id="QB1")])
        first = player_stats.load_player_game_rows(2026)
        self.assertIs(player_stats.load_player_game_rows(2026), first)

    def test_a_snapshot_that_disappears_reads_empty_not_stale(self) -> None:
        self._write_snapshot([_row(season="2026", week="1", game_id="G1", player_id="QB1")])
        self.assertEqual(len(player_stats.load_player_game_rows(2026)), 1)
        self.snapshot_path.unlink()
        self.assertEqual(player_stats.load_player_game_rows(2026), ())

    def test_player_ids_by_name_keeps_every_namesake(self) -> None:
        """`player_name_index` collapses namesakes to one id; the ambiguity-aware
        index must not, or a question about one would answer with the other."""
        self._write_snapshot([
            _row(season="2026", week="1", game_id="G1", player_id="111", player_name="Joseph Williams", team="Colorado"),
            _row(season="2026", week="1", game_id="G2", player_id="222", player_name="Joseph Williams", team="Holy Cross"),
            _row(season="2026", week="1", game_id="G3", player_id="333", player_name="Kenneth Walker III", team="X"),
        ])
        index = player_stats.player_ids_by_name(2026)
        self.assertEqual(set(index["joseph williams"]), {"111", "222"})
        self.assertEqual(index["kenneth walker"], ("333",))
        self.assertEqual(player_stats.normalize_name("Ja'Kobi Lane"), "jakobi lane")
        self.assertEqual(player_stats.normalize_name("José Pérez Jr."), "jose perez")

    def test_opponent_for_reads_the_other_school_in_the_game(self) -> None:
        self._write_snapshot([
            _row(season="2026", week="1", game_id="G1", player_id="1", team="Texas"),
            _row(season="2026", week="1", game_id="G1", player_id="2", team="Ohio State"),
        ])
        self.assertEqual(player_stats.opponent_for(2026, "G1", "Texas"), "Ohio State")
        self.assertEqual(player_stats.opponent_for(2026, "G9", "Texas"), "")


if __name__ == "__main__":
    unittest.main()
