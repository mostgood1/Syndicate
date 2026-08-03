"""Regression coverage for scripts/backfill_nfl_performance.py.

Every helper here takes an explicit source_root/log_path (added specifically
so tests never touch the real data/nfl_source/data/smartsim2_performance_log.jsonl
by accident -- confirmed live during this module's own development: calling
backfill_week() without overriding these resolved to the real production
path via the module-level NFL_SOURCE_ROOT/PERFORMANCE_LOG_PATH constants,
same as NCAAF's equivalent script, which has no test at this level at all
for exactly this reason)."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import scripts.backfill_nfl_performance as backfill
from syndicate.features.nfl.smartsim2_performance_tracking import read_performance_log

_SCHEDULE_FIELDS = [
    "game_id", "season", "game_type", "week", "gameday", "gametime",
    "away_team", "home_team", "away_score", "home_score",
    "spread_line", "total_line", "away_moneyline", "home_moneyline", "stadium",
]
_PROJECTION_FIELDS = [
    "game_id", "season", "week", "home_team", "away_team",
    "home_score_mean", "away_score_mean", "margin_mean", "total_mean",
    "margin_stdev", "total_stdev", "home_win_rate", "seeds_used",
    "profile_name", "rating_source", "generated_at",
]


def _write_schedule(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_SCHEDULE_FIELDS)
        writer.writeheader()
        for row in rows:
            full = {key: "" for key in _SCHEDULE_FIELDS}
            full.update(row)
            writer.writerow(full)


def _write_projections(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PROJECTION_FIELDS)
        writer.writeheader()
        for row in rows:
            full = {key: "" for key in _PROJECTION_FIELDS}
            full.update(row)
            writer.writerow(full)


_SCHEDULE_ROW = {
    "game_id": "2025_01_NE_SEA", "season": "2025", "week": "1",
    "away_team": "NE", "home_team": "SEA",
    "away_score": "20", "home_score": "24",
    "spread_line": "3.5", "total_line": "44.5",
}
_PROJECTION_ROW = {
    "game_id": "2025_01_NE_SEA", "season": "2025", "week": "1",
    "home_team": "SEA", "away_team": "NE",
    "home_score_mean": "22.1", "away_score_mean": "21.8",
    "margin_mean": "0.3", "total_mean": "43.9",
    "margin_stdev": "13.8", "total_stdev": "11.2", "home_win_rate": "0.51",
    "seeds_used": "300", "profile_name": "nfl_v1", "rating_source": "test",
    "generated_at": "2026-08-01T00:00:00Z",
}


class LoadCompletedGamesTests(unittest.TestCase):
    def test_reads_completed_game_with_negated_market_margin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW])
            games = backfill.load_completed_games(2025, 1, source_root=root)
            self.assertIn("2025_01_NE_SEA", games)
            game = games["2025_01_NE_SEA"]
            # spread_line=3.5 is bet notation (home getting 3.5) -> market_margin
            # (home_points - away_points sense) is its negation, -3.5.
            self.assertEqual(game["market_margin"], -3.5)
            self.assertEqual(game["market_total"], 44.5)
            self.assertEqual(game["home_score"], 24.0)
            self.assertEqual(game["away_score"], 20.0)

    def test_excludes_games_without_final_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            not_played = dict(_SCHEDULE_ROW, game_id="2025_01_KC_LAC", away_score="", home_score="")
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW, not_played])
            games = backfill.load_completed_games(2025, 1, source_root=root)
            self.assertEqual(set(games), {"2025_01_NE_SEA"})

    def test_excludes_other_weeks_and_seasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            other_week = dict(_SCHEDULE_ROW, game_id="wk2", week="2")
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW, other_week])
            games = backfill.load_completed_games(2025, 1, source_root=root)
            self.assertEqual(set(games), {"2025_01_NE_SEA"})

    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            games = backfill.load_completed_games(2025, 1, source_root=Path(tmp))
            self.assertEqual(games, {})

    def test_market_lines_none_when_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_line = dict(_SCHEDULE_ROW, spread_line="", total_line="")
            _write_schedule(root / "schedule_2025.csv", [no_line])
            games = backfill.load_completed_games(2025, 1, source_root=root)
            game = games["2025_01_NE_SEA"]
            self.assertIsNone(game["market_margin"])
            self.assertIsNone(game["market_total"])


class LoadSmartsimProjectionsTests(unittest.TestCase):
    def test_reads_projection_keyed_by_game_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_projections(root / "smartsim2_projections_2025_wk1.csv", [_PROJECTION_ROW])
            projections = backfill.load_smartsim_projections(2025, 1, source_root=root)
            self.assertIn("2025_01_NE_SEA", projections)
            self.assertAlmostEqual(projections["2025_01_NE_SEA"]["model_margin"], 0.3)
            self.assertAlmostEqual(projections["2025_01_NE_SEA"]["model_total"], 43.9)

    def test_missing_artifact_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projections = backfill.load_smartsim_projections(2025, 1, source_root=Path(tmp))
            self.assertEqual(projections, {})


class BackfillWeekTests(unittest.TestCase):
    def test_joins_schedule_and_projection_and_writes_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "perf.jsonl"
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW])
            _write_projections(root / "smartsim2_projections_2025_wk1.csv", [_PROJECTION_ROW])

            result = backfill.backfill_week(2025, 1, source_root=root, log_path=log_path)

            self.assertEqual(result, {"completed_games": 1, "written": 1, "skipped_no_projection": 0})
            rows = read_performance_log(log_path=log_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_id"], "2025_01_NE_SEA")
            self.assertEqual(rows[0]["actual_margin"], 4.0)

    def test_completed_game_without_projection_is_skipped_not_dropped_silently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "perf.jsonl"
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW])
            # No projections file written at all.

            result = backfill.backfill_week(2025, 1, source_root=root, log_path=log_path)

            self.assertEqual(result, {"completed_games": 1, "written": 0, "skipped_no_projection": 1})
            self.assertEqual(read_performance_log(log_path=log_path), [])


if __name__ == "__main__":
    unittest.main()
