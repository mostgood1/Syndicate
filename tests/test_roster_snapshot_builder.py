from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from syndicate.features.football.ingestion.roster_snapshot_builder import build_roster_snapshot_rows
from syndicate.features.football.ingestion.roster_snapshot_builder import roster_snapshot_output_path
from syndicate.features.football.ingestion.roster_snapshot_builder import validate_roster_snapshot_rows
from syndicate.features.football.ingestion.roster_snapshot_builder import write_roster_snapshot_csv


class RosterSnapshotBuilderTests(unittest.TestCase):
    def test_build_roster_snapshot_rows_canonicalizes_and_dedupes(self) -> None:
        source_rows = [
            {
                "player_id": "00-001",
                "player_name": "A. Player",
                "player_display_name": "Alpha Player",
                "team": "Philadelphia Eagles",
                "position": "",
                "position_group": "WR",
                "season": 2026,
                "week": 1,
            },
            {
                "player_id": "00-001",
                "player_name": "A. Player",
                "player_display_name": "Alpha Player",
                "team": "PHI",
                "position": "WR",
                "position_group": "WR",
                "season": 2026,
                "week": 2,
            },
            {
                "player_id": "00-002",
                "player_name": "B. Player",
                "player_display_name": "Beta Player",
                "team": "Dallas Cowboys",
                "position": "QB",
                "season": 2026,
                "week": 1,
            },
        ]

        rows = build_roster_snapshot_rows(season=2026, snapshot_date="2026-07-13", source_rows=source_rows)

        self.assertEqual(len(rows), 2)
        row_by_id = {row["player_id"]: row for row in rows}
        self.assertEqual(row_by_id["00-001"]["team"], "PHI")
        self.assertEqual(row_by_id["00-001"]["position"], "WR")
        self.assertEqual(row_by_id["00-001"]["player_name"], "Alpha Player")
        self.assertEqual(row_by_id["00-001"]["snapshot_date"], "2026-07-13")
        self.assertEqual(row_by_id["00-002"]["team_name"], "Dallas Cowboys")

        issues = validate_roster_snapshot_rows(rows)
        self.assertEqual(issues, [])

    def test_write_roster_snapshot_csv_emits_expected_file(self) -> None:
        source_rows = [
            {
                "player_id": "00-003",
                "player_name": "C. Player",
                "player_display_name": "Charlie Player",
                "team": "San Francisco 49ers",
                "position": "RB",
                "season": 2026,
                "week": 1,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "roster_2026_snapshot.csv"
            result = write_roster_snapshot_csv(
                season=2026,
                snapshot_date="2026-07-13",
                output_path=output_path,
                source_rows=source_rows,
            )

            self.assertEqual(result.output_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertEqual(roster_snapshot_output_path(season=2026).name, "roster_2026_snapshot.csv")

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["player_id"], "00-003")
            self.assertEqual(rows[0]["team"], "SF")
            self.assertEqual(rows[0]["player_name"], "Charlie Player")


if __name__ == "__main__":
    unittest.main()