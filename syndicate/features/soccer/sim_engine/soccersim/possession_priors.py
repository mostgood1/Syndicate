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


def _first_float(payload: Mapping[str, Any], keys: list[str], *, side: str | None = None) -> float | None:
    """First numeric hit, preferring this SIDE's copy of the key.

    `feature_generation_payload` is ONE dict for the whole match, but
    `build_possession_priors` runs per possession owner. Without `side`, a
    single `xg_for_per_match` is read for both teams -- so whichever side is
    on the ball gets scored with the same team's xG. A wrong number is worse
    than the neutral default it replaces, which is why the payload sat unfed
    rather than being wired naively.

    The key lists already carried `home_xg_for` / `away_xg_for` as fallbacks,
    which is the shape this restores: try `{side}_{key}` first, then the bare
    key, so a match-level metric (tempo, market) still resolves for both sides
    while a per-team metric resolves to the right team.
    """
    for key in keys:
        if side:
            numeric = _safe_float(payload.get(f"{side}_{key}"))
            if numeric is not None:
                return numeric
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


def _attack_strength(attacking_metrics: Mapping[str, Any], set_piece_metrics: Mapping[str, Any], form_metrics: Mapping[str, Any], *, side: str | None = None) -> float:
    # NO xg TERM HERE. `build_possession_priors` averages this index with
    # `fallback_attack = 0.5 + attack_rating`, and `attack_rating` IS xG --
    # `(xg_for / league_mean - 1.0) * _RATING_SCALE` in `compute_team_ratings`.
    # Measured on eredivisie (22 teams, 918 matches): corr(attack_rating,
    # xg_for) = +0.984, and xG accounted for 0.5546 of the combined
    # attack_index spread of 0.6728 -- **82% of the index was one signal
    # arriving through two routes**.
    #
    # A model whose measured defect is UNDER-DISPERSION (stdev 0.1575 vs market
    # 0.1811) does not need the same evidence twice: that raises confidence
    # without adding information, which moves the spread the right way for the
    # wrong reason and degrades calibration. CLAUDE.md's "mechanism vs
    # estimator" rule, measured -- two mechanisms produced a NEGATIVE
    # interaction in 4 of 4 MLB markets.
    #
    # The remaining terms are kept because they are what this block can add
    # that the rating cannot. `shots` is the weakest of them
    # (corr(xg_for, shots) = +0.895) and is a candidate for the same treatment
    # if a re-fit shows it earning nothing.
    shots = _first_float(attacking_metrics, ["shots_per_match", "shots", "home_shots", "away_shots"], side=side)
    big_chances = _first_float(attacking_metrics, ["big_chances_per_match", "big_chances"], side=side)
    goals = _first_float(attacking_metrics, ["goals_per_match", "goals_for_per_match", "goals_for"], side=side)
    set_piece_share = _first_float(set_piece_metrics, ["set_piece_xg_share", "set_piece_goal_share"], side=side)
    form_points = _first_float(form_metrics, ["points_per_match", "recent_points_per_match", "form_points"], side=side)

    score = 0.0
    score += ((shots or 12.5) - 12.5) * 0.016
    score += ((big_chances or 2.2) - 2.2) * 0.04
    score += ((goals or 1.35) - 1.35) * 0.14
    score += ((set_piece_share or 0.30) - 0.30) * 0.20
    score += ((form_points or 1.35) - 1.35) * 0.06
    return _clamp(0.5 + score, 0.05, 0.95)


def _defense_strength(defensive_metrics: Mapping[str, Any], *, side: str | None = None) -> float:
    # NO xg_against TERM HERE, for the same reason the attack block has no xg
    # term -- and the collinearity is even starker on this side.
    # `build_possession_priors` averages this index with
    # `fallback_defense = 0.5 + defense_rating`, and `defense_rating` is
    # `(1.0 - xg_against / league_mean) * _RATING_SCALE`: a linear transform of
    # `xg_against` and nothing else.
    #
    # Measured on eredivisie (22 teams, 918 matches):
    # **corr(defense_rating, xg_against) = -1.000, exactly**, and xG accounted
    # for 0.3274 of the 0.4181 combined defense_index spread -- 78% of the index
    # from one signal arriving twice.
    #
    # DROPPED IN THE SAME COMMIT AS THE ATTACK TERM ON PURPOSE. Fixing one side
    # alone leaves the model counting defensive evidence twice and offensive
    # evidence once, which systematically favours the defending side -- a NEW
    # bias, arguably worse than the symmetric double-count it replaces. The two
    # terms are structurally identical and had to move together.
    shots_allowed = _first_float(defensive_metrics, ["shots_allowed_per_match", "shots_allowed", "shots_against"], side=side)
    goals_against = _first_float(defensive_metrics, ["goals_against_per_match", "goals_against"], side=side)
    clean_sheet_rate = _first_float(defensive_metrics, ["clean_sheet_rate", "clean_sheets_per_match"], side=side)

    score = 0.0
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


def _possession_share(possession_metrics: Mapping[str, Any], *, side: str | None = None) -> float:
    share = _first_float(possession_metrics, ["possession_share", "possession_pct", "possession"], side=side)
    if share is None:
        return 0.5
    if share > 1.0:
        share = share / 100.0
    return _clamp(share, 0.20, 0.80)


def _pressing_index(defensive_metrics: Mapping[str, Any], possession_metrics: Mapping[str, Any], *, side: str | None = None) -> float:
    ppda = _first_float(defensive_metrics, ["ppda", "passes_per_defensive_action"], side=side)
    if ppda is None:
        ppda = _first_float(possession_metrics, ["ppda"], side=side)
    if ppda is None:
        return 0.5
    # Lower PPDA means more aggressive pressing; league-average is ~11.
    return _clamp(0.5 + (11.0 - ppda) * 0.06, 0.05, 0.95)


def _set_piece_index(set_piece_metrics: Mapping[str, Any], *, side: str | None = None) -> float:
    share = _first_float(set_piece_metrics, ["set_piece_xg_share", "set_piece_goal_share"], side=side)
    corners = _first_float(set_piece_metrics, ["corners_per_match", "corners"], side=side)
    score = 0.0
    score += ((share or 0.30) - 0.30) * 0.8
    score += ((corners or 5.0) - 5.0) * 0.03
    return _clamp(0.5 + score, 0.05, 0.95)


def _availability_index(availability_metrics: Mapping[str, Any], *, side: str | None = None) -> float:
    value = _first_float(availability_metrics, ["availability_index", "squad_availability", "starters_available_share"], side=side)
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

    # SIDE SELECTION MIRRORS THE RATING SELECTION ABOVE, which already takes
    # the owner's attack against the OPPONENT's defence. Attack, possession,
    # set pieces and availability describe the team on the ball; defence and
    # pressing describe the team it is playing against.
    opponent = "away" if owner == "home" else "home"
    attack_index = _attack_strength(attacking_metrics, set_piece_metrics, form_metrics, side=owner)
    defense_index = _defense_strength(defensive_metrics, side=opponent)
    pace_index, pace_seconds = _pace_values(tempo_metrics)
    possession_share = _possession_share(possession_metrics, side=owner)
    pressing_index = _pressing_index(defensive_metrics, possession_metrics, side=opponent)
    set_piece_index = _set_piece_index(set_piece_metrics, side=owner)
    availability_index = _availability_index(availability_metrics, side=owner)
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
