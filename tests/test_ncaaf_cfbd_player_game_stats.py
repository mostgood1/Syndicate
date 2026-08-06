from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.cfbd import build_ncaaf_player_game_stats_generation_report
from syndicate.features.ncaaf.cfbd import build_ncaaf_player_game_stats_rows
from syndicate.features.ncaaf.cfbd import validate_ncaaf_player_game_stats_rows
from syndicate.features.ncaaf.cfbd import write_ncaaf_player_game_stats_snapshot_csv


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


def _games_players_fixture() -> list[dict]:
    """Shaped exactly like the REAL CFBD /games/players response, confirmed
    live 2026-08-05 against
    https://api.collegefootballdata.com/games/players?year=2025&week=1&seasonType=regular
    -- a flat list of games, each with `id` and `teams`, each team with
    `team`/`categories`, each category with `name`/`types`, each type with
    `name`/`athletes` ({id, name, stat} where stat is always a string,
    including combined "C/ATT" strings like "6/13")."""
    return [
        {
            "id": 401752675,
            "teams": [
                {
                    "team": "Illinois State",
                    "conference": "MVFC",
                    "homeAway": "away",
                    "points": 3,
                    "categories": [
                        {
                            "name": "passing",
                            "types": [
                                {
                                    "name": "C/ATT",
                                    "athletes": [{"id": "4878284", "name": "Tommy Rittenhouse", "stat": "6/13"}],
                                },
                                {
                                    "name": "YDS",
                                    "athletes": [{"id": "4878284", "name": "Tommy Rittenhouse", "stat": "22"}],
                                },
                                {
                                    "name": "TD",
                                    "athletes": [{"id": "4878284", "name": "Tommy Rittenhouse", "stat": "0"}],
                                },
                                {
                                    "name": "INT",
                                    "athletes": [{"id": "4878284", "name": "Tommy Rittenhouse", "stat": "1"}],
                                },
                                {
                                    "name": "QBR",
                                    "athletes": [{"id": "4878284", "name": "Tommy Rittenhouse", "stat": "--"}],
                                },
                            ],
                        },
                        {
                            "name": "rushing",
                            "types": [
                                {
                                    "name": "CAR",
                                    "athletes": [
                                        {"id": "4878284", "name": "Tommy Rittenhouse", "stat": "8"},
                                        {"id": "4878290", "name": "Wenkers Wright", "stat": "12"},
                                    ],
                                },
                                {
                                    "name": "YDS",
                                    "athletes": [
                                        {"id": "4878284", "name": "Tommy Rittenhouse", "stat": "30"},
                                        {"id": "4878290", "name": "Wenkers Wright", "stat": "55"},
                                    ],
                                },
                                {
                                    "name": "TD",
                                    "athletes": [
                                        {"id": "4878284", "name": "Tommy Rittenhouse", "stat": "0"},
                                        {"id": "4878290", "name": "Wenkers Wright", "stat": "1"},
                                    ],
                                },
                            ],
                        },
                        {
                            "name": "receiving",
                            "types": [
                                {"name": "REC", "athletes": [{"id": "4878291", "name": "W.One", "stat": "3"}]},
                                {"name": "YDS", "athletes": [{"id": "4878291", "name": "W.One", "stat": "45"}]},
                                {"name": "TD", "athletes": [{"id": "4878291", "name": "W.One", "stat": "1"}]},
                            ],
                        },
                        {
                            "name": "defensive",
                            "types": [
                                {"name": "TOT", "athletes": [{"id": "9999999", "name": "D.One", "stat": "5"}]},
                            ],
                        },
                    ],
                }
            ],
        }
    ]


