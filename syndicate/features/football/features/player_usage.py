from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from typing import Any

from syndicate.features.football.contracts import FootballPlayerFeatures
from syndicate.features.football.ingestion.ftn_charting_ingestion import build_ftn_player_usage
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_player_stats
from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata


NFLVERSE_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _first_float(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _safe_float(payload.get(key))
        if value is not None:
            return value
    return None


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _normalize_player_name(value: Any) -> str:
    text = _safe_text(value).upper()
    return "".join(ch for ch in text if ch.isalnum())


def _download_csv(url: str) -> list[dict[str, Any]]:
    try:
        with urlopen(url, timeout=30) as response:
            text = response.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError, OSError):
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


@lru_cache(maxsize=16)
def _load_snap_counts(season: int) -> tuple[dict[str, Any], ...]:
    url = f"{NFLVERSE_BASE_URL}/snap_counts/snap_counts_{season}.csv"
    return tuple(_download_csv(url))


def _player_key(player: dict[str, Any]) -> str:
    return _safe_text(
        player.get("player_id")
        or player.get("id")
        or player.get("player_name")
        or player.get("name")
        or player.get("player")
        or ""
    ).upper()


def _player_aliases(player: dict[str, Any]) -> set[str]:
    aliases = {
        _safe_text(player.get("player_id") or player.get("id") or "").upper(),
        _safe_text(player.get("player_name") or player.get("name") or player.get("player") or "").upper(),
    }
    aliases.add(_safe_text(player.get("player_display_name") or "").upper())
    aliases.add(_normalize_player_name(player.get("player_name") or player.get("name") or player.get("player") or ""))
    aliases.add(_normalize_player_name(player.get("player_display_name") or ""))
    aliases.discard("")
    return aliases


def _match_row(rows: list[dict[str, Any]], player: dict[str, Any], *, season: int | None, week: int | None) -> dict[str, Any] | None:
    player_aliases = _player_aliases(player)
    team = canonical_team_abbr(player.get("team") or player.get("team_abbr") or "")
    position = _safe_text(player.get("position") or "").upper()
    for row in rows:
        row_player = _safe_text(row.get("player_id") or row.get("player_name") or row.get("player_display_name") or row.get("player") or "").upper()
        row_display_name = _safe_text(row.get("player_display_name") or row.get("player") or "").upper()
        row_normalized_name = _normalize_player_name(row.get("player_display_name") or row.get("player_name") or row.get("player") or "")
        row_team = canonical_team_abbr(row.get("team") or row.get("team_abbr") or "")
        row_position = _safe_text(row.get("position") or row.get("position_group") or "").upper()
        if player_aliases and row_player and row_player not in player_aliases and row_display_name not in player_aliases and row_normalized_name not in player_aliases:
            continue
        if team and row_team and team != row_team:
            continue
        if position and row_position and position != row_position and not row_position.startswith(position[:1]):
            continue
        if season is not None and _safe_text(row.get("season")) and int(float(row.get("season"))) != int(season):
            continue
        if week is not None and _safe_text(row.get("week")) and int(float(row.get("week"))) != int(week):
            continue
        return row
    return None


def _usage_aliases(player: dict[str, Any]) -> dict[str, Any]:
    usage_metrics = dict(player.get("usage_metrics") or {})
    snap_share = _first_float(usage_metrics, ["snap_share", "snap_pct", "snap_rate", "snaps_share"])
    target_share = _first_float(usage_metrics, ["target_share", "targets_share", "target_pct"])
    route_participation = _first_float(usage_metrics, ["route_participation", "route_pct", "routes_share"])
    carry_share = _first_float(usage_metrics, ["carry_share", "rush_share", "rush_pct"])
    goal_line_share = _first_float(usage_metrics, ["goal_line_share", "gl_share", "goal_line_pct"])
    red_zone_share = _first_float(usage_metrics, ["red_zone_share", "rz_share", "red_zone_pct"])
    air_yard_share = _first_float(usage_metrics, ["air_yard_share", "air_yards_share", "air_yards_pct"])

    usage_metrics.setdefault("snap_share", snap_share)
    usage_metrics.setdefault("target_share", target_share)
    usage_metrics.setdefault("route_participation", route_participation)
    usage_metrics.setdefault("carry_share", carry_share)
    usage_metrics.setdefault("goal_line_share", goal_line_share)
    usage_metrics.setdefault("red_zone_share", red_zone_share)
    usage_metrics.setdefault("air_yard_share", air_yard_share)

    return {
        "player_id": str(player.get("player_id") or player.get("id") or "").strip(),
        "player_name": str(player.get("player_name") or player.get("name") or "").strip(),
        "team": str(player.get("team") or "").strip(),
        "position": str(player.get("position") or "").strip(),
        "usage_metrics": usage_metrics,
        "market_features": dict(player.get("market_features") or {}),
        "snap_share": snap_share,
        "target_share": target_share,
        "route_participation": route_participation,
        "carry_share": carry_share,
        "goal_line_share": goal_line_share,
        "red_zone_share": red_zone_share,
        "air_yard_share": air_yard_share,
    }


