from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.cfbd import build_integration_report
from syndicate.features.ncaaf.cfbd import build_player_identity_rows
from syndicate.features.ncaaf.cfbd import build_team_registry_rows
from syndicate.features.ncaaf.cfbd import load_team_registry_rows
from syndicate.features.ncaaf.cfbd import validate_player_identity_rows
from syndicate.features.ncaaf.cfbd import write_player_identity_snapshot_csv


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class NcaafCfbdPlayerIdentityTests(unittest.TestCase):
    def test_client_uses_bearer_auth_and_connectivity_test(self) -> None:
        client = CfbdClient("secret-key", timeout=1.0)

        def fake_request(session, method, url, **kwargs):
            assert method == "GET"
            assert "/teams/fbs" in url
            headers = kwargs.get("headers") or {}
            assert headers.get("Authorization") == "Bearer secret-key"
            return _FakeResponse([{"school": "Alabama", "abbreviation": "ALA"}])

        with patch("requests.Session.request", new=fake_request):
            result = client.test_connection(season=2026)

        self.assertTrue(result["connected"])
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["sample_team"], "Alabama")

    def test_build_rows_canonicalizes_dedupes_and_validates(self) -> None:
        team_catalog_rows = [
            {
                "school": "Alabama",
                "abbreviation": "ALA",
                "conference": "SEC",
                "division": "FBS",
                "aliases": ["Alabama Crimson Tide", "Bama"],
            },
            {
                "school": "Texas",
                "abbreviation": "TEX",
                "conference": "SEC",
                "division": "FBS",
                "aliases": ["Texas Longhorns"],
            },
        ]
        team_registry_rows = build_team_registry_rows(season=2026, team_catalog_rows=team_catalog_rows)
        roster_rows = [
            {
                "id": "1001",
                "firstName": "Jalen",
                "lastName": "Milroe",
                "school": "Alabama",
                "position": "QB",
                "year": 2026,
            },
            {
                "playerId": "1001",
                "fullName": "Jalen Milroe",
                "team": "ALA",
                "position": "QB",
                "season": 2026,
            },
            {
                "id": "1002",
                "firstName": "Quinn",
                "lastName": "Ewers",
                "school": "Texas",
                "pos": "QB",
                "year": 2026,
            },
        ]

        rows = build_player_identity_rows(season=2026, roster_rows=roster_rows, team_registry_rows=team_registry_rows)

        self.assertEqual(len(rows), 2)
        row_by_id = {row["player_id"]: row for row in rows}
        self.assertEqual(row_by_id["1001"]["player_name"], "Jalen Milroe")
        self.assertEqual(row_by_id["1001"]["team_id"], "ALA")
        self.assertEqual(row_by_id["1002"]["position"], "QB")
        self.assertEqual(row_by_id["1002"]["season"], "2026")

        issues = validate_player_identity_rows(rows, team_registry_rows=team_registry_rows, season=2026)
        self.assertEqual(issues, [])

    def test_write_snapshot_and_report(self) -> None:
        team_catalog_rows = [
            {
                "school": "Alabama",
                "abbreviation": "ALA",
                "conference": "SEC",
                "division": "FBS",
                "aliases": ["Bama"],
            }
        ]
        team_registry_rows = build_team_registry_rows(season=2026, team_catalog_rows=team_catalog_rows)
        roster_rows = [
            {"id": "2001", "firstName": "Ty", "lastName": "Simpson", "school": "Alabama", "position": "QB", "year": 2026}
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "ncaaf_player_identity_snapshot.csv"
            result = write_player_identity_snapshot_csv(
                season=2026,
                roster_rows=roster_rows,
                team_registry_rows=team_registry_rows,
                output_path=output_path,
            )
            self.assertTrue(output_path.exists())
            self.assertEqual(result.rows[0]["team_id"], "ALA")

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["player_name"], "Ty Simpson")

            report = build_integration_report(
                season=2026,
                connectivity={"connected": True, "endpoint": "/teams/fbs"},
                team_registry_rows=team_registry_rows,
                roster_rows=roster_rows,
                snapshot_rows=result.rows,
                validation_issues=result.validation_issues,
                output_path=output_path,
                registry_mode="provisional_cfbd_team_catalog",
            )
            self.assertIn("Did CFBD successfully connect? Yes.", report)
            self.assertIn("Can CFBD populate the player identity snapshot? Yes.", report)

    def test_registry_loader_prefers_file_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "team_registry.csv"
            with registry_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["team_id", "canonical_team_name", "abbreviation", "conference", "subdivision", "aliases"])
                writer.writeheader()
                writer.writerow(
                    {
                        "team_id": "ALA",
                        "canonical_team_name": "Alabama",
                        "abbreviation": "ALA",
                        "conference": "SEC",
                        "subdivision": "FBS",
                        "aliases": "Alabama|Bama",
                    }
                )
            rows = load_team_registry_rows(registry_path=registry_path, season=2026, team_catalog_rows=[])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["team_id"], "ALA")


if __name__ == "__main__":
    unittest.main()