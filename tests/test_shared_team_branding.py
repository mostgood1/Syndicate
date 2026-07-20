from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from syndicate.features.shared.team_branding import TeamBranding
from syndicate.features.shared.team_branding import parse_espn_teams_payload
from syndicate.features.shared.team_branding import read_team_branding_snapshot
from syndicate.features.shared.team_branding import team_branding_index_by_abbreviation
from syndicate.features.shared.team_branding import team_branding_index_by_id
from syndicate.features.shared.team_branding import write_team_branding_snapshot


def _espn_payload(*teams: dict) -> dict:
    return {"sports": [{"leagues": [{"teams": [{"team": team} for team in teams]}]}]}


def _team(**overrides) -> dict:
    base = dict(
        id="1",
        abbreviation="ATL",
        location="Atlanta",
        displayName="Atlanta Hawks",
        color="c8102e",
        alternateColor="fdb927",
        logos=[
            {"href": "https://a.espncdn.com/i/teamlogos/nba/500-dark/atl.png", "rel": ["full", "dark"]},
            {"href": "https://a.espncdn.com/i/teamlogos/nba/500/atl.png", "rel": ["full", "default"]},
        ],
    )
    base.update(overrides)
    return base


class ParseEspnPayloadTests(unittest.TestCase):
    def test_parses_basic_team_fields(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team()), snapshot_date="2026-07-20")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.team_id, "1")
        self.assertEqual(row.abbreviation, "ATL")
        self.assertEqual(row.location, "Atlanta")
        self.assertEqual(row.display_name, "Atlanta Hawks")
        self.assertEqual(row.source_snapshot_date, "2026-07-20")

    def test_normalizes_hex_colors_with_hash_prefix(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team()), snapshot_date="2026-07-20")
        self.assertEqual(rows[0].primary_color, "#c8102e")
        self.assertEqual(rows[0].secondary_color, "#fdb927")

    def test_missing_color_is_none(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team(color="", alternateColor=None)), snapshot_date="2026-07-20")
        self.assertIsNone(rows[0].primary_color)
        self.assertIsNone(rows[0].secondary_color)

    def test_invalid_color_is_none(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team(color="not-a-color")), snapshot_date="2026-07-20")
        self.assertIsNone(rows[0].primary_color)

    def test_prefers_default_logo_rel_over_first_entry(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team()), snapshot_date="2026-07-20")
        self.assertEqual(rows[0].logo_url, "https://a.espncdn.com/i/teamlogos/nba/500/atl.png")

    def test_falls_back_to_first_logo_when_no_default_rel(self) -> None:
        rows = parse_espn_teams_payload(
            _espn_payload(_team(logos=[{"href": "https://example.com/only.png", "rel": ["full", "dark"]}])),
            snapshot_date="2026-07-20",
        )
        self.assertEqual(rows[0].logo_url, "https://example.com/only.png")

    def test_no_logos_is_none(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team(logos=[])), snapshot_date="2026-07-20")
        self.assertIsNone(rows[0].logo_url)

    def test_team_without_id_is_skipped(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team(id="")), snapshot_date="2026-07-20")
        self.assertEqual(rows, [])

    def test_multiple_teams_across_leagues(self) -> None:
        payload = {
            "sports": [
                {"leagues": [{"teams": [{"team": _team(id="1", abbreviation="ATL")}]}]},
                {"leagues": [{"teams": [{"team": _team(id="2", abbreviation="BOS")}]}]},
            ]
        }
        rows = parse_espn_teams_payload(payload, snapshot_date="2026-07-20")
        self.assertEqual({r.abbreviation for r in rows}, {"ATL", "BOS"})

    def test_malformed_payload_returns_empty(self) -> None:
        self.assertEqual(parse_espn_teams_payload({}, snapshot_date="2026-07-20"), [])
        self.assertEqual(parse_espn_teams_payload({"sports": "nope"}, snapshot_date="2026-07-20"), [])


class SnapshotRoundTripTests(unittest.TestCase):
    def test_write_then_read_round_trip(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team(), _team(id="2", abbreviation="BOS")), snapshot_date="2026-07-20")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "branding.csv"
            write_team_branding_snapshot(rows, path=path)
            loaded = read_team_branding_snapshot(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual({r.team_id for r in loaded}, {"1", "2"})
        self.assertEqual(loaded[0].primary_color, "#c8102e")

    def test_read_missing_snapshot_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.csv"
            self.assertEqual(read_team_branding_snapshot(path), ())


class IndexTests(unittest.TestCase):
    def test_index_by_id(self) -> None:
        rows = parse_espn_teams_payload(_espn_payload(_team(id="1"), _team(id="2", abbreviation="BOS")), snapshot_date="2026-07-20")
        index = team_branding_index_by_id(rows)
        self.assertEqual(set(index), {"1", "2"})

    def test_index_by_abbreviation_uppercases_and_skips_blank(self) -> None:
        rows = parse_espn_teams_payload(
            _espn_payload(_team(abbreviation="atl"), _team(id="2", abbreviation="")),
            snapshot_date="2026-07-20",
        )
        index = team_branding_index_by_abbreviation(rows)
        self.assertEqual(set(index), {"ATL"})


if __name__ == "__main__":
    unittest.main()
