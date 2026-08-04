from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import scripts.migrate_odds_history_to_shards as migrate_module
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_paths_for_sport
from syndicate.features.shared.odds_control_plane import shared_odds_history_root


class MigrateOddsHistoryToShardsTests(unittest.TestCase):
    def test_migrate_sport_splits_entries_by_date_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_DATA_ROOT": str(Path(tmp_dir) / "data"),
            },
            clear=False,
        ):
            combined_path = shared_odds_history_root() / "mlb" / "odds_history.json"
            combined_path.parent.mkdir(parents=True, exist_ok=True)
            combined_payload = {
                "schema_version": 1,
                "sport": "mlb",
                "markets": {
                    "market-a": {
                        "history": [
                            {"date": "2026-06-01", "captured_at": "2026-06-01T10:00:00Z", "current_line": 1.5},
                            {"date": "2026-06-01", "captured_at": "2026-06-01T11:00:00Z", "current_line": 1.5},
                        ]
                    },
                    "market-b": {
                        "history": [
                            {"date": "2026-06-02", "captured_at": "2026-06-02T10:00:00Z", "current_line": 2.5},
                        ]
                    },
                },
            }
            combined_path.write_text(json.dumps(combined_payload), encoding="utf-8")

            result = migrate_module.migrate_sport("mlb", dry_run=False)

            self.assertTrue(result["ok"])
            self.assertFalse(result["skipped"])
            self.assertEqual(result["shard_count"], 2)
            self.assertEqual(result["unassigned_entries"], 0)
            self.assertEqual(result["shards"]["2026-06-01"]["entries"], 2)
            self.assertEqual(result["shards"]["2026-06-02"]["entries"], 1)

            for path_str in result["shards"]["2026-06-01"]["paths"]:
                self.assertTrue(Path(path_str).exists())

            shard_a_path = Path(result["shards"]["2026-06-01"]["paths"][0])
            shard_a_payload = json.loads(shard_a_path.read_text(encoding="utf-8"))
            self.assertIn("market-a", shard_a_payload["markets"])
            self.assertNotIn("market-b", shard_a_payload["markets"])

            rerun_result = migrate_module.migrate_sport("mlb", dry_run=False)
            self.assertEqual(result, rerun_result)

    def test_migrate_sport_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_DATA_ROOT": str(Path(tmp_dir) / "data"),
            },
            clear=False,
        ):
            combined_path = shared_odds_history_root() / "nhl" / "odds_history.json"
            combined_path.parent.mkdir(parents=True, exist_ok=True)
            combined_path.write_text(
                json.dumps(
                    {
                        "markets": {
                            "market-c": {
                                "history": [{"date": "2026-06-03", "captured_at": "2026-06-03T10:00:00Z", "current_line": 3.5}]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = migrate_module.migrate_sport("nhl", dry_run=True)

            self.assertEqual(result["shard_count"], 1)
            for path_str in result["shards"]["2026-06-03"]["paths"]:
                self.assertFalse(Path(path_str).exists())

    def test_migrate_sport_skips_when_no_combined_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
                "SYNDICATE_DATA_ROOT": str(Path(tmp_dir) / "data"),
            },
            clear=False,
        ):
            result = migrate_module.migrate_sport("ncaab", dry_run=False)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["reason"], "no_combined_payload")


if __name__ == "__main__":
    unittest.main()


class OddsHistoryFreshestCopyWinsTests(unittest.TestCase):
    """A stale local copy used to shadow a freshly pulled one.

    odds_history_paths_for_sport's precedence is shared -> artifacts ->
    tracking, and load_odds_history_payload_for_sport took the first hit. But
    those paths do not refresh through the same route: the shared copy is not
    in HOT_ARTIFACT_PATTERNS and can never cross services, while the artifacts
    copy is pulled from web every board-build cycle. Confirmed live
    2026-08-04 on refresh-worker: STREAM_PULL_OK wrote the full 3,436-market
    MLB shard and the next build still read entry_count=611 from the stale
    shared copy, leaving every MLB board candidate at history_points=0.
    """

    def _write(self, path: Path, markets: dict, mtime: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"markets": markets}), encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_newer_artifacts_copy_beats_an_older_shared_copy(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": tmp_dir, "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False):
                paths = odds_history_paths_for_sport("mlb", "2026-08-04")
                self._write(paths[0], {"stale": {}}, 1785700000.0)          # shared, older
                self._write(paths[1], {"a": {}, "b": {}}, 1785800000.0)     # artifacts, newer
                payload = load_odds_history_payload_for_sport("mlb", "2026-08-04")
            self.assertEqual(sorted(payload["markets"]), ["a", "b"])

    def test_precedence_still_decides_when_copies_were_written_together(self) -> None:
        # The writer emits all three at once, so equal mtimes must resolve the
        # old way rather than arbitrarily.
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": tmp_dir, "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False):
                paths = odds_history_paths_for_sport("mlb", "2026-08-04")
                self._write(paths[0], {"shared": {}}, 1785800000.0)
                self._write(paths[1], {"artifacts": {}}, 1785800000.0)
                payload = load_odds_history_payload_for_sport("mlb", "2026-08-04")
            self.assertEqual(list(payload["markets"]), ["shared"])

    def test_missing_shard_still_returns_none(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": tmp_dir, "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False):
                self.assertIsNone(load_odds_history_payload_for_sport("mlb", "2026-08-04"))
