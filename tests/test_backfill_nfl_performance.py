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
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import scripts.backfill_nfl_performance as backfill
from syndicate.features.nfl.preseason_projection import SmartSimNflPreseasonProjection
from syndicate.features.nfl.preseason_projection import write_preseason_projection_artifact
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


_PRESEASON_SCHEDULE_FIELDS = [
    "game_id", "season", "game_type", "week", "gameday", "gametime",
    "away_team", "home_team", "away_score", "home_score", "status", "venue",
]
_PRESEASON_ODDS_SNAPSHOT_FIELDS = [
    "game_id", "season", "week", "home_team", "away_team",
    "home_moneyline", "away_moneyline", "spread_home", "total_line", "book", "fetched_at",
]


def _write_preseason_schedule(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PRESEASON_SCHEDULE_FIELDS)
        writer.writeheader()
        for row in rows:
            full = {key: "" for key in _PRESEASON_SCHEDULE_FIELDS}
            full.update(row)
            writer.writerow(full)


def _write_preseason_odds_snapshot(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PRESEASON_ODDS_SNAPSHOT_FIELDS)
        writer.writeheader()
        for row in rows:
            full = {key: "" for key in _PRESEASON_ODDS_SNAPSHOT_FIELDS}
            full.update(row)
            writer.writerow(full)


_PRESEASON_SCHEDULE_ROW = {
    "game_id": "401873271", "season": "2026", "game_type": "PRE", "week": "1",
    "gameday": "2026-08-07", "gametime": "00:00Z",
    "away_team": "CAR", "home_team": "ARI",
    "away_score": "17", "home_score": "24",
    "status": "Final",
}
_PRESEASON_ODDS_SNAPSHOT_ROW = {
    "game_id": "401873271", "season": "2026", "week": "1",
    "home_team": "ARI", "away_team": "CAR",
    "home_moneyline": "-150", "away_moneyline": "130",
    "spread_home": "-3.5", "total_line": "35.5",
    "book": "draftkings", "fetched_at": "2026-08-06T12:00:00+00:00",
}
_PRESEASON_PROJECTION = SmartSimNflPreseasonProjection(
    game_id="401873271", season=2026, week=1, home_team="ARI", away_team="CAR",
    home_score_mean=23.5, away_score_mean=19.0, margin_mean=4.5, total_mean=42.5,
    margin_stdev=10.1, total_stdev=9.4, home_win_rate=0.58, seeds_used=300,
    profile_name="nfl_preseason_v1", rating_source="test", generated_at="2026-08-01T00:00:00Z",
    nonstarter_participation_share=0.65, shrinkage_applied=0.4,
    uncertainty_note="starters limited",
)


class LoadCompletedPreseasonGamesTests(unittest.TestCase):
    def test_reads_completed_preseason_game_with_no_market_lines_and_real_gameday(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_preseason_schedule(root / "schedule_preseason_2026.csv", [_PRESEASON_SCHEDULE_ROW])
            games = backfill.load_completed_games(2026, 1, source_root=root, season_kind="preseason")
            self.assertIn("401873271", games)
            game = games["401873271"]
            self.assertEqual(game["home_score"], 24.0)
            self.assertEqual(game["away_score"], 17.0)
            self.assertEqual(game["gameday"], date(2026, 8, 7))
            # No market columns in ESPN's preseason schedule -- these are
            # filled in later, from the dated odds snapshot, by backfill_week().
            self.assertIsNone(game["market_margin"])
            self.assertIsNone(game["market_total"])

    def test_excludes_games_without_final_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            not_played = dict(_PRESEASON_SCHEDULE_ROW, game_id="401873272", away_score="", home_score="")
            _write_preseason_schedule(root / "schedule_preseason_2026.csv", [_PRESEASON_SCHEDULE_ROW, not_played])
            games = backfill.load_completed_games(2026, 1, source_root=root, season_kind="preseason")
            self.assertEqual(set(games), {"401873271"})

    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            games = backfill.load_completed_games(2026, 1, source_root=Path(tmp), season_kind="preseason")
            self.assertEqual(games, {})

    def test_regular_season_kind_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW])
            games_default = backfill.load_completed_games(2025, 1, source_root=root)
            games_explicit = backfill.load_completed_games(2025, 1, source_root=root, season_kind="regular")
            self.assertEqual(games_default, games_explicit)
            self.assertEqual(games_default["2025_01_NE_SEA"]["market_margin"], -3.5)


