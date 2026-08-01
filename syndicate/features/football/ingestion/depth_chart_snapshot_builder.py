from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path
from typing import Any

from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.nfl.sources import default_nfl_source_root


DEPTH_SNAPSHOT_COLUMNS = (
    "player_id",
    "player_name",
    "team",
    "position",
    "depth_rank",
    "role",
    "starter_flag",
    "backup_flag",
    "positional_group",
    "roster_status",
    "season",
    "snapshot_date",
    "source_system",
    "source_file",
    "source_date",
    "source_player_id",
    "source_player_name",
    "source_team_name",
    "notes",
)


@dataclass(frozen=True)
class DepthChartSnapshotBuildResult:
    rows: tuple[dict[str, str], ...]
    output_path: Path
    roster_source_file: str
    depth_source_file: str
    snapshot_date: str


def depth_chart_snapshot_output_path(*, season: int, snapshot_date: str | None = None, publish: bool = False) -> Path:
    root = default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "depth"
    if snapshot_date and publish:
        suffix = "_publish" if publish else ""
        return root / f"depth_{season}_snapshot_{snapshot_date.replace('-', '_')}{suffix}.csv"
    suffix = "_publish" if publish else ""
    return root / f"depth_{season}_snapshot{suffix}.csv"


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_bool_text(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "y", "starter"}:
        return "true"
    if lowered in {"0", "false", "no", "n", "backup"}:
        return "false"
    return text


