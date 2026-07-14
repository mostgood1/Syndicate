from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.football.ingestion.depth_chart_snapshot_builder import build_depth_snapshot_rows
from syndicate.features.football.ingestion.depth_chart_snapshot_builder import validate_depth_snapshot_rows
from syndicate.features.football.ingestion.depth_chart_snapshot_builder import write_depth_snapshot_csv


def test_build_depth_snapshot_rows_normalizes_joins_and_dedupes() -> None:
    roster_rows = [
        {"player_id": "p1", "player_name": "Alpha Player", "team": "PHI", "position": "WR"},
        {"player_id": "p2", "player_name": "Beta Player", "team": "DAL", "position": "QB"},
    ]
    depth_rows = [
        {
            "player_id": "p1",
            "player_name": "Alpha Player",
            "team": "Philadelphia Eagles",
            "position": "WR",
            "depth_rank": 1,
            "role": "starter",
            "starter_flag": True,
            "source_system": "demo_depth_feed",
        },
        {
            "player_id": "p1",
            "player_name": "Alpha Player",
            "team": "PHI",
            "position": "WR",
            "depth_rank": 1,
            "role": "starter",
            "starter_flag": True,
            "source_system": "demo_depth_feed",
        },
        {
            "player_name": "Beta Player",
            "team": "Dallas Cowboys",
            "position": "QB",
            "depth_rank": "2",
            "role": "backup",
            "backup_flag": True,
            "source_player_name": "Beta Player",
        },
    ]

    rows = build_depth_snapshot_rows(roster_rows=roster_rows, depth_rows=depth_rows, source_file="demo_depth_feed.csv")

    assert len(rows) == 2
    assert rows[0]["team"] in {"DAL", "PHI"}
    assert {row["player_id"] for row in rows} == {"p1", "p2"}
    assert any(row["starter_flag"] == "true" for row in rows)
    assert any(row["backup_flag"] == "true" for row in rows)


def test_validate_depth_snapshot_rows_rejects_duplicate_team_position_depth() -> None:
    rows = [
        {
            "player_id": "p1",
            "player_name": "Alpha Player",
            "team": "PHI",
            "position": "WR",
            "depth_rank": "1",
            "role": "starter",
        },
        {
            "player_id": "p2",
            "player_name": "Gamma Player",
            "team": "PHI",
            "position": "WR",
            "depth_rank": "1",
            "role": "backup",
        },
    ]

    issues = validate_depth_snapshot_rows(rows)

    assert any("duplicate team/position/depth_rank PHI/WR/1" in issue for issue in issues)


def test_write_depth_snapshot_csv_emits_expected_file(tmp_path: Path) -> None:
    roster_rows = [
        {"player_id": "p1", "player_name": "Alpha Player", "team": "PHI", "position": "WR"},
    ]
    depth_rows = [
        {
            "player_id": "p1",
            "player_name": "Alpha Player",
            "team": "PHI",
            "position": "WR",
            "depth_rank": 1,
            "role": "starter",
            "starter_flag": True,
            "source_system": "demo_depth_feed",
        },
    ]
    output_path = tmp_path / "depth_2026_snapshot.csv"

    result = write_depth_snapshot_csv(
        roster_rows=roster_rows,
        depth_rows=depth_rows,
        output_path=output_path,
        snapshot_date="2026-07-13",
        source_file="demo_depth_feed.csv",
    )

    assert result.output_path == output_path
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "player_id,player_name,team,position,depth_rank,role" in content
    assert "p1" in content


def test_validate_depth_snapshot_rows_rejects_invalid_team_and_role_context() -> None:
    rows = [
        {
            "player_id": "p1",
            "player_name": "Alpha Player",
            "team": "INVALID",
            "position": "WR",
            "depth_rank": "1",
            "role": "starter",
        }
    ]

    issues = validate_depth_snapshot_rows(rows)

    assert any("invalid team" in issue for issue in issues)
