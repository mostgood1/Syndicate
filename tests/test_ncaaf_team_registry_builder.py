from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from syndicate.features.ncaaf.cfbd import build_team_registry_rows
from syndicate.features.ncaaf.cfbd import validate_team_registry_rows
from syndicate.features.ncaaf.cfbd import write_team_registry_snapshot_csv


class _StubClient:
    def fetch_team_catalog(self, *, season: int):
        return [
            {
                "school": "Alabama",
                "abbreviation": "ALA",
                "conference": "SEC",
                "division": "FBS",
                "nickname": "Crimson Tide",
            },
            {
                "school": "Wake Forest",
                "abbreviation": "WF",
                "conference": "ACC",
                "division": "FBS",
                "nickname": "Demon Deacons",
            },
        ]


class TeamRegistryBuilderTests(unittest.TestCase):
    def test_build_team_registry_rows(self):
        rows = build_team_registry_rows(season=2025, team_catalog_rows=_StubClient().fetch_team_catalog(season=2025))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["team_id"], "ALA")
        self.assertEqual(rows[0]["canonical_team_name"], "Alabama")
        self.assertEqual(rows[0]["conference"], "SEC")
        self.assertIn("alabama", rows[0]["aliases"])

    def test_validate_team_registry_rows(self):
        rows = build_team_registry_rows(season=2025, team_catalog_rows=_StubClient().fetch_team_catalog(season=2025))
        issues = validate_team_registry_rows(rows, expected_season=2025)
        self.assertEqual(issues, [])

    def test_write_team_registry_snapshot_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "ncaaf_team_registry.csv"
            result = write_team_registry_snapshot_csv(client=_StubClient(), season=2025, output_path=output_path)
            self.assertTrue(output_path.exists())
            self.assertEqual(len(result.rows), 2)
            self.assertEqual(result.validation_issues, ())


if __name__ == "__main__":
    unittest.main()