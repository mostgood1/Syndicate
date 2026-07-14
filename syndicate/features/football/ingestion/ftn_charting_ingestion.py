from __future__ import annotations

import csv
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from syndicate.features.football.ingestion.source_fetchers import ensure_directory
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.nfl.sources import default_nfl_source_root


def ftn_charting_tracking_root() -> Path:
    return default_nfl_source_root() / "tracking" / "ftn_charting"


def ftn_charting_tracking_roots() -> tuple[Path, ...]:
    roots = []
    for base_root in preferred_artifact_roots(__file__, env_var="SYNDICATE_NFL_SOURCE_ROOT", local_dir_name="nfl_source"):
        candidate = base_root / "tracking" / "ftn_charting"
        if candidate not in roots:
            roots.append(candidate)
    return tuple(roots)


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "records", "games", "plays", "players", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, dict)]
        return [dict(payload)]
    return []


def _load_rows_from_path(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        rows: list[dict[str, Any]] = []
        for child in sorted(path.iterdir()):
            rows.extend(_load_rows_from_path(child))
        return rows
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        return _load_csv_rows(path)
    if path.suffix.lower() == ".json":
        return _load_json_rows(path)
    return []


def _download_text(url: str) -> str | None:
    try:
        with urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return None


@lru_cache(maxsize=16)
def load_ftn_charting_rows(source_root: str | Path | None = None) -> tuple[dict[str, Any], ...]:
    if source_root is not None:
        rows = _load_rows_from_path(Path(source_root))
        return tuple(row for row in rows if isinstance(row, dict))

    rows: list[dict[str, Any]] = []
    for root in ftn_charting_tracking_roots():
        rows.extend(_load_rows_from_path(root))
        if rows:
            break
    if not rows:
        for season in range(2022, 2027):
            url = f"https://github.com/nflverse/nflverse-data/releases/download/ftn_charting/ftn_charting_{season}.csv"
            target = ensure_directory(ftn_charting_tracking_root() / str(season)) / f"ftn_charting_{season}.csv"
            if not target.exists():
                text = _download_text(url)
                if text is not None:
                    target.write_text(text, encoding="utf-8")
            rows.extend(_load_rows_from_path(target))
            if rows:
                break
    return tuple(row for row in rows if isinstance(row, dict))


def _player_key(row: dict[str, Any]) -> str:
    return _safe_text(
        row.get("player_id")
        or row.get("playerId")
        or row.get("nfl_player_id")
        or row.get("player")
        or row.get("player_name")
        or row.get("name")
        or ""
    ).upper()


def _team_key(row: dict[str, Any]) -> str:
    return _safe_text(row.get("team") or row.get("team_abbr") or row.get("posteam") or "").upper()


def _season_week_key(row: dict[str, Any]) -> tuple[int | None, int | None]:
    season = _safe_float(row.get("season"))
    week = _safe_float(row.get("week"))
    return (int(season) if season is not None else None, int(week) if week is not None else None)


def _share(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def _charting_row_usage(row: dict[str, Any]) -> dict[str, Any]:
    snap_pct = _safe_float(row.get("snap_pct") or row.get("snap_share") or row.get("snap_rate"))
    target_pct = _safe_float(row.get("target_pct") or row.get("target_share") or row.get("targets_share"))
    route_pct = _safe_float(row.get("route_pct") or row.get("route_share") or row.get("route_participation"))
    carry_pct = _safe_float(row.get("carry_share") or row.get("rush_share") or row.get("rush_pct"))
    goal_line_pct = _safe_float(row.get("goal_line_pct") or row.get("goal_line_share") or row.get("gl_share"))
    red_zone_pct = _safe_float(row.get("red_zone_pct") or row.get("red_zone_share") or row.get("rz_share"))
    air_yards_pct = _safe_float(row.get("air_yards_pct") or row.get("air_yard_share") or row.get("air_yards_share"))
    route_runs = _safe_float(row.get("routes") or row.get("route_runs"))
    targets = _safe_float(row.get("targets"))
    snaps = _safe_float(row.get("snaps") or row.get("plays"))
    return {
        "snap_pct": snap_pct,
        "target_pct": target_pct,
        "route_pct": route_pct,
        "carry_share": carry_pct,
        "goal_line_pct": goal_line_pct,
        "red_zone_pct": red_zone_pct,
        "air_yards_pct": air_yards_pct,
        "routes": route_runs,
        "targets": targets,
        "snaps": snaps,
    }


def build_ftn_player_usage(
    player: dict[str, Any],
    *,
    season: int | None = None,
    week: int | None = None,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    rows = list(load_ftn_charting_rows(source_root))
    if not rows:
        return {}

    player_id = _player_key(player)
    team = _safe_text(player.get("team") or player.get("team_abbr") or "").upper()
    position = _safe_text(player.get("position") or "").upper()
    name = _safe_text(player.get("player_name") or player.get("name") or player.get("player") or "").strip()

    matched_rows: list[dict[str, Any]] = []
    for row in rows:
        row_key = _player_key(row)
        row_team = _team_key(row)
        row_season, row_week = _season_week_key(row)
        if player_id and row_key and row_key != player_id and row_key != name.upper():
            continue
        if team and row_team and row_team != team:
            continue
        if season is not None and row_season is not None and int(row_season) != int(season):
            continue
        if week is not None and row_week is not None and int(row_week) != int(week):
            continue
        matched_rows.append(row)

    if not matched_rows:
        return {}

    usage_samples = [_charting_row_usage(row) for row in matched_rows]
    snap_values = [value for value in (_safe_float(item.get("snap_pct")) for item in usage_samples) if value is not None]
    target_values = [value for value in (_safe_float(item.get("target_pct")) for item in usage_samples) if value is not None]
    route_values = [value for value in (_safe_float(item.get("route_pct")) for item in usage_samples) if value is not None]
    carry_values = [value for value in (_safe_float(item.get("carry_share")) for item in usage_samples) if value is not None]
    goal_line_values = [value for value in (_safe_float(item.get("goal_line_pct")) for item in usage_samples) if value is not None]
    red_zone_values = [value for value in (_safe_float(item.get("red_zone_pct")) for item in usage_samples) if value is not None]
    air_yards_values = [value for value in (_safe_float(item.get("air_yards_pct")) for item in usage_samples) if value is not None]

    return {
        "source": "ftn_charting",
        "source_root": str(Path(source_root) if source_root is not None else ftn_charting_tracking_root()),
        "player_id": player_id or _safe_text(player.get("player_id") or player.get("id") or ""),
        "player_name": name,
        "team": team,
        "position": position,
        "season": season,
        "week": week,
        "row_count": len(matched_rows),
        "snap_share": _share(snap_values),
        "target_share": _share(target_values),
        "route_participation": _share(route_values),
        "carry_share": _share(carry_values),
        "goal_line_share": _share(goal_line_values),
        "red_zone_share": _share(red_zone_values),
        "air_yard_share": _share(air_yards_values),
        "snap_pct": _share(snap_values),
        "target_pct": _share(target_values),
        "route_pct": _share(route_values),
        "rush_pct": _share(carry_values),
        "goal_line_pct": _share(goal_line_values),
        "red_zone_pct": _share(red_zone_values),
        "air_yards_pct": _share(air_yards_values),
        "usage_metrics": {
            "snap_share": _share(snap_values),
            "target_share": _share(target_values),
            "route_participation": _share(route_values),
            "carry_share": _share(carry_values),
            "goal_line_share": _share(goal_line_values),
            "red_zone_share": _share(red_zone_values),
            "air_yard_share": _share(air_yards_values),
        },
        "metric_samples": usage_samples,
    }