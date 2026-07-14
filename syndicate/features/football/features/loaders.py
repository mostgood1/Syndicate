from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.football.contracts import FootballGameFeatures
from syndicate.features.football.contracts import FootballPlayerFeatures
from syndicate.features.football.contracts import FootballSimulationInput
from syndicate.features.football.features.advanced_metrics import build_advanced_metrics
from syndicate.features.football.ingestion.nflverse_ingestion import build_nflverse_game_metrics
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_rows
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_player_stats
from syndicate.features.football.ingestion.rbsdm_ingestion import build_rbsdm_game_metrics
from syndicate.features.football.features.player_usage import to_football_player_features
from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata
from syndicate.features.football.features.team_metrics import to_football_game_features
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import recommendation_path


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


def _game_market_features(game: dict[str, Any]) -> dict[str, Any]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    return {
        "market": dict(betting),
        "simulation": dict(sim),
        "score": dict(sim.get("score") or {}),
        "probabilities": dict(sim.get("probabilities") or betting.get("probabilities") or {}),
    }


def _game_market_features_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered_rows = sorted(rows, key=lambda row: _safe_float(row.get("ev_pct")) or float("-inf"), reverse=True)
    top_row = ordered_rows[0] if ordered_rows else {}
    type_rows: dict[str, list[dict[str, Any]]] = {}
    for row in ordered_rows:
        row_type = _safe_text(row.get("type") or "Recommendation").upper()
        type_rows.setdefault(row_type, []).append(row)
    return {
        "top_row": dict(top_row),
        "rows": [dict(row) for row in ordered_rows],
        "by_type": {key: [dict(row) for row in value] for key, value in type_rows.items()},
        "moneyline": dict(top_row) if _safe_text(top_row.get("type")).upper() == "MONEYLINE" else {},
        "spread": dict(top_row) if _safe_text(top_row.get("type")).upper() == "SPREAD" else {},
        "total": dict(top_row) if _safe_text(top_row.get("type")).upper() == "TOTAL" else {},
    }


def _load_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _team_name_to_abbr(team_name: Any) -> str:
    return canonical_team_abbr(team_name)


def _historical_json_candidates(date: str, season: int | None) -> list[Path]:
    root = default_nfl_source_root()
    source_root = root / "source_artifacts"
    date_token = str(date or "").strip().replace("-", "_")
    candidates: list[Path] = []
    for base in (root, source_root):
        if not base.exists():
            continue
        if date_token:
            candidates.extend(sorted(base.glob(f"real_betting_lines_{date_token}.json")))
        if season is not None:
            candidates.extend(sorted(base.glob(f"real_betting_lines_{season}_*.json")))
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(candidate)
    return deduped


def _schedule_source_label(path: Path) -> str:
    name = path.name
    if name.startswith("real_betting_lines_") and name.endswith(".json"):
        return "real_betting_lines"
    return path.stem


