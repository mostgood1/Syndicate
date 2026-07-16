from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Mapping

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _first_float(payload: Mapping[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        numeric = _safe_float(payload.get(key))
        if numeric is not None:
            return numeric
    return None


def _mean_float(value: Any) -> float | None:
    if isinstance(value, Mapping):
        samples = [_safe_float(item) for item in value.values()]
        samples = [sample for sample in samples if sample is not None]
        if not samples:
            return None
        return sum(samples) / float(len(samples))
    if isinstance(value, (list, tuple)):
        samples = [_safe_float(item) for item in value]
        samples = [sample for sample in samples if sample is not None]
        if not samples:
            return None
        return sum(samples) / float(len(samples))
    return _safe_float(value)


def _extract_block(sources: list[Mapping[str, Any]], names: list[str]) -> dict[str, Any]:
    for source in sources:
        for name in names:
            candidate = source.get(name)
            if isinstance(candidate, Mapping):
                return dict(candidate)
    return {}


def _sources_from_payload(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [payload]
    for key in ("football_features", "features", "feature_stack", "priors", "input_state"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            sources.append(candidate)
    return sources


@dataclass(frozen=True)
class DrivePriorProfile:
    offense_index: float
    defense_index: float
    pace_index: float
    returning_production_index: float
    coach_continuity_index: float
    transfer_volatility_index: float
    player_usage_index: float
    market_prior_index: float
    pace_seconds_per_play: float
    drive_success_probability: float
    turnover_probability: float
    explosive_play_probability: float
    field_goal_probability: float
    punt_probability: float
    touchdown_probability: float
    no_score_probability: float
    red_zone_touchdown_probability: float
    red_zone_field_goal_probability: float
    expected_play_count: float
    expected_clock_seconds: float
    expected_field_position_gain: float
    feature_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "offense_index": self.offense_index,
            "defense_index": self.defense_index,
            "pace_index": self.pace_index,
            "returning_production_index": self.returning_production_index,
            "coach_continuity_index": self.coach_continuity_index,
            "transfer_volatility_index": self.transfer_volatility_index,
            "player_usage_index": self.player_usage_index,
            "market_prior_index": self.market_prior_index,
            "pace_seconds_per_play": self.pace_seconds_per_play,
            "drive_success_probability": self.drive_success_probability,
            "turnover_probability": self.turnover_probability,
            "explosive_play_probability": self.explosive_play_probability,
            "field_goal_probability": self.field_goal_probability,
            "punt_probability": self.punt_probability,
            "touchdown_probability": self.touchdown_probability,
            "no_score_probability": self.no_score_probability,
            "red_zone_touchdown_probability": self.red_zone_touchdown_probability,
            "red_zone_field_goal_probability": self.red_zone_field_goal_probability,
            "expected_play_count": self.expected_play_count,
            "expected_clock_seconds": self.expected_clock_seconds,
            "expected_field_position_gain": self.expected_field_position_gain,
            "feature_summary": dict(self.feature_summary),
        }


def _offense_strength(offensive_metrics: Mapping[str, Any], advanced_metrics: Mapping[str, Any], player_usage: Mapping[str, Any], returning_production: Mapping[str, Any], coach_continuity: Mapping[str, Any]) -> float:
    offensive_epa = _first_float(offensive_metrics, ["offensive_epa", "epa_play", "home_offensive_epa", "away_offensive_epa", "epa"])
    success_rate = _first_float(offensive_metrics, ["success_rate", "home_success_rate", "away_success_rate"])
    red_zone_efficiency = _first_float(offensive_metrics, ["red_zone_efficiency", "home_red_zone_efficiency", "away_red_zone_efficiency"])
    explosive_play_rate = _first_float(offensive_metrics, ["explosive_play_rate", "home_explosive_pass_rate", "away_explosive_pass_rate"])
    pass_rate = _first_float(offensive_metrics, ["pass_rate_over_expectation", "proe", "home_pass_rate", "away_pass_rate"])
    advanced_off_epa = _first_float(advanced_metrics, ["home_offensive_epa", "away_offensive_epa", "offensive_epa"])
    usage = _mean_float(player_usage.get("usage_index") or player_usage.get("snap_share") or player_usage.get("target_share") or player_usage.get("route_participation") or player_usage.get("air_yard_share"))
    returning = _first_float(returning_production, ["percent_ppa", "returning_production", "summary_value"])
    coach = _first_float(coach_continuity, ["continuity_score", "score"])

    score = 0.0
    score += (offensive_epa or 0.0) * 0.55
    score += ((success_rate or 0.5) - 0.5) * 1.2
    score += ((red_zone_efficiency or 0.5) - 0.5) * 0.8
    score += ((explosive_play_rate or 0.1) - 0.1) * 0.9
    score += ((pass_rate or 0.5) - 0.5) * 0.6
    score += (advanced_off_epa or 0.0) * 0.35
    score += ((usage or 0.25) - 0.25) * 0.7
    score += ((returning or 0.5) - 0.5) * 0.45
    score += ((coach or 0.5) - 0.5) * 0.35
    return _clamp(0.5 + score, 0.05, 0.95)


def _defense_strength(defensive_metrics: Mapping[str, Any], advanced_metrics: Mapping[str, Any]) -> float:
    defensive_epa = _first_float(defensive_metrics, ["defensive_epa", "epa_allowed", "home_defensive_epa", "away_defensive_epa"])
    success_rate_allowed = _first_float(defensive_metrics, ["success_rate_allowed", "home_success_rate_allowed", "away_success_rate_allowed"])
    pressure = _first_float(advanced_metrics, ["def_pressure_avg"])
    advanced_def_epa = _first_float(advanced_metrics, ["home_defensive_epa", "away_defensive_epa", "defensive_epa"])

    score = 0.0
    score += (-1.0 * (defensive_epa or 0.0)) * 0.55
    score += (0.5 - (success_rate_allowed or 0.5)) * 1.2
    score += (pressure or 0.0) * 0.22
    score += (-1.0 * (advanced_def_epa or 0.0)) * 0.35
    return _clamp(0.5 + score, 0.05, 0.95)


def _pace_index(pace: Mapping[str, Any]) -> tuple[float, float]:
    pace_seconds = _first_float(pace, ["pace_seconds_per_play", "secs_per_play", "home_pace_secs_play", "away_pace_secs_play"])
    if pace_seconds is None:
        pace_seconds = 24.0
    pace_index = _clamp((28.0 - pace_seconds) / 10.0, -1.0, 1.0)
    return pace_index, pace_seconds


def _player_usage_index(player_usage: Mapping[str, Any]) -> float:
    usage = _mean_float(player_usage.get("usage_index"))
    if usage is not None:
        return _clamp(usage, 0.0, 1.0)
    fields = [
        _first_float(player_usage, ["snap_share", "snap_pct", "snap_rate"]),
        _first_float(player_usage, ["target_share", "target_pct"]),
        _first_float(player_usage, ["route_participation", "route_pct"]),
        _first_float(player_usage, ["carry_share", "rush_pct"]),
        _first_float(player_usage, ["air_yard_share", "air_yards_pct"]),
    ]
    samples = [field for field in fields if field is not None]
    if not samples:
        return 0.25
    return _clamp(sum(samples) / float(len(samples)), 0.0, 1.0)


def _returning_index(returning_production: Mapping[str, Any]) -> float:
    value = _first_float(returning_production, ["percent_ppa", "returning_production", "summary_value"])
    if value is None:
        return 0.5
    return _clamp(value, 0.0, 1.0)


def _coach_index(coach_continuity: Mapping[str, Any]) -> float:
    value = _first_float(coach_continuity, ["continuity_score", "score"])
    if value is None:
        return 0.5
    return _clamp(value, 0.0, 1.0)


def _transfer_volatility(transfer_impact: Mapping[str, Any]) -> float:
    if not transfer_impact:
        return 0.2
    net = _first_float(transfer_impact, ["net", "impact", "volatility", "transfer_net"])
    if net is None:
        incoming = _first_float(transfer_impact, ["incoming"])
        outgoing = _first_float(transfer_impact, ["outgoing"])
        if incoming is None and outgoing is None:
            return 0.2
        net = float(abs((incoming or 0.0) - (outgoing or 0.0)))
    return _clamp(abs(net) / 20.0, 0.0, 1.0)


def _market_prior_index(market_features: Mapping[str, Any]) -> float:
    total = market_features.get("total") if isinstance(market_features.get("total"), Mapping) else {}
    spread = market_features.get("spread") if isinstance(market_features.get("spread"), Mapping) else {}
    moneyline = market_features.get("moneyline") if isinstance(market_features.get("moneyline"), Mapping) else {}
    confidence = _first_float(market_features, ["model_probability", "confidence", "edge"])
    total_line = _first_float(total, ["line", "total", "value"])
    spread_line = _first_float(spread, ["home_line", "away_line", "line"])
    moneyline_home = _first_float(moneyline, ["home"])

    score = 0.5
    score += ((total_line or 48.0) - 48.0) / 50.0
    score += abs(spread_line or 0.0) / 40.0
    score += ((confidence or 0.5) - 0.5) * 0.5
    score += ((moneyline_home or 0.0) / 500.0)
    return _clamp(score, 0.0, 1.0)


def build_drive_priors(source: SmartSim2SimulationInput | Mapping[str, Any], *, possession_state: PossessionState | None = None) -> DrivePriorProfile:
    if isinstance(source, SmartSim2SimulationInput):
        payload = _copy_mapping(source.feature_generation_payload)
        fallback_offense = _clamp(0.5 + float(source.home_offense_rating or 0.0), 0.05, 0.95)
        fallback_defense = _clamp(0.5 + float(source.home_defense_rating or 0.0), 0.05, 0.95)
    else:
        payload = _copy_mapping(source)
        fallback_offense = 0.5
        fallback_defense = 0.5

    sources = _sources_from_payload(payload)
    offensive_metrics = _extract_block(sources, ["offensive_metrics", "offense_metrics", "team_metrics", "offense", "offensive"])
    defensive_metrics = _extract_block(sources, ["defensive_metrics", "defense_metrics", "defense", "defensive"])
    pace = _extract_block(sources, ["pace", "pace_features", "tempo", "clock"])
    advanced_metrics = _extract_block(sources, ["advanced_metrics", "advanced", "game_metrics"])
    player_usage = _extract_block(sources, ["player_usage", "usage", "players"])
    market_features = _extract_block(sources, ["market_features", "market", "betting"])
    returning_production = _extract_block(sources, ["returning_production", "returning", "returning_metrics"])
    coach_continuity = _extract_block(sources, ["coach_continuity", "coach", "continuity"])
    transfer_impact = _extract_block(sources, ["transfer_impact", "transfer", "portal"])

    offense_index = _offense_strength(offensive_metrics, advanced_metrics, player_usage, returning_production, coach_continuity)
    defense_index = _defense_strength(defensive_metrics, advanced_metrics)
    pace_index, pace_seconds = _pace_index(pace)
    player_usage_index = _player_usage_index(player_usage)
    returning_index = _returning_index(returning_production)
    coach_index = _coach_index(coach_continuity)
    transfer_volatility = _transfer_volatility(transfer_impact)
    market_prior_index = _market_prior_index(market_features)

    offense_index = _clamp((offense_index + fallback_offense) / 2.0, 0.05, 0.95)
    defense_index = _clamp((defense_index + fallback_defense) / 2.0, 0.05, 0.95)

    aggressiveness = _clamp(0.5 + pace_index * 0.15 + (coach_index - 0.5) * 0.12 + (0.5 - transfer_volatility) * 0.08, 0.05, 0.95)
    scoring_environment = _clamp(0.35 + market_prior_index * 0.35 + offense_index * 0.18 - defense_index * 0.08, 0.05, 0.95)
    drive_success_probability = _clamp(
        0.24
        + offense_index * 0.28
        + returning_index * 0.06
        + coach_index * 0.04
        + market_prior_index * 0.03
        - defense_index * 0.22
        - transfer_volatility * 0.04,
        0.08,
        0.82,
    )
    turnover_probability = _clamp(
        0.05
        + defense_index * 0.10
        + transfer_volatility * 0.06
        + (0.5 - offense_index) * 0.04
        + (1.0 - aggressiveness) * 0.02,
        0.025,
        0.20,
    )
    explosive_play_probability = _clamp(
        0.06
        + offense_index * 0.14
        + player_usage_index * 0.06
        + pace_index * 0.04
        - defense_index * 0.05,
        0.02,
        0.30,
    )
    field_goal_probability = _clamp(
        0.05
        + drive_success_probability * 0.08
        + scoring_environment * 0.08
        + defense_index * 0.03
        - turnover_probability * 0.03,
        0.04,
        0.22,
    )
    punt_probability = _clamp(
        0.24
        + (1.0 - drive_success_probability) * 0.28
        + defense_index * 0.10
        - explosive_play_probability * 0.04
        - field_goal_probability * 0.02,
        0.12,
        0.65,
    )
    touchdown_probability = _clamp(
        drive_success_probability * (0.42 + offense_index * 0.10 + scoring_environment * 0.08),
        0.03,
        0.60,
    )
    no_score_probability = _clamp(
        1.0 - min(0.88, touchdown_probability + field_goal_probability),
        0.08,
        0.90,
    )
    red_zone_touchdown_probability = _clamp(touchdown_probability + offense_index * 0.06 - defense_index * 0.04, 0.06, 0.82)
    red_zone_field_goal_probability = _clamp(field_goal_probability + defense_index * 0.03, 0.04, 0.60)
    expected_play_count = _clamp(4.6 + (1.0 - pace_index) * 1.6 + (0.60 - aggressiveness) * 0.9 + (1.0 - drive_success_probability) * 1.1, 3.5, 8.5)
    expected_clock_seconds = _clamp(expected_play_count * pace_seconds, 18.0, 240.0)
    expected_field_position_gain = _clamp(8.0 + offense_index * 10.0 - defense_index * 5.0 + explosive_play_probability * 8.0, 1.0, 35.0)

    summary = {
        "offensive_metrics": offensive_metrics,
        "defensive_metrics": defensive_metrics,
        "pace": pace,
        "advanced_metrics": advanced_metrics,
        "player_usage": player_usage,
        "market_features": market_features,
        "returning_production": returning_production,
        "coach_continuity": coach_continuity,
        "transfer_impact": transfer_impact,
        "possession_state": possession_state.to_dict() if possession_state is not None else None,
    }
    return DrivePriorProfile(
        offense_index=round(offense_index, 4),
        defense_index=round(defense_index, 4),
        pace_index=round(pace_index, 4),
        returning_production_index=round(returning_index, 4),
        coach_continuity_index=round(coach_index, 4),
        transfer_volatility_index=round(transfer_volatility, 4),
        player_usage_index=round(player_usage_index, 4),
        market_prior_index=round(market_prior_index, 4),
        pace_seconds_per_play=round(pace_seconds, 4),
        drive_success_probability=round(drive_success_probability, 4),
        turnover_probability=round(turnover_probability, 4),
        explosive_play_probability=round(explosive_play_probability, 4),
        field_goal_probability=round(field_goal_probability, 4),
        punt_probability=round(punt_probability, 4),
        touchdown_probability=round(touchdown_probability, 4),
        no_score_probability=round(no_score_probability, 4),
        red_zone_touchdown_probability=round(red_zone_touchdown_probability, 4),
        red_zone_field_goal_probability=round(red_zone_field_goal_probability, 4),
        expected_play_count=round(expected_play_count, 4),
        expected_clock_seconds=round(expected_clock_seconds, 4),
        expected_field_position_gain=round(expected_field_position_gain, 4),
        feature_summary=summary,
    )


def drive_outcome_distribution(state: PossessionState, priors: DrivePriorProfile) -> dict[str, float]:
    field_position_factor = _clamp((state.field_position - 20) / 80.0, 0.0, 1.0)
    red_zone = 1.0 if state.field_position >= 80 else 0.0
    short_field = 1.0 if state.field_position >= 60 else 0.0
    long_distance = _clamp((state.distance - 5) / 10.0, 0.0, 1.0)
    late_down = 1.0 if state.down >= 3 else 0.0
    score_gap = (state.score_away - state.score_home) if state.possession_owner == "home" else (state.score_home - state.score_away)
    trailing = _clamp(score_gap / 21.0, 0.0, 1.0)
    leading = _clamp((-score_gap) / 21.0, 0.0, 1.0)

    touchdown = priors.touchdown_probability * (0.42 + field_position_factor * 0.45 + red_zone * 0.30 + trailing * 0.08)
    field_goal = priors.field_goal_probability * (0.48 + field_position_factor * 0.34 + short_field * 0.12 + red_zone * 0.10)
    missed_field_goal = field_goal * _clamp(0.42 + (1.0 - field_position_factor) * 0.18, 0.22, 0.62)
    field_goal = max(0.01, field_goal - missed_field_goal)
    punt = priors.punt_probability * (1.18 - field_position_factor * 0.30 + leading * 0.08 + long_distance * 0.06)
    turnover = priors.turnover_probability * (0.55 + long_distance * 0.20 + late_down * 0.10 + trailing * 0.04)
    turnover_on_downs = (1.0 - priors.drive_success_probability) * (0.14 + long_distance * 0.18 + late_down * 0.16)

    if red_zone > 0.0:
        touchdown *= priors.red_zone_touchdown_probability / max(0.01, priors.touchdown_probability)
        field_goal *= priors.red_zone_field_goal_probability / max(0.01, priors.field_goal_probability)

    weights = {
        "touchdown": max(0.01, touchdown),
        "field_goal": max(0.01, field_goal),
        "missed_field_goal": max(0.01, missed_field_goal),
        "punt": max(0.01, punt),
        "turnover": max(0.01, turnover),
        "turnover_on_downs": max(0.01, turnover_on_downs),
    }
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


__all__ = ["DrivePriorProfile", "build_drive_priors", "drive_outcome_distribution"]