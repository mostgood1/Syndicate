from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaaf.cfbd import build_ncaaf_coach_continuity_generation_report
from syndicate.features.ncaaf.cfbd import build_ncaaf_coach_continuity_rows
from syndicate.features.ncaaf.cfbd import validate_ncaaf_coach_continuity_rows
from syndicate.features.ncaaf.cfbd import write_ncaaf_coach_continuity_snapshot_csv


class _StubClient:
    def __init__(self, payload):
        self.payload = payload
        self.prior_payload = [
            {
                "firstName": "Nick",
                "lastName": "Saban",
                "hireDate": "2007-12-03T00:00:00.000Z",
                "seasons": [
                    {"school": "Alabama", "year": 2024},
                ],
            }
        ]

    def _get_json(self, path: str, params: dict[str, object] | None = None):
        if path == "/coaches":
            if params and params.get("year") == 2024:
                return self.prior_payload
            return self.payload
        raise AssertionError(f"unexpected live call: {path} {params}")

    def fetch_team_catalog(self, season: int):
        return [
            {"school": "Alabama", "abbreviation": "ALA", "conference": "SEC", "division": "FBS", "aliases": ["Bama"]},
            {"school": "Wake Forest", "abbreviation": "WAKE", "conference": "ACC", "division": "FBS", "aliases": ["Demon Deacons"]},
        ]


class NcaafCoachContinuityBuilderTests(unittest.TestCase):
    def test_build_rows_and_validate(self) -> None:
        coach_rows = [
            {
                "firstName": "Kalen",
                "lastName": "DeBoer",
                "hireDate": "2024-01-12T00:00:00.000Z",
                "seasons": [
                    {"school": "Alabama", "year": 2024},
                    {"school": "Alabama", "year": 2025},
                ],
            },
            {
                "firstName": "Jake",
                "lastName": "Dickert",
                "hireDate": None,
                "seasons": [
                    {"school": "Wake Forest", "year": 2025},
                ],
            },
        ]
        team_registry_rows = [
            {"team_id": "ALA", "canonical_team_name": "Alabama", "abbreviation": "ALA", "conference": "SEC", "subdivision": "FBS", "aliases": "bama|alabama"},
            {"team_id": "WAKE", "canonical_team_name": "Wake Forest", "abbreviation": "WAKE", "conference": "ACC", "subdivision": "FBS", "aliases": "wake forest|demon deacons"},
        ]

        rows = build_ncaaf_coach_continuity_rows(season=2025, coach_rows=coach_rows, team_registry_rows=team_registry_rows)

        self.assertEqual(len(rows), 2)
        by_team = {row["team_id"]: row for row in rows}
        self.assertEqual(by_team["ALA"]["head_coach_name"], "Kalen DeBoer")
        rows = build_ncaaf_coach_continuity_rows(
            season=2025,
            coach_rows=coach_rows,
            prior_coach_rows=[
                {
                    "firstName": "Nick",
                    "lastName": "Saban",
                    "hireDate": "2007-12-03T00:00:00.000Z",
                    "seasons": [{"school": "Alabama", "year": 2024}],
                }
            ],
            team_registry_rows=team_registry_rows,
        )


        by_team = {row["team_id"]: row for row in rows}
        self.assertEqual(by_team["ALA"]["prior_season_head_coach"], "Nick Saban")
        self.assertEqual(by_team["ALA"]["coach_changed"], "1")
        self.assertEqual(by_team["WAKE"]["head_coach_name"], "Jake Dickert")

        issues = validate_ncaaf_coach_continuity_rows(rows, expected_season=2025, team_registry_rows=team_registry_rows)
        self.assertEqual(issues, [])

    def test_write_snapshot_and_report(self) -> None:
        coach_rows = [
            {
                "firstName": "Kalen",
                "lastName": "DeBoer",
                "hireDate": "2024-01-12T00:00:00.000Z",
                "seasons": [
                    {"school": "Alabama", "year": 2025},
                ],
            }
        ]
        client = _StubClient(coach_rows)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "ncaaf_coach_continuity_snapshot.csv"
            result = write_ncaaf_coach_continuity_snapshot_csv(client=client, season=2025, team_registry_rows=None, output_path=output_path)

            self.assertTrue(output_path.exists())
            self.assertEqual(len(result.rows), 1)
            with output_path.open("r", encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows[0]["head_coach_name"], "Kalen DeBoer")

            report = build_ncaaf_coach_continuity_generation_report(
                season=2025,
                output_path=output_path,
                rows=result.rows,
                validation_issues=result.validation_issues,
                source_system=result.source_system,
                source_snapshot_date=result.source_snapshot_date,
            )
            self.assertIn("Was the snapshot generated successfully? Yes.", report)
            self.assertIn("Is M6 complete? Yes", report)


if __name__ == "__main__":
    unittest.main()