class LoadPreseasonMarketSnapshotsTests(unittest.TestCase):
    def test_reads_dated_snapshot_files_and_groups_by_game_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_preseason_odds_snapshot(root / "preseason_odds_snapshot_2026_08_06.csv", [_PRESEASON_ODDS_SNAPSHOT_ROW])
            index = backfill.load_preseason_market_snapshots(2026, source_root=root)
            self.assertIn("401873271", index)
            snapshot_date, row = index["401873271"][0]
            self.assertEqual(snapshot_date, date(2026, 8, 6))
            self.assertEqual(row["spread_home"], "-3.5")

    def test_ignores_files_for_other_seasons_and_non_matching_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_preseason_odds_snapshot(root / "preseason_odds_snapshot_2025_08_06.csv", [_PRESEASON_ODDS_SNAPSHOT_ROW])
            (root / "preseason_odds_2026.csv").write_text("game_id\n", encoding="utf-8")
            index = backfill.load_preseason_market_snapshots(2026, source_root=root)
            self.assertEqual(index, {})

    def test_missing_root_returns_empty(self) -> None:
        index = backfill.load_preseason_market_snapshots(2026, source_root=Path("Z:\\definitely\\missing"))
        self.assertEqual(index, {})

    def test_best_snapshot_row_prefers_latest_on_or_before_game_date(self) -> None:
        earlier = (date(2026, 8, 5), {"total_line": "35.0"})
        later_but_still_before = (date(2026, 8, 6), {"total_line": "35.5"})
        after_game = (date(2026, 8, 8), {"total_line": "99.0"})
        chosen = backfill._best_market_snapshot_row([earlier, later_but_still_before, after_game], game_date=date(2026, 8, 7))
        self.assertEqual(chosen["total_line"], "35.5")

    def test_best_snapshot_row_falls_back_to_latest_when_none_on_or_before(self) -> None:
        only_after = (date(2026, 8, 8), {"total_line": "99.0"})
        chosen = backfill._best_market_snapshot_row([only_after], game_date=date(2026, 8, 7))
        self.assertEqual(chosen["total_line"], "99.0")

    def test_best_snapshot_row_empty_entries_returns_none(self) -> None:
        self.assertIsNone(backfill._best_market_snapshot_row([], game_date=date(2026, 8, 7)))


class BackfillWeekPreseasonTests(unittest.TestCase):
    def test_joins_preseason_schedule_snapshot_and_projection_and_grades_a_real_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "preseason_perf.jsonl"
            _write_preseason_schedule(root / "schedule_preseason_2026.csv", [_PRESEASON_SCHEDULE_ROW])
            _write_preseason_odds_snapshot(root / "preseason_odds_snapshot_2026_08_06.csv", [_PRESEASON_ODDS_SNAPSHOT_ROW])
            write_preseason_projection_artifact([_PRESEASON_PROJECTION], season=2026, week=1, data_root=root)

            result = backfill.backfill_week(2026, 1, source_root=root, log_path=log_path, season_kind="preseason")

            self.assertEqual(result, {"completed_games": 1, "written": 1, "skipped_no_projection": 0})
            rows = read_performance_log(log_path=log_path)
            self.assertEqual(len(rows), 1)
            record = rows[0]
            self.assertEqual(record["game_id"], "401873271")
            self.assertEqual(record["actual_margin"], 7.0)  # 24 - 17
            self.assertEqual(record["actual_total"], 41.0)  # 24 + 17
            # spread_home=-3.5 -> market_margin = -(-3.5) = 3.5.
            self.assertEqual(record["market_margin"], 3.5)
            self.assertEqual(record["market_total"], 35.5)
            self.assertEqual(record["model_margin"], 4.5)
            self.assertEqual(record["model_total"], 42.5)

    def test_writes_to_the_separate_preseason_log_not_the_regular_season_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            regular_log = root / "smartsim2_performance_log.jsonl"
            preseason_log = root / "smartsim2_preseason_performance_log.jsonl"
            _write_preseason_schedule(root / "schedule_preseason_2026.csv", [_PRESEASON_SCHEDULE_ROW])
            _write_preseason_odds_snapshot(root / "preseason_odds_snapshot_2026_08_06.csv", [_PRESEASON_ODDS_SNAPSHOT_ROW])
            write_preseason_projection_artifact([_PRESEASON_PROJECTION], season=2026, week=1, data_root=root)

            backfill.backfill_week(2026, 1, source_root=root, log_path=preseason_log, season_kind="preseason")

            self.assertFalse(regular_log.exists())
            self.assertTrue(preseason_log.exists())
            self.assertEqual(len(read_performance_log(log_path=preseason_log)), 1)

    def test_completed_preseason_game_without_projection_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "preseason_perf.jsonl"
            _write_preseason_schedule(root / "schedule_preseason_2026.csv", [_PRESEASON_SCHEDULE_ROW])
            _write_preseason_odds_snapshot(root / "preseason_odds_snapshot_2026_08_06.csv", [_PRESEASON_ODDS_SNAPSHOT_ROW])
            # No projection artifact written.

            result = backfill.backfill_week(2026, 1, source_root=root, log_path=log_path, season_kind="preseason")

            self.assertEqual(result, {"completed_games": 1, "written": 0, "skipped_no_projection": 1})
            self.assertEqual(read_performance_log(log_path=log_path), [])

    def test_completed_preseason_game_without_any_snapshot_grades_with_null_market_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "preseason_perf.jsonl"
            _write_preseason_schedule(root / "schedule_preseason_2026.csv", [_PRESEASON_SCHEDULE_ROW])
            # No dated odds snapshot written at all.
            write_preseason_projection_artifact([_PRESEASON_PROJECTION], season=2026, week=1, data_root=root)

            result = backfill.backfill_week(2026, 1, source_root=root, log_path=log_path, season_kind="preseason")

            self.assertEqual(result["written"], 1)
            rows = read_performance_log(log_path=log_path)
            self.assertIsNone(rows[0]["market_margin"])
            self.assertIsNone(rows[0]["market_total"])


