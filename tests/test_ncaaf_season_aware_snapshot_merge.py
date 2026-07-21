"""Regression coverage for the season-aware merge fix in cfbd.py.

Both the player-identity and roster snapshot CSVs hold every season in one
file (keyed by a ``season`` column), not one file per season. The write
functions used to fully overwrite the file on every run, which meant
refreshing a new season (or attempting to refresh a season CFBD had no data
for yet) silently destroyed every other season's rows -- this happened for
real during the 2026 NCAAF bootstrap (28,899 real 2025 roster rows were
replaced with 0 rows). These tests pin down the fix: refreshing one season
must never remove another season's rows already on disk.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaaf.cfbd import PLAYER_IDENTITY_COLUMNS
from syndicate.features.ncaaf.cfbd import ROSTER_SNAPSHOT_COLUMNS
from syndicate.features.ncaaf.cfbd import _merge_season_aware_rows
from syndicate.features.ncaaf.cfbd import write_ncaaf_roster_snapshot_csv
from syndicate.features.ncaaf.cfbd import write_player_identity_snapshot_csv


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class MergeSeasonAwareRowsTests(unittest.TestCase):
    def test_new_season_added_alongside_existing_other_season(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _write_csv(path, ROSTER_SNAPSHOT_COLUMNS, [{"player_id": "1", "player_name": "A", "team_id": "10", "position": "QB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2026-01-01"}])
            combined = _merge_season_aware_rows(
                path, season=2026, new_rows=[{"player_id": "2", "player_name": "B", "team_id": "11", "position": "RB", "season": "2026"}], columns=ROSTER_SNAPSHOT_COLUMNS
            )
            seasons = {row.get("season") for row in combined}
            self.assertEqual(seasons, {"2025", "2026"})
            self.assertEqual(len(combined), 2)

    def test_empty_new_season_does_not_wipe_existing_data(self) -> None:
        """The exact real-world scenario: refreshing season=2026 when CFBD
        has zero rows for it must leave 2025's rows untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            existing = [{"player_id": str(i), "player_name": f"P{i}", "team_id": "10", "position": "QB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2026-01-01"} for i in range(5)]
            _write_csv(path, ROSTER_SNAPSHOT_COLUMNS, existing)
            combined = _merge_season_aware_rows(path, season=2026, new_rows=[], columns=ROSTER_SNAPSHOT_COLUMNS)
            self.assertEqual(len(combined), 5)
            self.assertTrue(all(row.get("season") == "2025" for row in combined))

    def test_re_running_same_season_replaces_only_that_seasons_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _write_csv(
                path,
                ROSTER_SNAPSHOT_COLUMNS,
                [
                    {"player_id": "1", "player_name": "Old2025Player", "team_id": "10", "position": "QB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2026-01-01"},
                    {"player_id": "2", "player_name": "B2024", "team_id": "11", "position": "RB", "season": "2024", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2026-01-01"},
                ],
            )
            combined = _merge_season_aware_rows(
                path, season=2025, new_rows=[{"player_id": "3", "player_name": "New2025Player", "team_id": "10", "position": "QB", "season": "2025"}], columns=ROSTER_SNAPSHOT_COLUMNS
            )
            names = {row.get("player_name") for row in combined}
            self.assertEqual(names, {"B2024", "New2025Player"})

    def test_missing_file_just_returns_new_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.csv"
            combined = _merge_season_aware_rows(path, season=2026, new_rows=[{"player_id": "1", "season": "2026"}], columns=ROSTER_SNAPSHOT_COLUMNS)
            self.assertEqual(len(combined), 1)


class WriteFunctionsPreserveOtherSeasonsTests(unittest.TestCase):
    def test_write_player_identity_snapshot_csv_preserves_prior_season_when_new_season_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.csv"
            _write_csv(
                path,
                PLAYER_IDENTITY_COLUMNS,
                [{"player_id": "1", "player_name": "Real2025Player", "team_id": "10", "position": "QB", "season": "2025"}],
            )
            write_player_identity_snapshot_csv(season=2026, roster_rows=[], team_registry_rows=[{"team_id": "10", "school": "Team"}], output_path=path)
            rows = _read_csv(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["player_name"], "Real2025Player")
            self.assertEqual(rows[0]["season"], "2025")

    def test_write_ncaaf_roster_snapshot_csv_preserves_prior_season_when_new_season_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "identity.csv"
            roster_path = Path(tmp) / "roster.csv"
            _write_csv(
                identity_path,
                PLAYER_IDENTITY_COLUMNS,
                [{"player_id": "1", "player_name": "Real2025Player", "team_id": "10", "position": "QB", "season": "2025"}],
            )
            _write_csv(
                roster_path,
                ROSTER_SNAPSHOT_COLUMNS,
                [{"player_id": "1", "player_name": "Real2025Player", "team_id": "10", "position": "QB", "season": "2025", "roster_status": "active", "source_system": "cfbd", "source_snapshot_date": "2026-01-01"}],
            )
            # Simulate the real incident: identity snapshot now also has (empty) 2026
            # rows merged in, and we refresh the roster snapshot for season=2026.
            write_ncaaf_roster_snapshot_csv(season=2026, identity_snapshot_path=identity_path, output_path=roster_path)
            rows = _read_csv(roster_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["player_name"], "Real2025Player")
            self.assertEqual(rows[0]["season"], "2025")

    def test_write_ncaaf_roster_snapshot_csv_filters_identity_rows_to_requested_season(self) -> None:
        """Once the identity snapshot holds multiple seasons, building the
        roster for one season must not re-derive rows from other seasons
        present in that same identity file."""
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "identity.csv"
            roster_path = Path(tmp) / "roster.csv"
            _write_csv(
                identity_path,
                PLAYER_IDENTITY_COLUMNS,
                [
                    {"player_id": "1", "player_name": "Player2025", "team_id": "10", "position": "QB", "season": "2025"},
                    {"player_id": "2", "player_name": "Player2026", "team_id": "10", "position": "RB", "season": "2026"},
                ],
            )
            write_ncaaf_roster_snapshot_csv(season=2026, identity_snapshot_path=identity_path, output_path=roster_path)
            rows = _read_csv(roster_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["player_name"], "Player2026")


if __name__ == "__main__":
    unittest.main()
