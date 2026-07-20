"""MLS match/shots-volume truth ingestion via American Soccer Analysis.

football-data.co.uk (the match_history.py source) doesn't cover MLS, so
match results come from ASA's ``games`` endpoint and shot volume from its
``teams/xgoals`` season aggregates. ASA's free tier doesn't expose
per-game shot counts, so each match's shot totals are approximated as the
two teams' season-average shots_for/against per game -- an aggregate proxy,
not a literal per-game count. That's sufficient for the calibration
package's match_totals/shots_per_match/result-rate checks; it is not
precise enough for a possession-level truth snapshot.
"""

from __future__ import annotations

from typing import Any

import requests

from syndicate.features.soccer.ingestion.player_history import _ASA_BASE
from syndicate.features.soccer.ingestion.player_history import _USER_AGENT
from syndicate.features.soccer.ingestion.player_history import fetch_asa_mls_team_directory
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import BenchmarkMatchRecord


def fetch_asa_mls_games(season_name: str | int, *, timeout: int = 30) -> list[dict[str, Any]]:
    response = requests.get(
        f"{_ASA_BASE}/games", params={"season_name": str(season_name)}, timeout=timeout, headers=_USER_AGENT
    )
    response.raise_for_status()
    return response.json()


def fetch_asa_mls_team_shot_rates(season_name: str | int, *, timeout: int = 30) -> dict[str, dict[str, float]]:
    """team_id -> {shots_for_per_match, shots_against_per_match, games}."""
    response = requests.get(
        f"{_ASA_BASE}/teams/xgoals", params={"season_name": str(season_name)}, timeout=timeout, headers=_USER_AGENT
    )
    response.raise_for_status()
    rates: dict[str, dict[str, float]] = {}
    for row in response.json():
        games = float(row.get("count_games") or 0)
        if games <= 0:
            continue
        rates[str(row.get("team_id"))] = {
            "shots_for_per_match": round(float(row.get("shots_for") or 0) / games, 4),
            "shots_against_per_match": round(float(row.get("shots_against") or 0) / games, 4),
            "games": games,
        }
    return rates


def normalize_asa_match_history(
    games: list[dict[str, Any]],
    *,
    season: int,
    team_directory: dict[str, str] | None = None,
    shot_rates: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    directory = team_directory or {}
    rates = shot_rates or {}
    rows: list[dict[str, Any]] = []
    for game in games:
        if str(game.get("status") or "").lower() != "fulltime":
            continue
        home_id = str(game.get("home_team_id") or "")
        away_id = str(game.get("away_team_id") or "")
        home_goals = game.get("home_score")
        away_goals = game.get("away_score")
        if home_goals is None or away_goals is None:
            continue
        home_shot_rate = rates.get(home_id, {})
        away_shot_rate = rates.get(away_id, {})
        rows.append(
            {
                "league": "mls",
                "season": season,
                "match_id": str(game.get("game_id") or ""),
                "date": str(game.get("date_time_utc") or ""),
                "home_team": directory.get(home_id, home_id),
                "away_team": directory.get(away_id, away_id),
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "home_shots_approx": home_shot_rate.get("shots_for_per_match"),
                "away_shots_approx": away_shot_rate.get("shots_for_per_match"),
                "knockout_game": bool(game.get("knockout_game")),
            }
        )
    return rows


def to_benchmark_match_records(rows: list[dict[str, Any]]) -> tuple[BenchmarkMatchRecord, ...]:
    records: list[BenchmarkMatchRecord] = []
    for row in rows:
        home_shots = row.get("home_shots_approx")
        away_shots = row.get("away_shots_approx")
        shots = int(round((home_shots or 0) + (away_shots or 0))) if (home_shots or away_shots) else 0
        records.append(
            BenchmarkMatchRecord(
                match_id=str(row.get("match_id") or ""),
                home_team=str(row.get("home_team") or ""),
                away_team=str(row.get("away_team") or ""),
                season=row.get("season"),
                home_goals=int(row.get("home_goals") or 0),
                away_goals=int(row.get("away_goals") or 0),
                half_home_goals=(0, int(row.get("home_goals") or 0)),
                half_away_goals=(0, int(row.get("away_goals") or 0)),
                possessions=0,
                shots=shots,
                shots_on_target=0,
                corners=0,
                metadata={
                    "league": "mls",
                    "date": row.get("date"),
                    "shots_are_season_average_proxy": True,
                },
            )
        )
    return tuple(records)


def fetch_mls_truth_snapshot_rows(season_name: str | int) -> list[dict[str, Any]]:
    """Convenience: games + team shot rates + directory -> normalized rows."""
    games = fetch_asa_mls_games(season_name)
    shot_rates = fetch_asa_mls_team_shot_rates(season_name)
    directory = fetch_asa_mls_team_directory()
    return normalize_asa_match_history(games, season=int(season_name), team_directory=directory, shot_rates=shot_rates)


__all__ = [
    "fetch_asa_mls_games",
    "fetch_asa_mls_team_shot_rates",
    "fetch_mls_truth_snapshot_rows",
    "normalize_asa_match_history",
    "to_benchmark_match_records",
]