def build_player_usage(
    player: dict[str, Any],
    *,
    sport: str,
    date: str,
    season: int | None = None,
    week: int | None = None,
) -> dict[str, Any]:
    aliases = _usage_aliases(player)
    source = "manual"
    source_root = None
    if sport.lower() == "nfl":
        ftn_usage = build_ftn_player_usage(player, season=season, week=week)
        stats_rows = list(load_nflverse_player_stats(season or 2025)) if season is not None else []
        matched_stats = _match_row(stats_rows, player, season=season, week=week) if stats_rows else None
        snap_rows = list(_load_snap_counts(season or 2025)) if season is not None else []
        matched_snaps = _match_row(snap_rows, player, season=season, week=week) if snap_rows else None
        if ftn_usage:
            source = "ftn_charting"
            source_root = ftn_usage.get("source_root")
            aliases["snap_share"] = ftn_usage.get("snap_share") if ftn_usage.get("snap_share") is not None else aliases["snap_share"]
            aliases["target_share"] = ftn_usage.get("target_share") if ftn_usage.get("target_share") is not None else aliases["target_share"]
            aliases["route_participation"] = (
                ftn_usage.get("route_participation")
                if ftn_usage.get("route_participation") is not None
                else aliases["route_participation"]
            )
            aliases["carry_share"] = ftn_usage.get("carry_share") if ftn_usage.get("carry_share") is not None else aliases["carry_share"]
            aliases["goal_line_share"] = ftn_usage.get("goal_line_share") if ftn_usage.get("goal_line_share") is not None else aliases["goal_line_share"]
            aliases["red_zone_share"] = ftn_usage.get("red_zone_share") if ftn_usage.get("red_zone_share") is not None else aliases["red_zone_share"]
            aliases["air_yard_share"] = ftn_usage.get("air_yard_share") if ftn_usage.get("air_yard_share") is not None else aliases["air_yard_share"]
            aliases["usage_metrics"] = {
                **aliases["usage_metrics"],
                "snap_share": aliases["snap_share"],
                "target_share": aliases["target_share"],
                "route_participation": aliases["route_participation"],
                "carry_share": aliases["carry_share"],
                "goal_line_share": aliases["goal_line_share"],
                "red_zone_share": aliases["red_zone_share"],
                "air_yard_share": aliases["air_yard_share"],
            }
        elif matched_stats or matched_snaps:
            source = "nflverse"
            source_root = "https://github.com/nflverse/nflverse-data/releases/download"
            if matched_snaps:
                aliases["snap_share"] = _first_float(matched_snaps, ["offense_pct", "offense_snaps", "snap_pct", "snap_share"])
            if matched_stats:
                aliases["target_share"] = _first_float(matched_stats, ["target_share", "targets_share", "target_pct"])
                aliases["air_yard_share"] = _first_float(matched_stats, ["air_yards_share", "air_yards_pct"])
                aliases["route_participation"] = _first_float(matched_stats, ["route_participation", "route_pct", "routes_share", "wopr"])
                aliases["carry_share"] = _first_float(matched_stats, ["carries", "carry_share", "rush_pct"])
                aliases["goal_line_share"] = _first_float(matched_stats, ["goal_line_share", "goal_line_pct"])
                aliases["red_zone_share"] = _first_float(matched_stats, ["red_zone_share", "red_zone_pct"])
                aliases["usage_metrics"] = {
                    **aliases["usage_metrics"],
                    "snap_share": aliases["snap_share"],
                    "target_share": aliases["target_share"],
                    "route_participation": aliases["route_participation"],
                    "carry_share": aliases["carry_share"],
                    "goal_line_share": aliases["goal_line_share"],
                    "red_zone_share": aliases["red_zone_share"],
                    "air_yard_share": aliases["air_yard_share"],
                }
    return {
        "player_id": aliases["player_id"],
        "player_name": aliases["player_name"],
        "team": canonical_team_abbr(aliases["team"]),
        "position": aliases["position"],
        "usage_metrics": aliases["usage_metrics"],
        "market_features": aliases["market_features"],
        "snap_share": aliases["snap_share"],
        "target_share": aliases["target_share"],
        "route_participation": aliases["route_participation"],
        "carry_share": aliases["carry_share"],
        "goal_line_share": aliases["goal_line_share"],
        "red_zone_share": aliases["red_zone_share"],
        "air_yard_share": aliases["air_yard_share"],
        "snap_pct": aliases["snap_share"],
        "target_pct": aliases["target_share"],
        "route_pct": aliases["route_participation"],
        "rush_pct": aliases["carry_share"],
        "goal_line_pct": aliases["goal_line_share"],
        "red_zone_pct": aliases["red_zone_share"],
        "air_yards_pct": aliases["air_yard_share"],
        "targets_share": aliases["target_share"],
        "routes_share": aliases["route_participation"],
        "snaps_share": aliases["snap_share"],
        "carry_share_pct": aliases["carry_share"],
        "source": source,
        "source_root": source_root,
        "sport": sport,
        "date": date,
    }


def to_football_player_features(
    player: dict[str, Any],
    *,
    sport: str,
    date: str,
    season: int | None = None,
    week: int | None = None,
) -> FootballPlayerFeatures:
    usage = build_player_usage(player, sport=sport, date=date, season=season, week=week)
    return FootballPlayerFeatures(
        sport=sport,
        date=date,
        player_id=usage["player_id"],
        player_name=usage["player_name"],
        team=usage["team"],
        position=usage["position"],
        usage_metrics=usage["usage_metrics"],
        market_features=usage["market_features"],
        adapter_metadata={
            "sport": sport,
            "team_metadata": canonical_team_metadata(usage["team"]),
            "snap_share": usage["snap_share"],
            "target_share": usage["target_share"],
            "route_participation": usage["route_participation"],
            "carry_share": usage["carry_share"],
            "goal_line_share": usage["goal_line_share"],
            "red_zone_share": usage["red_zone_share"],
            "air_yard_share": usage["air_yard_share"],
        },
    )