from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

from syndicate.features.football.ingestion.source_fetchers import download_to_cache
from syndicate.features.football.ingestion.source_fetchers import ensure_directory
from syndicate.features.football.ingestion.source_fetchers import load_csv_rows
from syndicate.features.football.ingestion.source_fetchers import load_tabular_rows
from syndicate.features.football.ingestion.source_fetchers import tracking_root
from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata
from syndicate.features.shared.source_roots import preferred_artifact_roots


NFLVERSE_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"


def nflverse_tracking_root() -> Path:
    return tracking_root("nfl_source") / "nflverse"


def nflverse_tracking_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for base_root in preferred_artifact_roots(__file__, env_var="SYNDICATE_NFL_SOURCE_ROOT", local_dir_name="nfl_source"):
        candidate = base_root / "tracking" / "nflverse"
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


def _download_csv_rows(url: str, target_path: Path) -> list[dict[str, Any]]:
    if not target_path.exists():
        downloaded = download_to_cache(url, target_path)
        if downloaded is None:
            return []
    return load_csv_rows(target_path)


def _release_cache_path(kind: str, season: int) -> Path:
    return ensure_directory(nflverse_tracking_root() / kind) / f"{kind}_{season}.csv"


def _pbp_rows(season: int) -> list[dict[str, Any]]:
    path = _release_cache_path("pbp", season)
    url = f"{NFLVERSE_BASE_URL}/pbp/play_by_play_{season}.csv"
    return _download_csv_rows(url, path)


def _team_stats_rows(season: int) -> list[dict[str, Any]]:
    path = _release_cache_path("team_stats", season)
    url = f"{NFLVERSE_BASE_URL}/stats_team/stats_team_week_{season}.csv"
    return _download_csv_rows(url, path)


def _player_stats_rows(season: int) -> list[dict[str, Any]]:
    path = _release_cache_path("player_stats", season)
    url = f"{NFLVERSE_BASE_URL}/stats_player/stats_player_week_{season}.csv"
    return _download_csv_rows(url, path)


def _ftn_charting_rows(season: int) -> list[dict[str, Any]]:
    path = _release_cache_path("ftn_charting", season)
    url = f"{NFLVERSE_BASE_URL}/ftn_charting/ftn_charting_{season}.csv"
    return _download_csv_rows(url, path)


def _roster_rows(season: int) -> list[dict[str, Any]]:
    """Real nflverse full-season rosters (team/position/depth per player)
    -- distinct from _player_stats_rows above, which is per-game weekly
    STATS (only populated once games are played, useless pre-season).
    This is what an actual roster/depth-chart concept needs: who's on the
    team right now, regardless of whether they've played yet."""
    path = _release_cache_path("roster", season)
    url = f"{NFLVERSE_BASE_URL}/rosters/roster_{season}.csv"
    return _download_csv_rows(url, path)


def _depth_chart_rows(season: int) -> list[dict[str, Any]]:
    """Real nflverse depth charts (per-team position-slot rank per player)
    -- confirmed live: real 2026 data already posted (dated 2026-08-01,
    today), unlike CFBD's NCAAF roster which has nothing for 2026 yet.
    No fetcher existed for this anywhere in the repo before; the previous
    depth-chart builder had zero real-source wiring at all."""
    path = _release_cache_path("depth_charts", season)
    url = f"{NFLVERSE_BASE_URL}/depth_charts/depth_charts_{season}.csv"
    return _download_csv_rows(url, path)


def _injuries_rows(season: int) -> list[dict[str, Any]]:
    """Real nflverse weekly injury reports (report/practice status per
    player per week) -- no equivalent exists anywhere else in this repo
    for NFL, and CFBD (the NCAAF data source) has no injuries endpoint at
    all, so this is NFL-only."""
    path = _release_cache_path("injuries", season)
    url = f"{NFLVERSE_BASE_URL}/injuries/injuries_{season}.csv"
    return _download_csv_rows(url, path)


def load_nflverse_team_stats(season: int) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in _team_stats_rows(season) if isinstance(row, dict))


def load_nflverse_player_stats(season: int) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in _player_stats_rows(season) if isinstance(row, dict))


def load_nflverse_ftn_charting_rows(season: int) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in _ftn_charting_rows(season) if isinstance(row, dict))


def load_nflverse_roster(season: int) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in _roster_rows(season) if isinstance(row, dict))


def load_nflverse_depth_chart(season: int) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in _depth_chart_rows(season) if isinstance(row, dict))


def load_nflverse_injuries(season: int) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in _injuries_rows(season) if isinstance(row, dict))


@lru_cache(maxsize=16)
def load_nflverse_rows(source_root: str | Path | None = None, *, season: int | None = None) -> tuple[dict[str, Any], ...]:
    if source_root is not None:
        rows = load_tabular_rows(Path(source_root))
        return tuple(row for row in rows if isinstance(row, dict))
    if season is None:
        return ()
    return tuple(row for row in _pbp_rows(int(season)) if isinstance(row, dict))


