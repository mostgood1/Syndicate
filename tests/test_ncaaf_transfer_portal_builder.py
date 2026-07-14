from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaaf.cfbd import _deterministic_transfer_player_id
from syndicate.features.ncaaf.cfbd import build_ncaaf_transfer_portal_rows
from syndicate.features.ncaaf.cfbd import validate_ncaaf_transfer_portal_rows
from syndicate.features.ncaaf.cfbd import write_ncaaf_transfer_portal_snapshot_csv


class _StubClient:
    def _get_json(self, path: str, params: dict[str, object] | None = None):
        raise AssertionError(f"unexpected live call: {path} {params}")


class NcaafTransferPortalBuilderTests(unittest.TestCase):
    def test_build_ncaaf_transfer_portal_rows_uses_local_identity_and_dedupes(self) -> None:
        portal_rows = [
            {
                "season": 2025,
                "firstName": "Cameron",
                "lastName": "Williams",
                "position": "IOL",
                "origin": "Alabama A&M",
                "destination": "Kennesaw State",
                "transferDate": "2025-02-05T05:00:00.000Z",
                "eligibility": "Immediate",
            },
            {
                "season": 2025,
                "firstName": "Cameron",
                "lastName": "Williams",
                "position": "IOL",
                "origin": "Alabama A&M",
                "destination": "Kennesaw State",
                "transferDate": "2025-02-05T05:00:00.000Z",
                "eligibility": "Immediate",
            },
        ]
        identity_rows = [
            {
                "player_id": "4769892",
                "player_name": "Cameron Williams",
                "team_id": "AAMU",
                "position": "IOL",
                "season": "2025",
            }
        ]
        roster_rows = identity_rows
        team_registry_rows = [
            {"team_id": "AAMU", "canonical_team_name": "Alabama A&M", "abbreviation": "AAMU", "aliases": "alabama a m|alabama a&m", "conference": "SWAC", "subdivision": "FCS"},
            {"team_id": "KENN", "canonical_team_name": "Kennesaw State", "abbreviation": "KENN", "aliases": "kennesaw state", "conference": "CUSA", "subdivision": "FBS"},
        ]

        rows = build_ncaaf_transfer_portal_rows(
            client=_StubClient(),
            season=2025,
            portal_rows=portal_rows,
            identity_rows=identity_rows,
            roster_rows=roster_rows,
            team_registry_rows=team_registry_rows,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_id"], "4769892")
        self.assertEqual(rows[0]["origin_team_id"], "AAMU")
        self.assertEqual(rows[0]["destination_team_id"], "KENN")
        self.assertEqual(rows[0]["transfer_date"], "2025-02-05")

        issues = validate_ncaaf_transfer_portal_rows(rows, expected_season=2025, team_registry_rows=team_registry_rows)
        self.assertEqual(issues, [])

    def test_deterministic_transfer_player_id_is_stable(self) -> None:
        first = _deterministic_transfer_player_id(
            player_name="Daniel Ogundipe",
            origin_team_id="AAMU",
            destination_team_id="KENN",
            transfer_date="2025-04-01",
            season=2025,
        )
        second = _deterministic_transfer_player_id(
            player_name="Daniel Ogundipe",
            origin_team_id="AAMU",
            destination_team_id="KENN",
            transfer_date="2025-04-01",
            season=2025,
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("cfbd-transfer-"))

    def test_write_ncaaf_transfer_portal_snapshot_csv_emits_expected_file(self) -> None:
        from syndicate.features.ncaaf.cfbd import NcaafTransferPortalSnapshotResult

        portal_rows = [
            {
                "season": 2025,
                "firstName": "Cameron",
                "lastName": "Williams",
                "position": "IOL",
                "origin": "Alabama A&M",
                "destination": "Kennesaw State",
                "transferDate": "2025-02-05T05:00:00.000Z",
                "eligibility": "Immediate",
            }
        ]
        identity_rows = [
            {
                "player_id": "4769892",
                "player_name": "Cameron Williams",
                "team_id": "AAMU",
                "position": "IOL",
                "season": "2025",
            }
        ]
        roster_rows = identity_rows
        team_registry_rows = [
            {"team_id": "AAMU", "canonical_team_name": "Alabama A&M", "abbreviation": "AAMU", "aliases": "alabama a m|alabama a&m", "conference": "SWAC", "subdivision": "FCS"},
            {"team_id": "KENN", "canonical_team_name": "Kennesaw State", "abbreviation": "KENN", "aliases": "kennesaw state", "conference": "CUSA", "subdivision": "FBS"},
        ]

        class StubClientWithPortal(_StubClient):
            def _get_json(self, path: str, params: dict[str, object] | None = None):
                if path == "/player/portal":
                    return portal_rows
                raise AssertionError(f"unexpected live call: {path} {params}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "ncaaf_transfer_portal_snapshot.csv"
            from syndicate.features.ncaaf.cfbd import write_ncaaf_transfer_portal_snapshot_csv

            result = write_ncaaf_transfer_portal_snapshot_csv(
                client=StubClientWithPortal(),
                season=2025,
                identity_rows=identity_rows,
                roster_snapshot_path_input=None,
                team_registry_rows=team_registry_rows,
                output_path=output_path,
            )

            self.assertEqual(result.output_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertEqual(len(result.rows), 1)


if __name__ == "__main__":
    unittest.main()