def _historical_game_rows(date: str, season: int | None) -> list[dict[str, Any]]:
    for path in _historical_json_candidates(date, season):
        payload = _load_json_payload(path)
        lines = payload.get("lines") if isinstance(payload.get("lines"), dict) else None
        if not lines:
            continue
        games: list[dict[str, Any]] = []
        for event_key, market_payload in lines.items():
            if "@" not in str(event_key) or not isinstance(market_payload, dict):
                continue
            away_team_raw, home_team_raw = [part.strip() for part in str(event_key).split("@", 1)]
            away_team = _team_name_to_abbr(away_team_raw)
            home_team = _team_name_to_abbr(home_team_raw)
            markets = market_payload.get("markets") if isinstance(market_payload.get("markets"), list) else []
            spread_price = None
            total_over_price = None
            total_under_price = None
            for market in markets:
                if not isinstance(market, dict):
                    continue
                key = _safe_text(market.get("key")).lower()
                outcomes = market.get("outcomes") if isinstance(market.get("outcomes"), list) else []
                if key == "spreads":
                    for outcome in outcomes:
                        if isinstance(outcome, dict) and _team_name_to_abbr(outcome.get("name")) == home_team:
                            spread_price = outcome.get("price")
                elif key == "totals":
                    for outcome in outcomes:
                        if not isinstance(outcome, dict):
                            continue
                        if _safe_text(outcome.get("name")).lower() == "over":
                            total_over_price = outcome.get("price")
                        elif _safe_text(outcome.get("name")).lower() == "under":
                            total_under_price = outcome.get("price")
            games.append(
                {
                    "game_id": f"{season or ''}-{date}-{away_team}-{home_team}".strip("-"),
                    "home_team": home_team,
                    "away_team": away_team,
                    "game_date": date,
                    "season": str(season or ""),
                    "week": "",
                    "team_metrics": {},
                    "defensive_metrics": {},
                    "matchup_metrics": {},
                    "pace_features": {},
                    "market_features": {
                        "market": dict(market_payload),
                        "simulation": {},
                        "score": {},
                        "probabilities": {},
                        "total": {
                            "line": (market_payload.get("total_runs") or {}).get("line") if isinstance(market_payload.get("total_runs"), dict) else None,
                            "over_price": total_over_price,
                            "under_price": total_under_price,
                        },
                        "moneyline": dict(market_payload.get("moneyline") or {}),
                        "spread": {
                            "home_line": (market_payload.get("run_line") or {}).get("home") if isinstance(market_payload.get("run_line"), dict) else None,
                            "home_price": spread_price,
                        },
                    },
                    "sim": {
                        "score": {},
                        "probabilities": {"home": None, "away": None},
                        "players": {},
                    },
                    "source_title": f"Historical NFL lines for {date}",
                    "source_path": str(path),
                    "status": "historical",
                    "detail": f"{len(markets)} markets",
                }
            )
        if games:
            schedule_source = _schedule_source_label(path)
            for game in games:
                game.setdefault("adapter_metadata", {})
                if isinstance(game["adapter_metadata"], dict):
                    game["adapter_metadata"].setdefault("source", schedule_source)
                    game["adapter_metadata"].setdefault("source_path", str(path))
            return games
    return []


def _historical_pbp_game_rows(date: str, season: int | None) -> list[dict[str, Any]]:
    if season is None:
        return []
    rows = list(load_nflverse_rows(season=season))
    if not rows:
        return []
    matching_rows = [row for row in rows if _safe_text(row.get("game_date")) == _safe_text(date) or _safe_text(row.get("date")) == _safe_text(date)]
    if not matching_rows:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in matching_rows:
        game_id = _safe_text(row.get("game_id") or row.get("old_game_id") or row.get("game_date") or date)
        grouped.setdefault(game_id, []).append(row)
    games: list[dict[str, Any]] = []
    for game_id, game_rows in grouped.items():
        first = game_rows[0]
        home_team = canonical_team_abbr(first.get("home_team") or first.get("posteam") or "")
        away_team = canonical_team_abbr(first.get("away_team") or "")
        if not home_team or not away_team:
            teams = sorted({ canonical_team_abbr(row.get("posteam") or "") for row in game_rows if canonical_team_abbr(row.get("posteam") or "") })
            if len(teams) >= 2:
                away_team, home_team = teams[0], teams[1]
        games.append(
            {
                "game_id": game_id,
                "home_team": home_team,
                "away_team": away_team,
                "game_date": _safe_text(first.get("game_date") or date),
                "season": _safe_text(first.get("season") or season),
                "week": _safe_text(first.get("week") or ""),
                "team_metrics": {},
                "defensive_metrics": {},
                "matchup_metrics": {},
                "pace_features": {},
                "market_features": {},
                "sim": {
                    "score": {},
                    "probabilities": {"home": None, "away": None},
                    "players": {},
                },
                "source_title": f"NFLverse historical game rows for {date}",
                "source_path": "nflverse_play_by_play",
                "status": "historical",
                "detail": f"{len(game_rows)} play-by-play rows",
                "home": {"abbr": home_team},
                "away": {"abbr": away_team},
            }
        )
    return games


