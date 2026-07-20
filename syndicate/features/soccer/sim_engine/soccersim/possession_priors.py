from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Mapping

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput


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


def _extract_block(sources: list[Mapping[str, Any]], names: list[str]) -> dict[str, Any]:
    for source in sources:
        for name in names:
            candidate = source.get(name)
            if isinstance(candidate, Mapping):
                return dict(candidate)
    return {}


def _sources_from_payload(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [payload]
    for key in ("soccer_features", "features", "feature_stack", "priors", "input_state"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            sources.append(candidate)
    return sources


@dataclass(frozen=True)
class PossessionPriorProfile:
    attack_index: float
    defense_index: float
    pace_index: float
    possession_share_index: float
    pressing_index: float
    set_piece_index: float
    availability_index: float
    market_prior_index: float
    pace_seconds_per_event: float
    possession_retention_probability: float
    shot_generation_probability: float
    shot_on_target_probability: float
    goal_conversion_probability: float
    fast_break_probability: float
    foul_won_probability: float
    corner_probability: float
    offside_probability: float
    penalty_probability: float
    expected_event_count: float
    expected_possession_seconds: float
    expected_pitch_progress: float
    feature_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_index": self.attack_index,
            "defense_index": self.defense_index,
            "pace_index": self.pace_index,
            "possession_share_index": self.possession_share_index,
            "pressing_index": self.pressing_index,
            "set_piece_index": self.set_piece_index,
            "availability_index": self.availability_index,
            "market_prior_index": self.market_prior_index,
            "pace_seconds_per_event": self.pace_seconds_per_event,
            "possession_retention_probability": self.possession_retention_probability,
            "shot_generation_probability": self.shot_generation_probability,
            "shot_on_target_probability": self.shot_on_target_probability,
            "goal_conversion_probability": self.goal_conversion_probability,
            "fast_break_probability": self.fast_break_probability,
            "foul_won_probability": self.foul_won_probability,
            "corner_probability": self.corner_probability,
            "offside_probability": self.offside_probability,
            "penalty_probability": self.penalty_probability,
            "expected_event_count": self.expected_event_count,
            "expected_possession_seconds": self.expected_possession_seconds,
            "expected_pitch_progress": self.expected_pitch_progress,
            "feature_summary": dict(self.feature_summary),
        }


def _attack_strength(attacking_metrics: Mapping[str, Any], set_piece_metrics: Mapping[str, Any], form_metrics: Mapping[str, Any]) -> float:
    xg_for = _first_float(attacking_metrics, ["xg_for_per_match", "xg_for", "xg", "home_xg_for", "away_xg_for"])
    shots = _first_float(attacking_metrics, ["shots_per_match", "shots", "home_shots", "away_shots"])
    big_chances = _first_float(attacking_metrics, ["big_chances_per_match", "big_chances"])
    goals = _first_float(attacking_metrics, ["goals_per_match", "goals_for_per_match", "goals_for"])
    set_piece_share = _first_float(set_piece_metrics, ["set_piece_xg_share", "set_piece_goal_share"])
    form_points = _first_float(form_metrics, ["points_per_match", "recent_points_per_match", "form_points"])

    score = 0.0
    score += ((xg_for or 1.35) - 1.35) * 0.22
    score += ((shots or 12.5) - 12.5) * 0.016
    score += ((big_chances or 2.2) - 2.2) * 0.04
    score += ((goals or 1.35) - 1.35) * 0.14
    score += ((set_piece_share or 0.30) - 0.30) * 0.20
    score += ((form_points or 1.35) - 1.35) * 0.06
    return _clamp(0.5 + score, 0.05, 0.95)


def _defense_strength(defensive_metrics: Mapping[str, Any]) -> float:
    xg_against = _first_float(defensive_metrics, ["xg_against_per_match", "xg_against", "home_xg_against", "away_xg_against"])
    shots_allowed = _first_float(defensive_metrics, ["shots_allowed_per_match", "shots_allowed", "shots_against"])
    goals_against = _first_float(defensive_metrics, ["goals_against_per_match", "goals_against"])
    clean_sheet_rate = _first_float(defensive_metrics, ["clean_sheet_rate", "clean_sheets_per_match"])

    score = 0.0
    score += (1.35 - (xg_against or 1.35)) * 0.22
    score += (12.5 - (shots_allowed or 12.5)) * 0.016
    score += (1.35 - (goals_against or 1.35)) * 0.14
    score += ((clean_sheet_rate or 0.30) - 0.30) * 0.30
    return _clamp(0.5 + score, 0.05, 0.95)


def _pace_values(tempo_metrics: Mapping[str, Any]) -> tuple[float, float]:
    pace_seconds = _first_float(tempo_metrics, ["pace_seconds_per_event", "seconds_per_event", "secs_per_event"])
    if pace_seconds is None:
        pace_seconds = 12.0
    pace_index = _clamp((13.5 - pace_seconds) / 5.0, -1.0, 1.0)
    return pace_index, pace_seconds


def _possession_share(possession_metrics: Mapping[str, Any]) -> float:
    share = _first_float(possession_metrics, ["possession_share", "possession_pct", "possession"])
    if share is None:
        return 0.5
    if share > 1.0:
        share = share / 100.0
    return _clamp(share, 0.20, 0.80)


def _pressing_index(defensive_metrics: Mapping[str, Any], possession_metrics: Mapping[str, Any]) -> float:
    ppda = _first_float(defensive_metrics, ["ppda", "passes_per_defensive_action"])
    if ppda is None:
        ppda = _first_float(possession_metrics, ["ppda"])
    if ppda is None:
        return 0.5
    # Lower PPDA means more aggressive pressing; league-average is ~11.
    return _clamp(0.5 + (11.0 - ppda) * 0.06, 0.05, 0.95)


def _set_piece_index(set_piece_metrics: Mapping[str, Any]) -> float:
    share = _first_float(set_piece_metrics, ["set_piece_xg_share", "set_piece_goal_share"])
    corners = _first_float(set_piece_metrics, ["corners_per_match", "corners"])
    score = 0.0
    score += ((share or 0.30) - 0.30) * 0.8
    score += ((corners or 5.0) - 5.0) * 0.03
    return _clamp(0.5 + score, 0.05, 0.95)


def _availability_index(availability_metrics: Mapping[str, Any]) -> float:
    value = _first_float(availability_metrics, ["availability_index", "squad_availability", "starters_available_share"])
    if value is None:
        return 0.5
    return _clamp(value, 0.0, 1.0)


def _market_prior_index(market_features: Mapping[str, Any]) -> float:
    total = market_features.get("total") if isinstance(market_features.get("total"), Mapping) else {}
    spread = market_features.get("spread") if isinstance(market_features.get("spread"), Mapping) else {}
    confidence = _first_float(market_features, ["model_probability", "confidence", "edge"])
    total_line = _first_float(total, ["line", "total", "value"])
    spread_line = _first_float(spread, ["home_line", "away_line", "line"])

    score = 0.5
    score += ((total_line or 2.6) - 2.6) / 3.0
    score += abs(spread_line or 0.0) / 4.0
    score += ((confidence or 0.5) - 0.5) * 0.5
    return _clamp(score, 0.0, 1.0)


def build_possession_priors(
    source: SoccerSimSimulationInput | Mapping[str, Any],
    *,
    possession_state: PossessionState | None = None,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
) -> PossessionPriorProfile:
    owner = possession_state.possession_owner if possession_state is not None else "home"
    if isinstance(source, SoccerSimSimulationInput):
        payload = _copy_mapping(source.feature_generation_payload)
        if owner == "home":
            attack_rating = float(source.home_attack_rating or 0.0)
            defense_rating = float(source.away_defense_rating or 0.0)
        else:
            attack_rating = float(source.away_attack_rating or 0.0)
            defense_rating = float(source.home_defense_rating or 0.0)
        fallback_attack = _clamp(0.5 + attack_rating, 0.05, 0.95)
        fallback_defense = _clamp(0.5 + defense_rating, 0.05, 0.95)
    else:
        payload = _copy_mapping(source)
        fallback_attack = 0.5
        fallback_defense = 0.5

    sources = _sources_from_payload(payload)
    attacking_metrics = _extract_block(sources, ["attacking_metrics", "attack_metrics", "team_metrics", "attack", "attacking"])
    defensive_metrics = _extract_block(sources, ["defensive_metrics", "defense_metrics", "defense", "defensive"])
    possession_metrics = _extract_block(sources, ["possession_metrics", "possession", "ball_progression"])
    tempo_metrics = _extract_block(sources, ["tempo", "pace", "pace_features", "clock"])
    set_piece_metrics = _extract_block(sources, ["set_piece_metrics", "set_pieces", "set_piece"])
    availability_metrics = _extract_block(sources, ["availability", "squad_availability", "rotation"])
    market_features = _extract_block(sources, ["market_features", "market", "betting"])
    form_metrics = _extract_block(sources, ["form", "recent_form", "form_metrics"])

    attack_index = _attack_strength(attacking_metrics, set_piece_metrics, form_metrics)
    defense_index = _defense_strength(defensive_metrics)
    pace_index, pace_seconds = _pace_values(tempo_metrics)
    possession_share = _possession_share(possession_metrics)
    pressing_index = _pressing_index(defensive_metrics, possession_metrics)
    set_piece_index = _set_piece_index(set_piece_metrics)
    availability_index = _availability_index(availability_metrics)
    market_prior_index = _market_prior_index(market_features)

    attack_index = _clamp((attack_index + fallback_attack) / 2.0, 0.05, 0.95)
    defense_index = _clamp((defense_index + fallback_defense) / 2.0, 0.05, 0.95)
    if owner == "home":
        attack_index = _clamp(attack_index + profile.home_advantage_attack_boost, 0.05, 0.95)

    possession_retention_probability = _clamp(
        0.50
        + attack_index * 0.18
        + (possession_share - 0.5) * 0.24
        + availability_index * 0.02
        - defense_index * 0.16,
        0.28,
        0.78,
    )
    shot_generation_probability = _clamp(
        0.085
        + attack_index * 0.16
        + set_piece_index * 0.02
        + market_prior_index * 0.02
        - defense_index * 0.09,
        0.04,
        0.34,
    )
    shot_on_target_probability = _clamp(
        0.28 + attack_index * 0.12 - defense_index * 0.06,
        0.20,
        0.50,
    )
    goal_conversion_probability = _clamp(
        0.068 + attack_index * 0.075 - defense_index * 0.045 + set_piece_index * 0.008,
        0.035,
        0.22,
    )
    fast_break_probability = _clamp(
        0.030 + pressing_index * 0.028 + pace_index * 0.015 + attack_index * 0.010,
        0.010,
        0.12,
    )
    foul_won_probability = _clamp(0.085 + (1.0 - possession_retention_probability) * 0.04, 0.05, 0.16)
    corner_probability = _clamp(0.040 + attack_index * 0.025 - defense_index * 0.015, 0.015, 0.10)
    offside_probability = _clamp(0.016 + attack_index * 0.010, 0.008, 0.045)
    penalty_probability = _clamp(0.0018 + attack_index * 0.0016 - defense_index * 0.0008, 0.0008, 0.006)
    expected_event_count = _clamp(
        3.2 + (possession_share - 0.5) * 2.4 + possession_retention_probability * 1.6 - pressing_index * 0.5,
        2.0,
        7.0,
    )
    expected_possession_seconds = _clamp(expected_event_count * pace_seconds * profile.possession_tempo_multiplier, 10.0, 120.0)
    expected_pitch_progress = _clamp(10.0 + attack_index * 12.0 - defense_index * 6.0 + fast_break_probability * 30.0, 3.0, 35.0)

    summary = {
        "attacking_metrics": attacking_metrics,
        "defensive_metrics": defensive_metrics,
        "possession_metrics": possession_metrics,
        "tempo": tempo_metrics,
        "set_piece_metrics": set_piece_metrics,
        "availability": availability_metrics,
        "market_features": market_features,
        "form": form_metrics,
        "possession_state": possession_state.to_dict() if possession_state is not None else None,
    }
    return PossessionPriorProfile(
        attack_index=round(attack_index, 4),
        defense_index=round(defense_index, 4),
        pace_index=round(pace_index, 4),
        possession_share_index=round(possession_share, 4),
        pressing_index=round(pressing_index, 4),
        set_piece_index=round(set_piece_index, 4),
        availability_index=round(availability_index, 4),
        market_prior_index=round(market_prior_index, 4),
        pace_seconds_per_event=round(pace_seconds, 4),
        possession_retention_probability=round(possession_retention_probability, 4),
        shot_generation_probability=round(shot_generation_probability, 4),
        shot_on_target_probability=round(shot_on_target_probability, 4),
        goal_conversion_probability=round(goal_conversion_probability, 4),
        fast_break_probability=round(fast_break_probability, 4),
        foul_won_probability=round(foul_won_probability, 4),
        corner_probability=round(corner_probability, 4),
        offside_probability=round(offside_probability, 4),
        penalty_probability=round(penalty_probability, 4),
        expected_event_count=round(expected_event_count, 4),
        expected_possession_seconds=round(expected_possession_seconds, 4),
        expected_pitch_progress=round(expected_pitch_progress, 4),
        feature_summary=summary,
    )


def possession_outcome_distribution(state: PossessionState, priors: PossessionPriorProfile) -> dict[str, float]:
    """Static per-possession terminal-outcome distribution for a given state.

    A diagnostic analog of the Football Core's drive_outcome_distribution:
    it does not run the event loop, it summarizes what the priors imply for
    a possession starting from ``state``.
    """
    field_factor = _clamp((state.pitch_position - 30) / 70.0, 0.0, 1.0)
    shot = priors.shot_generation_probability * (0.75 + field_factor * 0.9)
    goal = shot * priors.goal_conversion_probability * (0.8 + field_factor * 0.5)
    saved = shot * priors.shot_on_target_probability * (1.0 - priors.goal_conversion_probability)
    off_target = max(0.01, shot - goal - saved)
    turnover = (1.0 - priors.possession_retention_probability) * (0.9 - field_factor * 0.2)
    offside = priors.offside_probability * (0.6 + field_factor * 0.8)

    weights = {
        "goal": max(0.005, goal),
        "shot_saved": max(0.01, saved),
        "shot_off_target": max(0.01, off_target),
        "turnover": max(0.05, turnover),
        "offside": max(0.005, offside),
    }
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


__all__ = ["PossessionPriorProfile", "build_possession_priors", "possession_outcome_distribution"]
