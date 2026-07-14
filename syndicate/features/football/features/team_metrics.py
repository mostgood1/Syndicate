from __future__ import annotations

from typing import Any

from syndicate.features.football.contracts import FootballTeamFeatures
from syndicate.features.football.contracts import FootballGameFeatures
from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata


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


def _team_metric_aliases(game: dict[str, Any]) -> dict[str, Any]:
    team_metrics = dict(game.get("team_metrics") or {})
    defensive_metrics = dict(game.get("defensive_metrics") or {})
    advanced_metrics = dict(game.get("advanced_metrics") or {})
    pace_features = dict(game.get("pace_features") or {})

    offensive_epa = _first_float(advanced_metrics, ["offensive_epa", "epa_play", "home_off_epa", "away_off_epa"])
    defensive_epa = _first_float(advanced_metrics, ["defensive_epa", "epa_allowed", "home_def_epa", "away_def_epa"])
    success_rate = _first_float(advanced_metrics, ["success_rate", "home_success_rate", "away_success_rate"])
    success_rate_allowed = _first_float(advanced_metrics, ["success_rate_allowed", "home_success_rate_allowed", "away_success_rate_allowed"])
    pass_rate_over_expectation = _first_float(advanced_metrics, ["pass_rate_over_expectation", "proe", "home_pass_rate", "away_pass_rate"])
    red_zone_efficiency = _first_float(advanced_metrics, ["red_zone_efficiency", "rz_efficiency", "home_rzd_off_eff", "away_rzd_off_eff"])
    explosive_play_rate = _first_float(advanced_metrics, ["explosive_play_rate", "home_explosive_pass_rate", "away_explosive_pass_rate"])
    pace_value = _first_float(pace_features, ["pace", "possessions", "drives"])

    team_metrics.setdefault("offensive_epa", offensive_epa)
    team_metrics.setdefault("epa_play", offensive_epa)
    team_metrics.setdefault("defensive_epa", defensive_epa)
    team_metrics.setdefault("epa_allowed", defensive_epa)
    team_metrics.setdefault("success_rate", success_rate)
    team_metrics.setdefault("success_rate_allowed", success_rate_allowed)
    team_metrics.setdefault("pass_rate_over_expectation", pass_rate_over_expectation)
    team_metrics.setdefault("proe", pass_rate_over_expectation)
    team_metrics.setdefault("red_zone_efficiency", red_zone_efficiency)
    team_metrics.setdefault("explosive_play_rate", explosive_play_rate)
    team_metrics.setdefault("home_offensive_epa", _first_float(advanced_metrics, ["home_offensive_epa", "home_off_epa", "home_off_epa_ema", "home_off_epa_blend"]))
    team_metrics.setdefault("away_offensive_epa", _first_float(advanced_metrics, ["away_offensive_epa", "away_off_epa", "away_off_epa_ema", "away_off_epa_blend"]))
    team_metrics.setdefault("home_defensive_epa", _first_float(advanced_metrics, ["home_defensive_epa", "home_def_epa", "home_def_epa_ema", "home_def_epa_blend"]))
    team_metrics.setdefault("away_defensive_epa", _first_float(advanced_metrics, ["away_defensive_epa", "away_def_epa", "away_def_epa_ema", "away_def_epa_blend"]))
    team_metrics.setdefault("home_success_rate", _first_float(advanced_metrics, ["home_success_rate", "home_success_rate_ema"]))
    team_metrics.setdefault("away_success_rate", _first_float(advanced_metrics, ["away_success_rate", "away_success_rate_ema"]))
    team_metrics.setdefault("home_success_rate_allowed", _first_float(advanced_metrics, ["home_success_rate_allowed", "home_def_success_rate", "home_success_rate_allowed_ema"]))
    team_metrics.setdefault("away_success_rate_allowed", _first_float(advanced_metrics, ["away_success_rate_allowed", "away_def_success_rate", "away_success_rate_allowed_ema"]))
    team_metrics.setdefault("home_red_zone_efficiency", _first_float(advanced_metrics, ["home_red_zone_efficiency", "home_rzd_off_eff"]))
    team_metrics.setdefault("away_red_zone_efficiency", _first_float(advanced_metrics, ["away_red_zone_efficiency", "away_rzd_off_eff"]))
    team_metrics.setdefault("home_explosive_pass_rate", _first_float(advanced_metrics, ["home_explosive_pass_rate"]))
    team_metrics.setdefault("away_explosive_pass_rate", _first_float(advanced_metrics, ["away_explosive_pass_rate"]))
    team_metrics.setdefault("home_pace_secs_play", _first_float(advanced_metrics, ["home_pace_secs_play"]))
    team_metrics.setdefault("away_pace_secs_play", _first_float(advanced_metrics, ["away_pace_secs_play"]))
    team_metrics.setdefault("home_pass_rate", _first_float(advanced_metrics, ["home_pass_rate", "home_pass_rate_ema", "home_pass_rate_prior", "home_pass_rate_blend"]))
    team_metrics.setdefault("away_pass_rate", _first_float(advanced_metrics, ["away_pass_rate", "away_pass_rate_ema", "away_pass_rate_prior", "away_pass_rate_blend"]))

    pace_features.setdefault("pace", pace_value)
    if pace_features.get("possessions") is None and pace_value is not None:
        pace_features.setdefault("possessions", pace_value)

    return {
        "game_id": str(game.get("gamePk") or game.get("game_id") or "").strip(),
        "home_team": canonical_team_abbr((game.get("home") or {}).get("abbr") or game.get("home_team") or ""),
        "away_team": canonical_team_abbr((game.get("away") or {}).get("abbr") or game.get("away_team") or ""),
        "team_metrics": team_metrics,
        "defensive_metrics": defensive_metrics,
        "advanced_metrics": advanced_metrics,
        "pace_features": pace_features,
        "offensive_epa": offensive_epa,
        "defensive_epa": defensive_epa,
        "success_rate": success_rate,
        "success_rate_allowed": success_rate_allowed,
        "pass_rate_over_expectation": pass_rate_over_expectation,
        "proe": pass_rate_over_expectation,
        "red_zone_efficiency": red_zone_efficiency,
        "explosive_play_rate": explosive_play_rate,
    }