class RegularSeasonUnchangedTests(unittest.TestCase):
    """Confirms the default (no season_kind, or season_kind="regular")
    path is byte-for-byte identical to pre-preseason-task behavior."""

    def test_backfill_week_default_matches_explicit_regular_season_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_default = root / "default.jsonl"
            log_explicit = root / "explicit.jsonl"
            _write_schedule(root / "schedule_2025.csv", [_SCHEDULE_ROW])
            _write_projections(root / "smartsim2_projections_2025_wk1.csv", [_PROJECTION_ROW])

            result_default = backfill.backfill_week(2025, 1, source_root=root, log_path=log_default)
            result_explicit = backfill.backfill_week(2025, 1, source_root=root, log_path=log_explicit, season_kind="regular")

            self.assertEqual(result_default, result_explicit)
            self.assertEqual(read_performance_log(log_path=log_default), read_performance_log(log_path=log_explicit))


class MainCliSeasonKindTests(unittest.TestCase):
    def test_season_kind_flag_defaults_to_regular_and_uses_regular_log(self) -> None:
        calls: list[tuple] = []

        def fake_backfill_week(season, week, *, log_path, season_kind):
            calls.append((season, week, log_path, season_kind))
            return {"completed_games": 0, "written": 0, "skipped_no_projection": 0}

        argv = ["backfill_nfl_performance.py", "--season", "2025", "--weeks", "1"]
        with patch.object(sys, "argv", argv), patch.object(backfill, "backfill_week", side_effect=fake_backfill_week):
            backfill.main()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], backfill.PERFORMANCE_LOG_PATH)
        self.assertEqual(calls[0][3], "regular")

    def test_season_kind_preseason_flag_selects_preseason_log(self) -> None:
        calls: list[tuple] = []

        def fake_backfill_week(season, week, *, log_path, season_kind):
            calls.append((season, week, log_path, season_kind))
            return {"completed_games": 0, "written": 0, "skipped_no_projection": 0}

        argv = ["backfill_nfl_performance.py", "--season", "2026", "--weeks", "1", "--season-kind", "preseason"]
        with patch.object(sys, "argv", argv), patch.object(backfill, "backfill_week", side_effect=fake_backfill_week):
            backfill.main()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], backfill.PRESEASON_PERFORMANCE_LOG_PATH)
        self.assertEqual(calls[0][3], "preseason")

    def test_season_kind_preseason_weeks_all_uses_preseason_week_discovery(self) -> None:
        argv = ["backfill_nfl_performance.py", "--season", "2026", "--weeks", "all", "--season-kind", "preseason"]
        fake_result = {"completed_games": 0, "written": 0, "skipped_no_projection": 0}
        with patch.object(sys, "argv", argv), \
             patch.object(backfill, "preseason_seasons_and_weeks", return_value={2026: [1, 2]}) as mock_discovery, \
             patch.object(backfill, "backfill_week", return_value=fake_result) as mock_backfill:
            backfill.main()

        mock_discovery.assert_called_once()
        self.assertEqual(mock_backfill.call_count, 2)
        weeks_called = sorted(call.args[1] for call in mock_backfill.call_args_list)
        self.assertEqual(weeks_called, [1, 2])

    def test_season_kind_invalid_choice_rejected_by_argparse(self) -> None:
        argv = ["backfill_nfl_performance.py", "--season", "2026", "--weeks", "1", "--season-kind", "bogus"]
        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit):
                backfill.main()


if __name__ == "__main__":
    unittest.main()