class NcaafCfbdPlayerGameStatsTests(unittest.TestCase):
    def test_client_fetch_requires_week(self) -> None:
        client = CfbdClient("secret-key", timeout=1.0)
        with self.assertRaises(ValueError):
            client.fetch_player_game_stats(season=2025)

    def test_client_fetch_uses_bearer_auth_and_week_param(self) -> None:
        client = CfbdClient("secret-key", timeout=1.0)
        seen_params: dict = {}

        def fake_request(session, method, url, **kwargs):
            assert method == "GET"
            assert "/games/players" in url
            seen_params.update(kwargs.get("params") or {})
            headers = kwargs.get("headers") or {}
            assert headers.get("Authorization") == "Bearer secret-key"
            return _FakeResponse(_games_players_fixture())

        with patch("requests.Session.request", new=fake_request):
            rows = client.fetch_player_game_stats(season=2025, week=1)

        self.assertEqual(seen_params.get("year"), 2025)
        self.assertEqual(seen_params.get("week"), 1)
        self.assertEqual(seen_params.get("seasonType"), "regular")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 401752675)

    def test_build_rows_merges_dual_category_player_and_splits_c_att(self) -> None:
        rows = build_ncaaf_player_game_stats_rows(season=2025, week=1, games_payload=_games_players_fixture())
        by_id = {row["player_id"]: row for row in rows}

        self.assertEqual(len(rows), 3)

        rittenhouse = by_id["4878284"]
        self.assertEqual(rittenhouse["player_name"], "Tommy Rittenhouse")
        self.assertEqual(rittenhouse["team"], "Illinois State")
        self.assertEqual(float(rittenhouse["passing_completions"]), 6.0)
        self.assertEqual(float(rittenhouse["passing_attempts"]), 13.0)
        self.assertEqual(float(rittenhouse["passing_yards"]), 22.0)
        self.assertEqual(float(rittenhouse["interceptions"]), 1.0)
        # Same athlete also has a rushing category entry in the same game --
        # must be merged onto the same row, not a second row.
        self.assertEqual(float(rittenhouse["rushing_attempts"]), 8.0)
        self.assertEqual(float(rittenhouse["rushing_yards"]), 30.0)
        # A passing TD (there is none here) never counts as anytime_td --
        # this player has zero rushing/receiving TDs, so anytime_td is 0.
        self.assertEqual(float(rittenhouse["anytime_td"]), 0.0)

        wright = by_id["4878290"]
        self.assertEqual(float(wright["rushing_tds"]), 1.0)
        self.assertEqual(float(wright["anytime_td"]), 1.0)

        receiver = by_id["4878291"]
        self.assertEqual(float(receiver["receptions"]), 3.0)
        self.assertEqual(float(receiver["receiving_yards"]), 45.0)
        self.assertEqual(float(receiver["anytime_td"]), 1.0)

        # Defensive category rows are not player-offense stat lines and
        # must not leak into the snapshot.
        self.assertNotIn("9999999", by_id)

        issues = validate_ncaaf_player_game_stats_rows(rows, expected_season=2025, expected_week=1)
        self.assertEqual(issues, [])

    def test_write_snapshot_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "ncaaf_player_game_stats_snapshot.csv"
            result = write_ncaaf_player_game_stats_snapshot_csv(
                client=CfbdClient("secret-key", timeout=1.0),
                season=2025,
                week=1,
                games_payload=_games_players_fixture(),
                output_path=output_path,
            )
            self.assertTrue(output_path.exists())
            self.assertEqual(result.validation_issues, ())

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)

            report = build_ncaaf_player_game_stats_generation_report(
                season=2025,
                week=1,
                output_path=result.output_path,
                rows=result.rows,
                validation_issues=result.validation_issues,
                source_system=result.source_system,
                source_snapshot_date=result.source_snapshot_date,
            )
            self.assertIn("Was the player game stats snapshot generated successfully? Yes.", report)

    def test_write_snapshot_preserves_other_weeks(self) -> None:
        # Refreshing week 2 must not wipe out week 1's already-fetched rows
        # -- same discipline as _merge_season_aware_rows for the roster/
        # identity snapshots (see cfbd.py's real comment on that bug).
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "ncaaf_player_game_stats_snapshot.csv"
            client = CfbdClient("secret-key", timeout=1.0)
            write_ncaaf_player_game_stats_snapshot_csv(
                client=client, season=2025, week=1, games_payload=_games_players_fixture(), output_path=output_path
            )
            write_ncaaf_player_game_stats_snapshot_csv(
                client=client, season=2025, week=2, games_payload=[], output_path=output_path
            )

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["week"] == "1" for row in rows))


if __name__ == "__main__":
    unittest.main()