def _match_game_rows(rows: list[dict[str, Any]], *, home_team: str, away_team: str, season: int | None = None, week: int | None = None) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    home = canonical_team_abbr(home_team)
    away = canonical_team_abbr(away_team)
    for row in rows:
        if season is not None:
            row_season = _safe_float(row.get("season"))
            if row_season is not None and int(row_season) != int(season):
                continue
        if week is not None:
            row_week = _safe_float(row.get("week"))
            if row_week is not None and int(row_week) != int(week):
                continue
        row_home = canonical_team_abbr(row.get("home_team") or "")
        row_away = canonical_team_abbr(row.get("away_team") or "")
        if row_home == home and row_away == away:
            matched.append(row)
        elif row_home == away and row_away == home:
            matched.append(row)
    return matched


def _team_metrics_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    epa_values = [_safe_float(row.get("epa")) for row in rows]
    success_values = [_safe_float(row.get("success")) for row in rows]
    proe_values = [
        _safe_float(
            row.get("proe")
            or row.get("pass_rate_over_expected")
            or row.get("pass_rate_over_expectation")
            or row.get("pass_rate_over_expected")
        )
        for row in rows
    ]
    play_types = [_safe_text(row.get("play_type") or row.get("type") or "") for row in rows]
    pass_count = sum(1 for value in play_types if value.lower() == "pass")
    rush_count = sum(1 for value in play_types if value.lower() == "rush")
    total = len(rows)
    offensive_epa = round(mean([value for value in epa_values if value is not None]), 4) if any(value is not None for value in epa_values) else None
    success_rate = round(mean([value for value in success_values if value is not None]), 4) if any(value is not None for value in success_values) else None
    proe = round(mean([value for value in proe_values if value is not None]), 4) if any(value is not None for value in proe_values) else None
    return {
        "offensive_epa": offensive_epa,
        "success_rate": success_rate,
        "proe": proe,
        "pass_rate": round(pass_count / total, 4) if total else None,
        "rush_rate": round(rush_count / total, 4) if total else None,
    }


def _team_stats_metric(rows: list[dict[str, Any]], team: str, keys: list[str]) -> float | None:
    team = canonical_team_abbr(team)
    for row in rows:
        row_team = canonical_team_abbr(row.get("team") or row.get("team_abbr") or row.get("team_id") or row.get("posteam") or "")
        if row_team != team:
            continue
        for key in keys:
            value = _safe_float(row.get(key))
            if value is not None:
                return value
    return None


def build_nflverse_game_metrics(
    game: dict[str, Any],
    *,
    season: int | None = None,
    week: int | None = None,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    if season is None:
        return {}
    rows = list(load_nflverse_rows(source_root, season=season))
    if not rows:
        return {}

    home_team = canonical_team_abbr((game.get("home") or {}).get("abbr") or game.get("home_team") or "")
    away_team = canonical_team_abbr((game.get("away") or {}).get("abbr") or game.get("away_team") or "")
    game_rows = _match_game_rows(rows, home_team=home_team, away_team=away_team, season=season, week=week)
    if not game_rows:
        return {}

    home_rows = [row for row in game_rows if _safe_text(row.get("posteam") or "").upper() == home_team.upper()]
    away_rows = [row for row in game_rows if _safe_text(row.get("posteam") or "").upper() == away_team.upper()]
    home_offense = _team_metrics_from_rows(home_rows or game_rows)
    away_offense = _team_metrics_from_rows(away_rows or game_rows)
    team_stats_rows = list(load_nflverse_team_stats(int(season)))
    home_proe = _team_stats_metric(team_stats_rows, home_team, ["pass_rate_over_expected", "proe", "pass_rate_over_expectation"])
    away_proe = _team_stats_metric(team_stats_rows, away_team, ["pass_rate_over_expected", "proe", "pass_rate_over_expectation"])
    home_proe = home_proe if home_proe is not None else _team_stats_metric(team_stats_rows, home_team, ["passing_cpoe"])
    away_proe = away_proe if away_proe is not None else _team_stats_metric(team_stats_rows, away_team, ["passing_cpoe"])

    return {
        "source": "nflverse_play_by_play",
        "source_root": str(Path(source_root) if source_root is not None else nflverse_tracking_root()),
        "home_team": home_team,
        "away_team": away_team,
        "season": season,
        "week": week,
        "row_count": len(game_rows),
        "home_team_metadata": canonical_team_metadata(home_team),
        "away_team_metadata": canonical_team_metadata(away_team),
        "epa_per_play": home_offense.get("offensive_epa"),
        "success_rate": home_offense.get("success_rate"),
        "proe": home_proe if home_proe is not None else home_offense.get("proe"),
        "home_offensive_epa": home_offense.get("offensive_epa"),
        "away_offensive_epa": away_offense.get("offensive_epa"),
        "home_defensive_epa": away_offense.get("offensive_epa"),
        "away_defensive_epa": home_offense.get("offensive_epa"),
        "home_success_rate": home_offense.get("success_rate"),
        "away_success_rate": away_offense.get("success_rate"),
        "home_pass_rate": home_offense.get("pass_rate"),
        "away_pass_rate": away_offense.get("pass_rate"),
        "home_rush_rate": home_offense.get("rush_rate"),
        "away_rush_rate": away_offense.get("rush_rate"),
        "home_proe": home_proe,
        "away_proe": away_proe,
    }
