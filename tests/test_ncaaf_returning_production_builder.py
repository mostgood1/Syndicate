from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaaf.cfbd import build_ncaaf_returning_production_generation_report
from syndicate.features.ncaaf.cfbd import build_ncaaf_returning_production_rows
from syndicate.features.ncaaf.cfbd import validate_ncaaf_returning_production_rows
from syndicate.features.ncaaf.cfbd import write_ncaaf_returning_production_snapshot_csv


class _StubClient:
    def __init__(self, payload):
        self.payload = payload

    def _get_json(self, path: str, params: dict[str, object] | None = None):
        if path == "/player/returning":
            return self.payload
        raise AssertionError(f"unexpected live call: {path} {params}")


class NcaafReturningProductionBuilderTests(unittest.TestCase):
    def test_build_rows_joins_and_derives_expected_fields(self) -> None:
        returning_rows = [
            {
                "season": 2025,
                "team": "Alabama",
                "conference": "SEC",
                "totalPPA": 187.5,
                "totalPassingPPA": 46.4,
                "totalReceivingPPA": 118.8,
                "totalRushingPPA": 22.3,
                "percentPPA": 0.433,
                "percentPassingPPA": 0.394,
                "percentReceivingPPA": 0.571,
                "percentRushingPPA": 0.208,
                "usage": 0.395,
                "passingUsage": 0.098,
                "receivingUsage": 0.647,
                "rushingUsage": 0.482,
            }
        ]
        team_registry_rows = [
            {"team_id": "ALA", "canonical_team_name": "Alabama", "abbreviation": "ALA", "conference": "SEC", "subdivision": "FBS", "aliases": "alabama|bama"}
        ]
        roster_rows = [
            {"player_id": "1", "player_name": "Player One", "team_id": "ALA", "position": "QB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2025-01-01"},
            {"player_id": "2", "player_name": "Player Two", "team_id": "ALA", "position": "RB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2025-01-01"},
        ]
        transfer_rows = [
            {"player_id": "3", "player_name": "Player Three", "origin_team_id": "ALA", "destination_team_id": "TEX", "transfer_date": "2025-01-10", "season": "2025", "position": "WR", "eligibility": "Immediate", "source_system": "cfbd", "source_snapshot_date": "2025-01-01"}
        ]

        rows = build_ncaaf_returning_production_rows(
            season=2025,
            returning_rows=returning_rows,
            team_registry_rows=team_registry_rows,
            roster_rows=roster_rows,
            transfer_rows=transfer_rows,
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["team_id"], "ALA")
        self.assertEqual(row["team_name"], "Alabama")
        self.assertEqual(row["season"], "2025")
        self.assertEqual(row["source_system"], "cfbd")
        self.assertIn("transfer_adjusted_ppa", row)
        self.assertIn("returning_starter_estimate", row)

        issues = validate_ncaaf_returning_production_rows(rows, expected_season=2025, team_registry_rows=team_registry_rows)
        self.assertEqual(issues, [])

    def test_write_snapshot_and_report(self) -> None:
        returning_rows = [
            {
                "season": 2025,
                "team": "Alabama",
                "conference": "SEC",
                "totalPPA": 187.5,
                "totalPassingPPA": 46.4,
                "totalReceivingPPA": 118.8,
                "totalRushingPPA": 22.3,
                "percentPPA": 0.433,
                "percentPassingPPA": 0.394,
                "percentReceivingPPA": 0.571,
                "percentRushingPPA": 0.208,
                "usage": 0.395,
                "passingUsage": 0.098,
                "receivingUsage": 0.647,
                "rushingUsage": 0.482,
            }
        ]
        team_registry_rows = [
            {"team_id": "ALA", "canonical_team_name": "Alabama", "abbreviation": "ALA", "conference": "SEC", "subdivision": "FBS", "aliases": "alabama|bama"}
        ]
        roster_rows = [
            {"player_id": "1", "player_name": "Player One", "team_id": "ALA", "position": "QB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2025-01-01"}
        ]
        transfer_rows = []

        class StubClient:
            def _get_json(self, path: str, params: dict[str, object] | None = None):
                if path == "/player/returning":
                    return returning_rows
                raise AssertionError(f"unexpected live call: {path} {params}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "ncaaf_returning_production_snapshot.csv"
            result = write_ncaaf_returning_production_snapshot_csv(
                client=StubClient(),
                season=2025,
                roster_snapshot_path_input=None,
                transfer_snapshot_path_input=None,
                team_registry_rows=team_registry_rows,
                output_path=output_path,
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(len(result.rows), 1)
            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["team_id"], "ALA")

            report = build_ncaaf_returning_production_generation_report(
                season=2025,
                output_path=output_path,
                roster_path=Path(tmp_dir) / "roster.csv",
                transfer_path=Path(tmp_dir) / "transfers.csv",
                rows=result.rows,
                validation_issues=result.validation_issues,
                source_system=result.source_system,
                source_snapshot_date=result.source_snapshot_date,
            )
            self.assertIn("Was the snapshot generated successfully? Yes.", report)
            self.assertIn("Is M5 returning-production onboarding now complete? Yes", report)

    def test_zero_values_are_preserved_in_snapshot_rows(self) -> None:
        returning_rows = [
            {
                "season": 2025,
                "team": "Wake Forest",
                "conference": "ACC",
                "totalPPA": 97.5,
                "totalPassingPPA": 0,
                "totalReceivingPPA": 62,
                "totalRushingPPA": 35.5,
                "percentPPA": 0.262,
                "percentPassingPPA": 0,
                "percentReceivingPPA": 0.268,
                "percentRushingPPA": 0.575,
                "usage": 0.359,
                "passingUsage": 0,
                "receivingUsage": 0.245,
                "rushingUsage": 0.834,
            }
        ]
        team_registry_rows = [
            {"team_id": "WAKE", "canonical_team_name": "Wake Forest", "abbreviation": "WAKE", "conference": "ACC", "subdivision": "FBS", "aliases": "wake forest|wake|demon deacons"}
        ]

        rows = build_ncaaf_returning_production_rows(
            season=2025,
            returning_rows=returning_rows,
            team_registry_rows=team_registry_rows,
            roster_rows=[],
            transfer_rows=[],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["total_passing_ppa"], "0.0")
        self.assertEqual(row["percent_passing_ppa"], "0.0")
        self.assertEqual(row["passing_usage"], "0.0")


if __name__ == "__main__":
    unittest.main()