def _safe_int_text(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _normalize_player_name(row: dict[str, Any]) -> str:
    return _safe_text(
        row.get("player_name")
        or row.get("player_display_name")
        or row.get("full_name")
        or row.get("name")
        or row.get("source_player_name")
    )


def _normalize_team(row: dict[str, Any]) -> str:
    return canonical_team_abbr(row.get("team") or row.get("team_abbr") or row.get("team_name") or row.get("source_team_name") or "")


def _normalize_position(row: dict[str, Any]) -> str:
    return _safe_text(row.get("position") or row.get("position_group") or row.get("positional_group") or row.get("pos_abb") or "")


def _normalize_depth_row(
    row: dict[str, Any],
    *,
    season: int,
    snapshot_date: str,
    source_file: str,
) -> dict[str, str]:
    player_name = _normalize_player_name(row)
    team = _normalize_team(row)
    position = _normalize_position(row)
    player_id = _safe_text(row.get("player_id") or row.get("source_player_id") or row.get("player_ref") or row.get("gsis_id") or "")
    depth_rank = _safe_int_text(row.get("depth_rank") or row.get("depth_order") or row.get("rank") or row.get("pos_rank") or "")
    role = _safe_text(row.get("role") or row.get("depth_role") or row.get("starter_status") or "")
    if not role and depth_rank:
        # nflverse's real depth_charts release carries pos_rank (real
        # 1-based depth-chart slot per position), not a starter/backup
        # label directly -- derive the label from that real rank rather
        # than leaving role empty (required by validate_depth_snapshot_rows).
        role = "Starter" if depth_rank == "1" else f"Depth {depth_rank}"
    starter_flag = _safe_bool_text(row.get("starter_flag") or row.get("is_starter") or row.get("starter") or "")
    backup_flag = _safe_bool_text(row.get("backup_flag") or row.get("is_backup") or row.get("backup") or "")
    return {
        "player_id": player_id,
        "player_name": player_name,
        "team": team,
        "position": position,
        "depth_rank": depth_rank,
        "role": role,
        "starter_flag": starter_flag,
        "backup_flag": backup_flag,
        "positional_group": _safe_text(row.get("positional_group") or row.get("position_group") or position),
        "roster_status": _safe_text(row.get("roster_status") or row.get("status") or ""),
        "season": str(season),
        "snapshot_date": snapshot_date,
        "source_system": _safe_text(row.get("source_system") or "authoritative_depth_feed") or "authoritative_depth_feed",
        "source_file": source_file,
        "source_date": _safe_text(row.get("source_date") or snapshot_date),
        "source_player_id": _safe_text(row.get("source_player_id") or player_id),
        "source_player_name": _safe_text(row.get("source_player_name") or player_name),
        "source_team_name": _safe_text(row.get("source_team_name") or row.get("team_name") or row.get("team") or team),
        "notes": _safe_text(row.get("notes") or ""),
    }


def _depth_sort_key(row: dict[str, str]) -> tuple[int, int, str, str, str]:
    season_value = int(_safe_text(row.get("season") or "0") or 0)
    depth_value = int(_safe_text(row.get("depth_rank") or "0") or 0)
    return (season_value, depth_value, row.get("team") or "", row.get("position") or "", row.get("player_name") or "")


def _roster_identity_index(roster_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, dict[str, str]]:
    identity_index: dict[str, dict[str, str]] = {}
    for row in roster_rows:
        if not isinstance(row, dict):
            continue
        player_id = _safe_text(row.get("player_id"))
        player_name = _safe_text(row.get("player_name"))
        team = canonical_team_abbr(row.get("team") or "")
        position = _safe_text(row.get("position") or "")
        if player_id:
            identity_index[f"id:{player_id}"] = {"player_id": player_id, "player_name": player_name, "team": team, "position": position}
        if player_name and team and position:
            identity_index[f"name:{player_name.lower()}|{team}|{position.lower()}"] = {"player_id": player_id, "player_name": player_name, "team": team, "position": position}
    return identity_index


def _build_row_key(row: dict[str, str]) -> str:
    return "|".join((row.get("team") or "", row.get("position") or "", row.get("depth_rank") or "", row.get("player_id") or row.get("player_name") or ""))


def build_depth_snapshot_rows(
    *,
    season: int = 2026,
    snapshot_date: str | None = None,
    roster_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    depth_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    source_file: str = "authoritative_depth_feed.csv",
) -> tuple[dict[str, str], ...]:
    snapshot_day = snapshot_date or date_type.today().isoformat()
    roster_index = _roster_identity_index(roster_rows)
    normalized_rows: list[dict[str, str]] = []
    for row in depth_rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_depth_row(row, season=season, snapshot_date=snapshot_day, source_file=source_file)
        if not normalized.get("player_id") and normalized.get("player_name") and normalized.get("team") and normalized.get("position"):
            fallback_key = f"name:{normalized['player_name'].lower()}|{normalized['team']}|{normalized['position'].lower()}"
            roster_match = roster_index.get(fallback_key)
            if roster_match and roster_match.get("player_id"):
                normalized["player_id"] = roster_match["player_id"]
                normalized["source_player_id"] = roster_match["player_id"]
            else:
                # Real nflverse depth-chart rows for practice-squad/
                # undrafted players sometimes have no gsis_id AND no
                # roster-snapshot match (same real-data quirk as
                # roster_snapshot_builder) -- derive a stable id from the
                # same real fields rather than dropping a real player.
                normalized["player_id"] = fallback_key
                normalized["source_player_id"] = normalized["source_player_id"] or fallback_key
        elif normalized.get("player_id"):
            roster_match = roster_index.get(f"id:{normalized['player_id']}")
            if roster_match and not normalized.get("player_name"):
                normalized["player_name"] = roster_match.get("player_name") or normalized["player_name"]
            if roster_match and not normalized.get("team"):
                normalized["team"] = roster_match.get("team") or normalized["team"]
            if roster_match and not normalized.get("position"):
                normalized["position"] = roster_match.get("position") or normalized["position"]
        normalized_rows.append(normalized)

    grouped: dict[str, dict[str, str]] = {}
    for row in normalized_rows:
        if not row.get("player_id"):
            continue
        if not row.get("player_name") or not row.get("team") or not row.get("position") or not row.get("depth_rank") or not row.get("role"):
            continue
        group_key = _build_row_key(row)
        current = grouped.get(group_key)
        if current is None or _depth_sort_key(row) >= _depth_sort_key(current):
            grouped[group_key] = row

    deduped = list(grouped.values())
    deduped.sort(key=lambda row: (row.get("team") or "", row.get("position") or "", row.get("depth_rank") or "", row.get("player_name") or ""))
    return tuple(deduped)


def validate_depth_snapshot_rows(rows: list[dict[str, str]] | tuple[dict[str, str], ...]) -> list[str]:
    issues: list[str] = []
    required_fields = ("player_id", "player_name", "team", "position", "depth_rank", "role")
    seen_team_position_depth: Counter[tuple[str, str, str]] = Counter()
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
        player_name = _safe_text(row.get("player_name"))
        team = _safe_text(row.get("team")).upper()
        position = _safe_text(row.get("position"))
        depth_rank = _safe_text(row.get("depth_rank"))
        role = _safe_text(row.get("role"))
        if player_id:
            seen_player_ids[player_id] += 1
        if team not in valid_teams:
            issues.append(f"row {index} has invalid team {team}")
        if depth_rank and not depth_rank.isdigit():
            issues.append(f"row {index} has invalid depth_rank {depth_rank}")
        if role and not player_name:
            issues.append(f"row {index} has invalid role context")
        if player_id and team and position and depth_rank:
            seen_team_position_depth[(team, position, depth_rank)] += 1

        starter_flag = _safe_text(row.get("starter_flag")).lower()
        backup_flag = _safe_text(row.get("backup_flag")).lower()
        if starter_flag in {"true", "1", "yes"} and backup_flag in {"true", "1", "yes"}:
            issues.append(f"row {index} has conflicting starter/backup flags")
        if starter_flag in {"true", "1", "yes"} and role and "starter" not in role.lower():
            issues.append(f"row {index} has starter flag inconsistent with role")
        if backup_flag in {"true", "1", "yes"} and role and "backup" not in role.lower() and "reserve" not in role.lower():
            issues.append(f"row {index} has backup flag inconsistent with role")

    duplicate_ids = [player_id for player_id, count in seen_player_ids.items() if count > 1]
    for player_id in duplicate_ids:
        issues.append(f"duplicate player_id {player_id}")

    duplicate_team_position_depth = [key for key, count in seen_team_position_depth.items() if count > 1]
    for team, position, depth_rank in duplicate_team_position_depth:
        issues.append(f"duplicate team/position/depth_rank {team}/{position}/{depth_rank}")
    return issues


def write_depth_snapshot_csv(
    *,
    season: int = 2026,
    snapshot_date: str | None = None,
    output_path: Path | None = None,
    publish: bool = False,
    roster_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    depth_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    source_file: str = "authoritative_depth_feed.csv",
) -> DepthChartSnapshotBuildResult:
    snapshot_day = snapshot_date or date_type.today().isoformat()
    rows = build_depth_snapshot_rows(
        season=season,
        snapshot_date=snapshot_day,
        roster_rows=roster_rows,
        depth_rows=depth_rows,
        source_file=source_file,
    )
    issues = validate_depth_snapshot_rows(rows)
    if issues:
        raise ValueError("Depth snapshot validation failed: " + "; ".join(issues))

    path = output_path or depth_chart_snapshot_output_path(season=season, snapshot_date=None, publish=publish)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DEPTH_SNAPSHOT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in DEPTH_SNAPSHOT_COLUMNS})

    return DepthChartSnapshotBuildResult(
        rows=rows,
        output_path=path,
        roster_source_file=str(default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "rosters" / f"roster_{season}_snapshot.csv"),
        depth_source_file=source_file,
        snapshot_date=snapshot_day,
    )