def build_team_metrics(game: dict[str, Any], *, sport: str, date: str) -> dict[str, Any]:
    aliases = _team_metric_aliases(game)
    team_metrics = aliases["team_metrics"]
    return {
        "game_id": aliases["game_id"],
        "home_team": aliases["home_team"],
        "away_team": aliases["away_team"],
        "team_metrics": team_metrics,
        "defensive_metrics": aliases["defensive_metrics"],
        "advanced_metrics": aliases["advanced_metrics"],
        "matchup_metrics": dict(game.get("matchup_metrics") or {}),
        "market_features": dict(game.get("market_features") or {}),
        "pace_features": aliases["pace_features"],
        "offensive_epa": aliases["offensive_epa"],
        "defensive_epa": aliases["defensive_epa"],
        "success_rate": aliases["success_rate"],
        "success_rate_allowed": aliases["success_rate_allowed"],
        "pass_rate_over_expectation": aliases["pass_rate_over_expectation"],
        "proe": aliases["proe"],
        "red_zone_efficiency": aliases["red_zone_efficiency"],
        "explosive_play_rate": aliases["explosive_play_rate"],
        "epa_per_play": aliases["offensive_epa"],
        "success_rate_value": aliases["success_rate"],
        "proe_value": aliases["proe"],
        "red_zone_efficiency_value": aliases["red_zone_efficiency"],
        "explosive_play_rate_value": aliases["explosive_play_rate"],
        "home_offensive_epa": team_metrics.get("home_offensive_epa"),
        "away_offensive_epa": team_metrics.get("away_offensive_epa"),
        "home_defensive_epa": team_metrics.get("home_defensive_epa"),
        "away_defensive_epa": team_metrics.get("away_defensive_epa"),
        "home_success_rate": team_metrics.get("home_success_rate"),
        "away_success_rate": team_metrics.get("away_success_rate"),
        "home_success_rate_allowed": team_metrics.get("home_success_rate_allowed"),
        "away_success_rate_allowed": team_metrics.get("away_success_rate_allowed"),
        "home_red_zone_efficiency": team_metrics.get("home_red_zone_efficiency"),
        "away_red_zone_efficiency": team_metrics.get("away_red_zone_efficiency"),
        "home_explosive_pass_rate": team_metrics.get("home_explosive_pass_rate"),
        "away_explosive_pass_rate": team_metrics.get("away_explosive_pass_rate"),
        "home_pace_secs_play": team_metrics.get("home_pace_secs_play"),
        "away_pace_secs_play": team_metrics.get("away_pace_secs_play"),
        "home_pass_rate": team_metrics.get("home_pass_rate"),
        "away_pass_rate": team_metrics.get("away_pass_rate"),
        "sport": sport,
        "date": date,
    }


