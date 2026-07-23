from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from refresh_wnba_oddsapi_props import _materialize_processed_snapshot_alias
from refresh_wnba_oddsapi_props import _invalidate_stale_processed_snapshot_alias_if_needed


class InvalidateStaleProcessedSnapshotAliasTests(unittest.TestCase):
    # Confirmed live 2026-07-23: an all-star-break date's processed alias
    # kept serving a prior day's real 6-game slate forever, because a fresh
    # (correctly) empty raw fetch never invalidated the existing alias --
    # only ever refreshed it when the raw fetch actually had content.

    def test_deletes_alias_whose_rows_belong_to_a_different_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            alias_path = processed_root / "oddsapi_player_props_2026-07-23.csv"
            alias_path.write_text(
                "event_id,commence_time,home_team,away_team\n"
                "abc,2026-07-22T19:00:00Z,Los Angeles Sparks,Phoenix Mercury\n",
                encoding="utf-8",
            )

            _invalidate_stale_processed_snapshot_alias_if_needed(alias_path=alias_path, date_str="2026-07-23", log_file=None)

            self.assertFalse(alias_path.exists())

    def test_preserves_alias_whose_rows_genuinely_belong_to_the_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            alias_path = processed_root / "oddsapi_player_props_2026-07-22.csv"
            alias_path.write_text(
                "event_id,commence_time,home_team,away_team\n"
                "abc,2026-07-22T19:00:00Z,Los Angeles Sparks,Phoenix Mercury\n",
                encoding="utf-8",
            )

            _invalidate_stale_processed_snapshot_alias_if_needed(alias_path=alias_path, date_str="2026-07-22", log_file=None)

            self.assertTrue(alias_path.exists())

    def test_leaves_alias_untouched_when_commence_time_column_is_missing(self) -> None:
        # Ambiguous -- can't validate, so never delete on ambiguity, only on
        # a confirmed date mismatch.
        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            alias_path = processed_root / "oddsapi_player_props_2026-07-23.csv"
            alias_path.write_text("event_id,home_team,away_team\nabc,LAS,PHX\n", encoding="utf-8")

            _invalidate_stale_processed_snapshot_alias_if_needed(alias_path=alias_path, date_str="2026-07-23", log_file=None)

            self.assertTrue(alias_path.exists())

    def test_noop_when_alias_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            alias_path = processed_root / "oddsapi_player_props_2026-07-23.csv"

            _invalidate_stale_processed_snapshot_alias_if_needed(alias_path=alias_path, date_str="2026-07-23", log_file=None)

            self.assertFalse(alias_path.exists())


class MaterializeProcessedSnapshotAliasTests(unittest.TestCase):
    def test_invalidates_stale_alias_when_fresh_raw_snapshot_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            alias_path = processed_root / "oddsapi_player_props_2026-07-23.csv"
            alias_path.write_text(
                "event_id,commence_time,home_team,away_team\n"
                "abc,2026-07-22T19:00:00Z,Los Angeles Sparks,Phoenix Mercury\n",
                encoding="utf-8",
            )
            # Fresh raw fetch for 2026-07-23 came back empty (missing file
            # simulates a confirmed no-events write, same as
            # fetch_basketball_oddsapi_props_local.py's own empty-CSV output).
            missing_snapshot_path = root / "raw" / "odds_wnba_player_props_2026-07-23.csv"

            result_path, rows, error = _materialize_processed_snapshot_alias(
                processed_root=processed_root,
                date_str="2026-07-23",
                snapshot_path=missing_snapshot_path,
                log_file=None,
            )

            self.assertEqual(result_path, alias_path)
            self.assertEqual(rows, 0)
            self.assertIsNone(error)
            self.assertFalse(alias_path.exists())

    def test_preserves_valid_alias_when_fresh_raw_snapshot_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            alias_path = processed_root / "oddsapi_player_props_2026-07-22.csv"
            alias_path.write_text(
                "event_id,commence_time,home_team,away_team\n"
                "abc,2026-07-22T19:00:00Z,Los Angeles Sparks,Phoenix Mercury\n",
                encoding="utf-8",
            )
            missing_snapshot_path = root / "raw" / "odds_wnba_player_props_2026-07-22.csv"

            result_path, rows, error = _materialize_processed_snapshot_alias(
                processed_root=processed_root,
                date_str="2026-07-22",
                snapshot_path=missing_snapshot_path,
                log_file=None,
            )

            self.assertEqual(result_path, alias_path)
            self.assertEqual(rows, 1)
            self.assertIsNone(error)
            self.assertTrue(alias_path.exists())


if __name__ == "__main__":
    unittest.main()