def _team_abbr_lookup_from_pbp(rows: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in rows:
        home = _safe_text(row.get("home_team") or "")
        away = _safe_text(row.get("away_team") or "")
        if home:
            lookup[home] = home
        if away:
            lookup[away] = away
    return lookup


def _historical_player_rows(date: str, season: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target_rows = _historical_pbp_game_rows(date, season)
    if not target_rows:
        target_rows = _historical_game_rows(date, season)
    target_games = [
        {
            "week": _safe_text(row.get("week") or ""),
            "home_team": _safe_text(row.get("home_team") or ""),
            "away_team": _safe_text(row.get("away_team") or ""),
            "game_id": _safe_text(row.get("game_id") or ""),
        }
        for row in target_rows
    ]
    for row in load_nflverse_player_stats(season or 2025):
        if not isinstance(row, dict):
            continue
        row_week = _safe_text(row.get("week") or "")
        team = canonical_team_abbr(row.get("team") or row.get("team_abbr") or row.get("posteam"))
        opponent_team = canonical_team_abbr(row.get("opponent_team") or row.get("defteam") or row.get("opp_team"))
        row_game_id = _safe_text(row.get("game_id") or "")
        if target_games:
            matched = any(
                (
                    (game["game_id"] and row_game_id == game["game_id"])
                    or (
                        (not game["week"] or row_week == game["week"])
                        and (team in {game["home_team"], game["away_team"]})
                        and (opponent_team in {game["home_team"], game["away_team"]})
                    )
                )
                for game in target_games
            )
            if not matched:
                continue
        elif row_week != _safe_text(date):
            continue
        player_name = _safe_text(row.get("player_display_name") or row.get("player_name") or row.get("player"))
        if not player_name or not team:
            continue
        rows.append(
            {
                "player_id": _safe_text(row.get("player_id") or row.get("player_name") or row.get("player_display_name") or row.get("player")),
                "player_name": player_name,
                "team": team,
                "position": _safe_text(row.get("position")),
                "usage_metrics": {
                    "target_share": _safe_float(row.get("target_share") or row.get("targets_share")),
                    "route_participation": _safe_float(row.get("route_participation") or row.get("route_pct") or row.get("routes_share") or row.get("wopr")),
                    "snap_share": _safe_float(row.get("snap_share") or row.get("snap_pct") or row.get("snaps_share")),
                    "carry_share": _safe_float(row.get("carry_share") or row.get("carry_share_pct") or row.get("rush_pct")),
                },
                "market_features": {
                    "game_date": date,
                    "week": row_week,
                    "opponent_team": opponent_team,
                    "line": None,
                },
            }
        )
    return rows


def build_historical_football_simulation_input(*, sport: str, date: str, season: int | None = None) -> FootballSimulationInput:
    games = _historical_game_rows(date, season)
    if not games:
        games = _historical_pbp_game_rows(date, season)
    players = _historical_player_rows(date, season)
    if not games:
        return FootballSimulationInput(
            sport=sport,
            date=date,
            adapter_metadata={"source": "historical_fallback_empty", "season": season},
        )
    game_features: list[FootballGameFeatures] = []
    player_features: list[FootballPlayerFeatures] = []
    for game in games:
        home_team = canonical_team_abbr(game.get("home_team"))
        away_team = canonical_team_abbr(game.get("away_team"))
        game["home"] = {"abbr": home_team}
        game["away"] = {"abbr": away_team}
        nflverse_metrics = build_nflverse_game_metrics(game, season=season, week=None)
        if nflverse_metrics:
            game.setdefault("advanced_metrics", {})
            if isinstance(game["advanced_metrics"], dict):
                game["advanced_metrics"].update(nflverse_metrics)
            game.setdefault("team_metrics", {})
            if isinstance(game["team_metrics"], dict):
                game["team_metrics"].setdefault("offensive_epa", nflverse_metrics.get("epa_per_play"))
                game["team_metrics"].setdefault("epa_play", nflverse_metrics.get("epa_per_play"))
                game["team_metrics"].setdefault("defensive_epa", nflverse_metrics.get("away_defensive_epa"))
                game["team_metrics"].setdefault("epa_allowed", nflverse_metrics.get("away_defensive_epa"))
                game["team_metrics"].setdefault("success_rate", nflverse_metrics.get("success_rate"))
                game["team_metrics"].setdefault("success_rate_allowed", nflverse_metrics.get("away_success_rate"))
                game["team_metrics"].setdefault("pass_rate_over_expectation", nflverse_metrics.get("proe"))
                game["team_metrics"].setdefault("proe", nflverse_metrics.get("proe"))
                game["team_metrics"].setdefault("home_offensive_epa", nflverse_metrics.get("home_offensive_epa"))
                game["team_metrics"].setdefault("away_offensive_epa", nflverse_metrics.get("away_offensive_epa"))
                game["team_metrics"].setdefault("home_defensive_epa", nflverse_metrics.get("home_defensive_epa"))
                game["team_metrics"].setdefault("away_defensive_epa", nflverse_metrics.get("away_defensive_epa"))
                game["team_metrics"].setdefault("home_success_rate", nflverse_metrics.get("home_success_rate"))
                game["team_metrics"].setdefault("away_success_rate", nflverse_metrics.get("away_success_rate"))
                game["team_metrics"].setdefault("home_pass_rate", nflverse_metrics.get("home_pass_rate"))
                game["team_metrics"].setdefault("away_pass_rate", nflverse_metrics.get("away_pass_rate"))
                game["team_metrics"].setdefault("home_rush_rate", nflverse_metrics.get("home_rush_rate"))
                game["team_metrics"].setdefault("away_rush_rate", nflverse_metrics.get("away_rush_rate"))
        game_features.append(to_football_game_features(game, sport=sport, date=date))
        player_features.extend(_player_features_from_game(game, sport=sport, date=date, season=season, selection=None))
    if not player_features:
        for player in players:
            player_features.append(
                FootballPlayerFeatures(
                    sport=sport,
                    date=date,
                    player_id=_safe_text(player.get("player_id")),
                    player_name=_safe_text(player.get("player_name")),
                    team=canonical_team_abbr(player.get("team")),
                    position=_safe_text(player.get("position")),
                    usage_metrics=dict(player.get("usage_metrics") or {}),
                    market_features=dict(player.get("market_features") or {}),
                    adapter_metadata={"source": "historical_player_row", "season": season},
                )
            )
    return FootballSimulationInput(
        sport=sport,
        date=date,
        games=tuple(game_features),
        players=tuple(player_features),
        metadata={
            "season": season,
            "selection": "",
            "game_count": len(game_features),
            "player_count": len(player_features),
        },
        adapter_metadata={
            "source": "historical_football_loader",
            "season": season,
            "schedule_source": "real_betting_lines" if games and isinstance(games[0].get("adapter_metadata"), dict) and games[0]["adapter_metadata"].get("source") == "real_betting_lines" else None,
            "home_team_metadata": canonical_team_metadata(games[0].get("home_team")) if games else {},
            "away_team_metadata": canonical_team_metadata(games[0].get("away_team")) if games else {},
        },
    )


@lru_cache(maxsize=16)
def _read_snapshot_rows(season: int, week: int) -> tuple[dict[str, Any], ...]:
    path = recommendation_path(week, season=season)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(row for row in csv.DictReader(handle) if isinstance(row, dict))
    except Exception:
        return ()


def _group_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        game_date = _safe_text(row.get("game_date") or row.get("date") or "")
        home_team = _safe_text(row.get("home_team") or "Home")
        away_team = _safe_text(row.get("away_team") or "Away")
        season = _safe_text(row.get("season") or "")
        week = _safe_text(row.get("week") or "")
        grouped.setdefault((season, week, game_date, away_team, home_team), []).append(row)
    games: list[dict[str, Any]] = []
    for (season, week, game_date, away_team, home_team), matchup_rows in grouped.items():
        market_features = _game_market_features_from_rows(matchup_rows)
        top_row = market_features.get("top_row") if isinstance(market_features.get("top_row"), dict) else {}
        games.append(
            {
                "game_id": f"{season}-{week}-{away_team}-{home_team}".strip("-") or f"{away_team}-{home_team}",
                "home_team": home_team,
                "away_team": away_team,
                "game_date": game_date,
                "season": _safe_text(season, ""),
                "week": _safe_text(week, ""),
                "team_metrics": {},
                "defensive_metrics": {},
                "matchup_metrics": {},
                "pace_features": {},
                "market_features": market_features,
                "sim": {
                    "score": {},
                    "probabilities": {
                        "home": _safe_float(top_row.get("ev_pct")),
                        "away": None,
                    },
                    "players": {},
                },
                "source_title": f"NFL recommendations summary for Week {week}",
                "source_path": str(recommendation_path(int(week or 0), season=int(season or 0) or None)),
                "status": "ok",
                "detail": f"{len(matchup_rows)} recommendation rows",
            }
        )
    return games


@lru_cache(maxsize=16)
def _load_manifest(season: int, week: int) -> dict[str, Any]:
    path = default_nfl_source_root() / "manifests" / f"{season}_wk{week}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_games(season: int, week: int) -> list[dict[str, Any]]:
    return _group_snapshot_rows(list(_read_snapshot_rows(season, week)))


def _game_adapter_metadata(game: dict[str, Any], *, sport: str, season: int | None = None, selection: Any | None = None) -> dict[str, Any]:
    raw_metadata = dict(game.get("adapter_metadata") or {})
    home_team = canonical_team_abbr(game.get("home_team") or (game.get("home") or {}).get("abbr") or "")
    away_team = canonical_team_abbr(game.get("away_team") or (game.get("away") or {}).get("abbr") or "")
    return {
        "sport": sport,
        "season": season,
        "selection": _safe_text(selection, ""),
        "source_title": _safe_text(game.get("source_title") or ""),
        "source_path": _safe_text(game.get("source_path") or ""),
        "status": _safe_text(game.get("status") or ""),
        "detail": _safe_text(game.get("detail") or ""),
        "schedule_source": raw_metadata.get("schedule_source") or raw_metadata.get("source"),
        "schedule_source_path": raw_metadata.get("source_path") or raw_metadata.get("schedule_source_path"),
        "home_team_metadata": canonical_team_metadata(home_team),
        "away_team_metadata": canonical_team_metadata(away_team),
    }


def _player_features_from_game(
    game: dict[str, Any],
    *,
    sport: str,
    date: str,
    season: int | None = None,
    selection: Any | None = None,
) -> list[FootballPlayerFeatures]:
    players: list[FootballPlayerFeatures] = []
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    projections = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    for side in ("home", "away"):
        side_players = projections.get(side)
        if not isinstance(side_players, list):
            continue
        for player in side_players:
            if not isinstance(player, dict):
                continue
            player_team = canonical_team_abbr((game.get(side) or {}).get("abbr") or game.get(f"{side}_team") or "")
            player_features = to_football_player_features(
                {
                    "player_id": player.get("player_id") or player.get("id") or player.get("player") or "",
                    "player_name": player.get("player_name") or player.get("player") or player.get("name") or "",
                    "team": player_team,
                    "position": player.get("position") or "",
                    "usage_metrics": dict(player),
                    "market_features": _game_market_features(game),
                },
                sport=sport,
                date=date,
                season=season,
                week=selection if isinstance(selection, int) else None,
            )
            players.append(player_features)
    return players


def build_football_simulation_input(
    *,
    sport: str,
    date: str,
    games: list[dict[str, Any]],
    season: int | None = None,
    selection: Any | None = None,
) -> FootballSimulationInput:
    game_features: list[FootballGameFeatures] = []
    player_features: list[FootballPlayerFeatures] = []
    season_value = int(season or 0) if season is not None else None
    week_value = None
    if isinstance(selection, int):
        week_value = selection
    for game in games:
        if not isinstance(game, dict):
            continue
        converted = dict(game)
        converted["team_metrics"] = dict(game.get("team_metrics") or {})
        converted["defensive_metrics"] = dict(game.get("defensive_metrics") or {})
        converted["matchup_metrics"] = dict(game.get("matchup_metrics") or {})
        converted["market_features"] = _game_market_features(game)
        converted["pace_features"] = dict(game.get("pace_features") or {})
        nflverse_metrics = build_nflverse_game_metrics(game, season=season_value, week=week_value)
        if nflverse_metrics:
            converted["advanced_metrics"] = dict(nflverse_metrics)
            converted["team_metrics"].setdefault("offensive_epa", nflverse_metrics.get("epa_per_play"))
            converted["team_metrics"].setdefault("epa_play", nflverse_metrics.get("epa_per_play"))
            converted["team_metrics"].setdefault("defensive_epa", nflverse_metrics.get("away_defensive_epa"))
            converted["team_metrics"].setdefault("epa_allowed", nflverse_metrics.get("away_defensive_epa"))
            converted["team_metrics"].setdefault("success_rate", nflverse_metrics.get("success_rate"))
            converted["team_metrics"].setdefault("success_rate_allowed", nflverse_metrics.get("away_success_rate"))
            converted["team_metrics"].setdefault("pass_rate_over_expectation", nflverse_metrics.get("proe"))
            converted["team_metrics"].setdefault("proe", nflverse_metrics.get("proe"))
            converted["team_metrics"].setdefault("home_offensive_epa", nflverse_metrics.get("home_offensive_epa"))
            converted["team_metrics"].setdefault("away_offensive_epa", nflverse_metrics.get("away_offensive_epa"))
            converted["team_metrics"].setdefault("home_defensive_epa", nflverse_metrics.get("home_defensive_epa"))
            converted["team_metrics"].setdefault("away_defensive_epa", nflverse_metrics.get("away_defensive_epa"))
            converted["team_metrics"].setdefault("home_success_rate", nflverse_metrics.get("home_success_rate"))
            converted["team_metrics"].setdefault("away_success_rate", nflverse_metrics.get("away_success_rate"))
            converted["team_metrics"].setdefault("home_pass_rate", nflverse_metrics.get("home_pass_rate"))
            converted["team_metrics"].setdefault("away_pass_rate", nflverse_metrics.get("away_pass_rate"))
            converted["team_metrics"].setdefault("home_rush_rate", nflverse_metrics.get("home_rush_rate"))
            converted["team_metrics"].setdefault("away_rush_rate", nflverse_metrics.get("away_rush_rate"))
        rbsdm_metrics = build_rbsdm_game_metrics(game, season=season_value, week=week_value)
        if rbsdm_metrics:
            converted.setdefault("advanced_metrics", {})
            converted["advanced_metrics"].update(rbsdm_metrics)
            converted["team_metrics"].setdefault("offensive_epa", rbsdm_metrics.get("epa_per_play"))
            converted["team_metrics"].setdefault("epa_play", rbsdm_metrics.get("epa_per_play"))
            converted["team_metrics"].setdefault("defensive_epa", rbsdm_metrics.get("away_defensive_epa"))
            converted["team_metrics"].setdefault("epa_allowed", rbsdm_metrics.get("away_defensive_epa"))
            converted["team_metrics"].setdefault("success_rate", rbsdm_metrics.get("success_rate"))
            converted["team_metrics"].setdefault("success_rate_allowed", rbsdm_metrics.get("away_success_rate"))
            converted["team_metrics"].setdefault("pass_rate_over_expectation", rbsdm_metrics.get("proe"))
            converted["team_metrics"].setdefault("proe", rbsdm_metrics.get("proe"))
            converted["team_metrics"].setdefault("red_zone_efficiency", rbsdm_metrics.get("home_red_zone_efficiency"))
            converted["team_metrics"].setdefault("explosive_play_rate", rbsdm_metrics.get("home_explosive_play_rate"))
            converted["team_metrics"].setdefault("home_offensive_epa", rbsdm_metrics.get("home_offensive_epa"))
            converted["team_metrics"].setdefault("away_offensive_epa", rbsdm_metrics.get("away_offensive_epa"))
            converted["team_metrics"].setdefault("home_defensive_epa", rbsdm_metrics.get("home_defensive_epa"))
            converted["team_metrics"].setdefault("away_defensive_epa", rbsdm_metrics.get("away_defensive_epa"))
            converted["team_metrics"].setdefault("home_success_rate", rbsdm_metrics.get("home_success_rate"))
            converted["team_metrics"].setdefault("away_success_rate", rbsdm_metrics.get("away_success_rate"))
            converted["team_metrics"].setdefault("home_success_rate_allowed", rbsdm_metrics.get("home_success_rate_allowed"))
            converted["team_metrics"].setdefault("away_success_rate_allowed", rbsdm_metrics.get("away_success_rate_allowed"))
            converted["team_metrics"].setdefault("home_red_zone_efficiency", rbsdm_metrics.get("home_red_zone_efficiency"))
            converted["team_metrics"].setdefault("away_red_zone_efficiency", rbsdm_metrics.get("away_red_zone_efficiency"))
            converted["team_metrics"].setdefault("home_explosive_play_rate", rbsdm_metrics.get("home_explosive_play_rate"))
            converted["team_metrics"].setdefault("away_explosive_play_rate", rbsdm_metrics.get("away_explosive_play_rate"))
            converted["team_metrics"].setdefault("home_pace_secs_play", rbsdm_metrics.get("home_pace_secs_play"))
            converted["team_metrics"].setdefault("away_pace_secs_play", rbsdm_metrics.get("away_pace_secs_play"))
            converted["team_metrics"].setdefault("home_pass_rate", rbsdm_metrics.get("home_pass_rate"))
            converted["team_metrics"].setdefault("away_pass_rate", rbsdm_metrics.get("away_pass_rate"))
        if season_value is not None and week_value is not None:
            manifest_rows = _manifest_games(season_value, week_value)
            home_team = _safe_text((game.get("home") or {}).get("abbr") or game.get("home_team") or "")
            away_team = _safe_text((game.get("away") or {}).get("abbr") or game.get("away_team") or "")
            row = next(
                (
                    manifest_row
                    for manifest_row in manifest_rows
                    if _safe_text(manifest_row.get("home_team") or "") == home_team and _safe_text(manifest_row.get("away_team") or "") == away_team
                ),
                None,
            )
            if row:
                converted["advanced_metrics"] = build_advanced_metrics(row)
                converted["team_metrics"].setdefault("offensive_epa", converted["advanced_metrics"].get("home_offensive_epa"))
                converted["team_metrics"].setdefault("epa_play", converted["advanced_metrics"].get("home_offensive_epa"))
                converted["team_metrics"].setdefault("defensive_epa", converted["advanced_metrics"].get("home_defensive_epa"))
                converted["team_metrics"].setdefault("epa_allowed", converted["advanced_metrics"].get("home_defensive_epa"))
                converted["team_metrics"].setdefault("success_rate", converted["advanced_metrics"].get("home_success_rate"))
                converted["team_metrics"].setdefault("success_rate_allowed", converted["advanced_metrics"].get("home_success_rate_allowed"))
                converted["team_metrics"].setdefault("pass_rate_over_expectation", converted["advanced_metrics"].get("pass_rate_diff"))
                converted["team_metrics"].setdefault("red_zone_efficiency", converted["advanced_metrics"].get("home_red_zone_efficiency"))
                converted["team_metrics"].setdefault("explosive_play_rate", converted["advanced_metrics"].get("home_explosive_pass_rate"))
                converted["pace_features"].setdefault("pace", converted["advanced_metrics"].get("home_pace_secs_play"))
                converted["pace_features"].setdefault("possessions", converted["advanced_metrics"].get("home_pace_secs_play"))
        converted["home_team"] = canonical_team_abbr(converted.get("home_team") or (converted.get("home") or {}).get("abbr") or "")
        converted["away_team"] = canonical_team_abbr(converted.get("away_team") or (converted.get("away") or {}).get("abbr") or "")
        converted["home"] = {"abbr": converted["home_team"]}
        converted["away"] = {"abbr": converted["away_team"]}
        converted["adapter_metadata"] = _game_adapter_metadata(game, sport=sport, season=season, selection=selection)
        game_features.append(to_football_game_features(converted, sport=sport, date=date))
        player_features.extend(_player_features_from_game(game, sport=sport, date=date))

    simulation_adapter_metadata = {
        "source": "football_feature_loader",
        "season": season,
    }
    if games:
        simulation_adapter_metadata.update(
            _game_adapter_metadata(
                games[0],
                sport=sport,
                season=season,
                selection=selection,
            )
        )

    return FootballSimulationInput(
        sport=sport,
        date=date,
        games=tuple(game_features),
        players=tuple(player_features),
        metadata={
            "season": season,
            "selection": _safe_text(selection, ""),
            "game_count": len(game_features),
            "player_count": len(player_features),
        },
        adapter_metadata=simulation_adapter_metadata,
    )