def to_football_game_features(game: dict[str, Any], *, sport: str, date: str) -> FootballGameFeatures:
    metrics = build_team_metrics(game, sport=sport, date=date)
    adapter_metadata = dict(game.get("adapter_metadata") or {})
    adapter_metadata.setdefault("source", "feature_builder")
    adapter_metadata.setdefault("sport", sport)
    adapter_metadata.setdefault("home_team_metadata", canonical_team_metadata(metrics["home_team"]))
    adapter_metadata.setdefault("away_team_metadata", canonical_team_metadata(metrics["away_team"]))
    home_team_features = FootballTeamFeatures(
        sport=sport,
        date=date,
        team_id=metrics["home_team"],
        team_name=metrics["home_team"],
        team_abbr=metrics["home_team"],
        offensive_metrics={
            **dict(metrics["team_metrics"]),
            "offensive_epa": metrics.get("offensive_epa"),
            "success_rate": metrics.get("success_rate"),
            "pass_rate_over_expectation": metrics.get("pass_rate_over_expectation"),
            "proe": metrics.get("proe"),
            "red_zone_efficiency": metrics.get("red_zone_efficiency"),
            "explosive_play_rate": metrics.get("explosive_play_rate"),
        },
        defensive_metrics={
            **dict(metrics["defensive_metrics"]),
            "defensive_epa": metrics.get("defensive_epa"),
            "success_rate_allowed": metrics.get("success_rate_allowed"),
        },
        pace_metrics=dict(metrics["pace_features"]),
        market_features=dict(metrics["market_features"]),
        adapter_metadata={"side": "home", "sport": sport, "team_metadata": canonical_team_metadata(metrics["home_team"])},
    )
    away_team_features = FootballTeamFeatures(
        sport=sport,
        date=date,
        team_id=metrics["away_team"],
        team_name=metrics["away_team"],
        team_abbr=metrics["away_team"],
        offensive_metrics={
            **dict(metrics["team_metrics"]),
            "offensive_epa": metrics.get("offensive_epa"),
            "success_rate": metrics.get("success_rate"),
            "pass_rate_over_expectation": metrics.get("pass_rate_over_expectation"),
            "proe": metrics.get("proe"),
            "red_zone_efficiency": metrics.get("red_zone_efficiency"),
            "explosive_play_rate": metrics.get("explosive_play_rate"),
        },
        defensive_metrics={
            **dict(metrics["defensive_metrics"]),
            "defensive_epa": metrics.get("defensive_epa"),
            "success_rate_allowed": metrics.get("success_rate_allowed"),
        },
        pace_metrics=dict(metrics["pace_features"]),
        market_features=dict(metrics["market_features"]),
        adapter_metadata={"side": "away", "sport": sport, "team_metadata": canonical_team_metadata(metrics["away_team"])},
    )
    return FootballGameFeatures(
        sport=sport,
        date=date,
        game_id=metrics["game_id"],
        home_team=metrics["home_team"],
        away_team=metrics["away_team"],
        team_metrics=metrics["team_metrics"],
        defensive_metrics=metrics["defensive_metrics"],
        advanced_metrics=metrics["advanced_metrics"],
        matchup_metrics=metrics["matchup_metrics"],
        market_features=metrics["market_features"],
        pace_features=metrics["pace_features"],
        epa_per_play=metrics["offensive_epa"],
        success_rate_value=metrics["success_rate"],
        proe_value=metrics["proe"],
        red_zone_efficiency_value=metrics["red_zone_efficiency"],
        explosive_play_rate_value=metrics["explosive_play_rate"],
        home_team_features=home_team_features,
        away_team_features=away_team_features,
        adapter_metadata=adapter_metadata,
    )