from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path
from typing import Any

from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_player_stats
from syndicate.features.nfl.sources import default_nfl_source_root


ROSTER_SNAPSHOT_COLUMNS = (
    "player_id",
    "player_name",
    "team",
    "position",
    "season",
    "snapshot_date",
    "team_abbr",
    "team_name",
    "player_display_name",
    "position_group",
    "source_system",
    "source_file",
    "source_date",
    "source_player_id",
    "source_player_name",
    "source_team_name",
)


@dataclass(frozen=True)
class RosterSnapshotBuildResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    source_file: str
    snapshot_date: str


def roster_snapshot_output_path(*, season: int, snapshot_date: str | None = None, publish: bool = False) -> Path:
    root = default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "rosters"
    if snapshot_date and publish:
        suffix = "_publish" if publish else ""
        return root / f"roster_{season}_snapshot_{snapshot_date.replace('-', '_')}{suffix}.csv"
    suffix = "_publish" if publish else ""
    return root / f"roster_{season}_snapshot{suffix}.csv"


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _normalize_position(row: dict[str, Any]) -> str:
    position = _safe_text(row.get("position") or "")
    if position:
        return position
    return _safe_text(row.get("position_group") or "")


def _normalize_source_row(
    row: dict[str, Any],
    *,
    season: int,
    snapshot_date: str,
    source_file: str,
) -> dict[str, str]:
    player_id = _safe_text(row.get("player_id") or row.get("source_player_id") or "")
    player_name = _safe_text(row.get("player_display_name") or row.get("player_name") or row.get("full_name") or row.get("name") or "")
    team = canonical_team_abbr(row.get("team") or row.get("team_abbr") or row.get("team_name") or row.get("source_team_name") or "")
    position = _normalize_position(row)
    team_metadata = canonical_team_metadata(team)
    return {
        "player_id": player_id,
        "player_name": player_name,
        "team": team,
        "position": position,
        "season": str(season),
        "snapshot_date": snapshot_date,
        "team_abbr": team_metadata.get("team_abbr") or team,
        "team_name": team_metadata.get("team_name") or team,
        "player_display_name": _safe_text(row.get("player_display_name") or player_name),
        "position_group": _safe_text(row.get("position_group") or position),
        "source_system": "nflverse_player_stats",
        "source_file": source_file,
        "source_date": snapshot_date,
        "source_player_id": player_id,
        "source_player_name": _safe_text(row.get("player_name") or row.get("player_display_name") or player_name),
        "source_team_name": _safe_text(row.get("team") or row.get("team_name") or row.get("source_team_name") or team),
    }


def _player_sort_key(row: dict[str, str]) -> tuple[int, int, str, str]:
    season_value = int(row.get("season") or 0)
    week_value = int(_safe_text(row.get("week") or "0") or 0)
    return (season_value, week_value, row.get("team") or "", row.get("player_name") or "")


def build_roster_snapshot_rows(
    *,
    season: int = 2026,
    snapshot_date: str | None = None,
    source_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> tuple[dict[str, str], ...]:
    snapshot_day = snapshot_date or date_type.today().isoformat()
    source_file = str(default_nfl_source_root() / "tracking" / "nflverse" / "player_stats" / f"player_stats_{season}.csv")
    rows = list(source_rows) if source_rows is not None else list(load_nflverse_player_stats(season))
    normalized_rows = [
        _normalize_source_row(row, season=season, snapshot_date=snapshot_day, source_file=source_file)
        for row in rows
        if isinstance(row, dict)
    ]
    grouped: dict[str, dict[str, str]] = {}
    for row in normalized_rows:
        if not row.get("player_id"):
            fallback_key = "|".join((row.get("player_name") or "", row.get("team") or "", row.get("position") or ""))
            if not fallback_key.strip("|"):
                continue
            group_key = fallback_key
        else:
            group_key = row["player_id"]
        current = grouped.get(group_key)
        if current is None or _player_sort_key(row) >= _player_sort_key(current):
            grouped[group_key] = row

    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("team") or "", row.get("player_name") or "", row.get("player_id") or ""))
    return tuple(deduped)


def validate_roster_snapshot_rows(rows: list[dict[str, str]] | tuple[dict[str, str], ...]) -> list[str]:
    issues: list[str] = []
    required_fields = ("player_id", "player_name", "team", "position")
    seen_player_ids: Counter[str] = Counter()
    valid_teams = {
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU",
        "IND", "JAX", "KC", "LV", "LAC", "LA", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI",
        "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    }

    for index, row in enumerate(rows):
        for field in required_fields:
            if not _safe_text(row.get(field)):
                issues.append(f"row {index} missing required field {field}")
        player_id = _safe_text(row.get("player_id"))
        team = _safe_text(row.get("team")).upper()
        if player_id:
            seen_player_ids[player_id] += 1
        if team not in valid_teams:
            issues.append(f"row {index} has invalid team {team}")

    duplicate_ids = [player_id for player_id, count in seen_player_ids.items() if count > 1]
    for player_id in duplicate_ids:
        issues.append(f"duplicate player_id {player_id}")
    return issues


def write_roster_snapshot_csv(
    *,
    season: int = 2026,
    snapshot_date: str | None = None,
    output_path: Path | None = None,
    publish: bool = False,
    source_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> RosterSnapshotBuildResult:
    snapshot_day = snapshot_date or date_type.today().isoformat()
    rows = build_roster_snapshot_rows(season=season, snapshot_date=snapshot_day, source_rows=source_rows)
    issues = validate_roster_snapshot_rows(rows)
    if issues:
        raise ValueError("Roster snapshot validation failed: " + "; ".join(issues))

    path = output_path or roster_snapshot_output_path(season=season, snapshot_date=None, publish=publish)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROSTER_SNAPSHOT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in ROSTER_SNAPSHOT_COLUMNS})

    source_file = str(default_nfl_source_root() / "tracking" / "nflverse" / "player_stats" / f"player_stats_{season}.csv")
    return RosterSnapshotBuildResult(rows=rows, output_path=path, source_file=source_file, snapshot_date=snapshot_day)
