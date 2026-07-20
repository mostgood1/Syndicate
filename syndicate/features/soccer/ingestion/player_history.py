"""Player-history ingestion for SoccerSim usage profiles.

Two free sources cover the engine's leagues:

- **Understat** (big-five European leagues): season player tables with
  minutes, games, shots, goals, xG, xA, key passes, position — embedded as
  escaped JSON in the league page. Seasons are keyed by start year
  (2025 = the 2025-26 season).
- **American Soccer Analysis** (MLS): public API with per-player xgoals
  tables (minutes, shots, xG, xA) joined against the player directory.

Both normalize to the per-90 row shape that
``soccersim.player_props.build_usage_profiles`` consumes:
``player_id, player_name, team, position, minutes, games, shots_per90,
xg_per90, xa_per90, expected_minutes_share, is_goalkeeper``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

UNDERSTAT_LEAGUES: dict[str, str] = {
    "epl": "EPL",
    "la_liga": "La_liga",
    "bundesliga": "Bundesliga",
    "serie_a": "Serie_A",
    "ligue_1": "Ligue_1",
}

_ASA_BASE = "https://app.americansocceranalysis.com/api/v1/mls"

_USER_AGENT = {"User-Agent": "Mozilla/5.0 (SyndicateSoccerSim)"}
_UNDERSTAT_XHR_HEADERS = {**_USER_AGENT, "X-Requested-With": "XMLHttpRequest"}


def fetch_understat_league_data(league: str, season_start_year: int, *, timeout: int = 30) -> dict[str, Any]:
    """Fetch Understat's league bundle: ``players``, ``teams`` (with
    per-match history: xG, xGA, PPDA, deep entries), and ``dates``."""
    league_key = UNDERSTAT_LEAGUES[str(league).strip().lower()]
    url = f"https://understat.com/getLeagueData/{league_key}/{int(season_start_year)}"
    response = requests.get(url, timeout=timeout, headers=_UNDERSTAT_XHR_HEADERS)
    response.raise_for_status()
    return response.json()


def fetch_understat_players(league: str, season_start_year: int, *, timeout: int = 30) -> list[dict[str, Any]]:
    try:
        league_data = fetch_understat_league_data(league, season_start_year, timeout=timeout)
        players = league_data.get("players")
        if isinstance(players, list) and players:
            return players
    except Exception:
        pass
    # Fallback: legacy embedded-JSON page scrape.
    league_key = UNDERSTAT_LEAGUES[str(league).strip().lower()]
    url = f"https://understat.com/league/{league_key}/{int(season_start_year)}"
    response = requests.get(url, timeout=timeout, headers=_USER_AGENT)
    response.raise_for_status()
    match = re.search(r"var playersData\s*=\s*JSON\.parse\('([^']+)'\)", response.text)
    if not match:
        raise ValueError(f"playersData not available for {url}")
    decoded = match.group(1).encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    return json.loads(decoded)


def normalize_understat_team_history(
    league_data: dict[str, Any],
    *,
    league: str,
    season: int,
) -> list[dict[str, Any]]:
    """Flatten Understat team blocks into per-team per-match history rows."""
    rows: list[dict[str, Any]] = []
    teams = league_data.get("teams") or {}
    for team in teams.values() if isinstance(teams, dict) else teams:
        title = str(team.get("title") or "").strip()
        for match_index, entry in enumerate(team.get("history") or []):
            rows.append(
                {
                    "league": league,
                    "season": season,
                    "team": title,
                    "match_index": match_index,
                    "date": str(entry.get("date") or ""),
                    "home_away": str(entry.get("h_a") or ""),
                    "xg_for": _safe_number(entry.get("xG")),
                    "xg_against": _safe_number(entry.get("xGA")),
                    "npxg_for": _safe_number(entry.get("npxG")),
                    "npxg_against": _safe_number(entry.get("npxGA")),
                    "ppda": _ppda_value(entry.get("ppda")),
                    "ppda_allowed": _ppda_value(entry.get("ppda_allowed")),
                    "deep_entries": _safe_number(entry.get("deep")),
                    "deep_entries_allowed": _safe_number(entry.get("deep_allowed")),
                    "goals_for": _safe_number(entry.get("scored")),
                    "goals_against": _safe_number(entry.get("missed")),
                    "expected_points": _safe_number(entry.get("xpts")),
                    "points": _safe_number(entry.get("pts")),
                    "result": str(entry.get("result") or ""),
                }
            )
    return rows


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return round(float(value), 4)
    except Exception:
        return None


def _ppda_value(value: Any) -> float | None:
    # Understat PPDA arrives as {"att": passes, "def": defensive_actions}.
    if isinstance(value, dict):
        att = _safe_number(value.get("att"))
        defensive = _safe_number(value.get("def"))
        if att is None or not defensive:
            return None
        return round(att / defensive, 4)
    return _safe_number(value)


def _per90(value: Any, minutes: float) -> float:
    try:
        numeric = float(value or 0.0)
    except Exception:
        numeric = 0.0
    return round(numeric / minutes * 90.0, 4) if minutes > 0 else 0.0


def normalize_understat_players(
    raw_players: list[dict[str, Any]],
    *,
    league: str,
    season: int,
    minimum_minutes: float = 180.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in raw_players:
        try:
            minutes = float(player.get("time") or 0.0)
        except Exception:
            minutes = 0.0
        if minutes < minimum_minutes:
            continue
        try:
            games = int(player.get("games") or 0)
        except Exception:
            games = 0
        position = str(player.get("position") or "")
        rows.append(
            {
                "league": league,
                "season": season,
                "player_id": f"understat_{player.get('id')}",
                "player_name": str(player.get("player_name") or "").strip(),
                "team": str(player.get("team_title") or "").strip(),
                "position": position,
                "minutes": minutes,
                "games": games,
                "shots_per90": _per90(player.get("shots"), minutes),
                "xg_per90": _per90(player.get("xG"), minutes),
                "xa_per90": _per90(player.get("xA"), minutes),
                "goals_per90": _per90(player.get("goals"), minutes),
                "assists_per90": _per90(player.get("assists"), minutes),
                "key_passes_per90": _per90(player.get("key_passes"), minutes),
                "expected_minutes_share": round(min(1.0, minutes / (games * 90.0)), 4) if games > 0 else 0.0,
                "is_goalkeeper": "GK" in position.upper(),
                "source": "understat",
            }
        )
    return rows


def fetch_asa_mls_players(season_name: str | int, *, minimum_minutes: int = 180, timeout: int = 30) -> list[dict[str, Any]]:
    """Fetch MLS player xgoals rows joined with the ASA player directory."""
    xgoals = requests.get(
        f"{_ASA_BASE}/players/xgoals",
        params={"season_name": str(season_name), "minimum_minutes": int(minimum_minutes)},
        timeout=timeout,
        headers=_USER_AGENT,
    )
    xgoals.raise_for_status()
    players = requests.get(f"{_ASA_BASE}/players", timeout=timeout, headers=_USER_AGENT)
    players.raise_for_status()
    directory = {str(row.get("player_id")): row for row in players.json()}
    teams = fetch_asa_mls_team_directory(timeout=timeout)
    merged: list[dict[str, Any]] = []
    for row in xgoals.json():
        info = directory.get(str(row.get("player_id"))) or {}
        team_id = row.get("team_id")
        if isinstance(team_id, list) and team_id:
            team_id = team_id[-1]
        merged.append(
            {
                **row,
                "player_name": info.get("player_name"),
                "position": info.get("primary_general_position"),
                "team_name": teams.get(str(team_id), str(team_id or "")),
            }
        )
    return merged


def fetch_asa_mls_team_directory(*, timeout: int = 30) -> dict[str, str]:
    """ASA team_id -> team name."""
    response = requests.get(f"{_ASA_BASE}/teams", timeout=timeout, headers=_USER_AGENT)
    response.raise_for_status()
    return {str(row.get("team_id")): str(row.get("team_name") or "") for row in response.json()}


def fetch_asa_mls_team_history(season_name: str | int, *, timeout: int = 30) -> list[dict[str, Any]]:
    """MLS per-team season xG rows normalized to the team-history row shape
    ``compute_team_ratings`` consumes (per-match averages, not totals)."""
    response = requests.get(
        f"{_ASA_BASE}/teams/xgoals",
        params={"season_name": str(season_name)},
        timeout=timeout,
        headers=_USER_AGENT,
    )
    response.raise_for_status()
    directory = fetch_asa_mls_team_directory(timeout=timeout)
    rows: list[dict[str, Any]] = []
    for team in response.json():
        games = _safe_number(team.get("count_games")) or 0.0
        if games <= 0:
            continue
        xg_for = _safe_number(team.get("xgoals_for")) or 0.0
        xg_against = _safe_number(team.get("xgoals_against")) or 0.0
        rows.append(
            {
                "league": "mls",
                "season": str(season_name),
                "team": directory.get(str(team.get("team_id")), str(team.get("team_id"))),
                "xg_for": round(xg_for / games, 4),
                "xg_against": round(xg_against / games, 4),
                "ppda": None,
                "games": games,
            }
        )
    return rows


def normalize_asa_players(
    raw_players: list[dict[str, Any]],
    *,
    season: int,
    minimum_minutes: float = 180.0,
) -> list[dict[str, Any]]:
    # ASA rows lack games-played; approximate each player's minutes share
    # as minutes relative to the team's most-used player (a proxy for the
    # team's playable season minutes so far).
    team_max_minutes: dict[str, float] = {}
    for player in raw_players:
        team_key = str(player.get("team_name") or player.get("team_id") or "")
        try:
            minutes = float(player.get("minutes_played") or 0.0)
        except Exception:
            minutes = 0.0
        team_max_minutes[team_key] = max(team_max_minutes.get(team_key, 0.0), minutes)

    rows: list[dict[str, Any]] = []
    for player in raw_players:
        try:
            minutes = float(player.get("minutes_played") or 0.0)
        except Exception:
            minutes = 0.0
        if minutes < minimum_minutes:
            continue
        position = str(player.get("position") or player.get("general_position") or "")
        team = str(player.get("team_name") or "")
        if not team:
            team_id = player.get("team_id")
            if isinstance(team_id, list) and team_id:
                team = str(team_id[-1])
            elif team_id:
                team = str(team_id)
        team_key = str(player.get("team_name") or player.get("team_id") or "")
        max_minutes = team_max_minutes.get(team_key) or 0.0
        minutes_share = round(min(1.0, minutes / max_minutes), 4) if max_minutes > 0 else None
        rows.append(
            {
                "league": "mls",
                "season": season,
                "player_id": f"asa_{player.get('player_id')}",
                "player_name": str(player.get("player_name") or "").strip(),
                "team": team,
                "position": position,
                "minutes": minutes,
                "games": None,
                "shots_per90": _per90(player.get("shots"), minutes),
                "xg_per90": _per90(player.get("xgoals"), minutes),
                "xa_per90": _per90(player.get("xassists"), minutes),
                "goals_per90": _per90(player.get("goals"), minutes),
                "assists_per90": _per90(player.get("primary_assists"), minutes),
                "key_passes_per90": _per90(player.get("key_passes"), minutes),
                "expected_minutes_share": minutes_share,
                "is_goalkeeper": position.upper() in {"GK", "GOALKEEPER"},
                "source": "asa",
            }
        )
    return rows


__all__ = [
    "UNDERSTAT_LEAGUES",
    "fetch_asa_mls_players",
    "fetch_asa_mls_team_directory",
    "fetch_asa_mls_team_history",
    "fetch_understat_league_data",
    "fetch_understat_players",
    "normalize_asa_players",
    "normalize_understat_players",
    "normalize_understat_team_history",
]
