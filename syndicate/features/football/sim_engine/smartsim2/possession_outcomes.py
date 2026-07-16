from __future__ import annotations

from dataclasses import dataclass
from random import Random

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState


def is_terminal_outcome(outcome: PossessionOutcome) -> bool:
    return outcome in {
        PossessionOutcome.TOUCHDOWN,
        PossessionOutcome.FIELD_GOAL,
        PossessionOutcome.PUNT,
        PossessionOutcome.TURNOVER,
        PossessionOutcome.TURNOVER_ON_DOWNS,
    }


def score_for_outcome(outcome: PossessionOutcome) -> int:
    if outcome == PossessionOutcome.TOUCHDOWN:
        return 7
    if outcome == PossessionOutcome.FIELD_GOAL:
        return 3
    return 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def possession_probabilities(
    state: PossessionState,
    *,
    offense_rating: float = 0.0,
    defense_rating: float = 0.0,
) -> dict[PossessionOutcome, float]:
    field_ratio = _clamp((state.field_position - 20) / 80.0, 0.0, 1.0)
    down_pressure = (state.down - 1) * 0.05
    distance_pressure = _clamp((state.distance - 5) / 15.0, 0.0, 1.0) * 0.08
    offense_bonus = offense_rating * 0.06
    defense_bonus = defense_rating * 0.05

    touchdown = _clamp(0.06 + (field_ratio * 0.26) + offense_bonus - defense_bonus, 0.03, 0.46)
    field_goal = _clamp(0.08 + (field_ratio * 0.14) + offense_bonus * 0.4 - defense_bonus * 0.3, 0.04, 0.28)
    turnover = _clamp(0.05 + down_pressure + distance_pressure + defense_bonus * 0.8 - offense_bonus * 0.25, 0.03, 0.22)
    punt = _clamp(0.18 + (1.0 - field_ratio) * 0.28 + distance_pressure * 0.5, 0.12, 0.55)
    turnover_on_downs = _clamp(0.08 + down_pressure * 0.9 + distance_pressure * 0.4, 0.05, 0.22)

    total = touchdown + field_goal + turnover + punt + turnover_on_downs
    return {
        PossessionOutcome.TOUCHDOWN: touchdown / total,
        PossessionOutcome.FIELD_GOAL: field_goal / total,
        PossessionOutcome.TURNOVER: turnover / total,
        PossessionOutcome.PUNT: punt / total,
        PossessionOutcome.TURNOVER_ON_DOWNS: turnover_on_downs / total,
    }


def choose_possession_outcome(
    state: PossessionState,
    *,
    rng: Random,
    offense_rating: float = 0.0,
    defense_rating: float = 0.0,
) -> PossessionOutcome:
    probabilities = possession_probabilities(state, offense_rating=offense_rating, defense_rating=defense_rating)
    roll = rng.random()
    cursor = 0.0
    for outcome, probability in probabilities.items():
        cursor += probability
        if roll <= cursor:
            return outcome
    return PossessionOutcome.TURNOVER_ON_DOWNS


@dataclass(frozen=True)
class OutcomeResolution:
    outcome: PossessionOutcome
    points: int
    possession_change: bool
    turnover: bool = False


def classify_outcome(outcome: PossessionOutcome) -> OutcomeResolution:
    if outcome == PossessionOutcome.TOUCHDOWN:
        return OutcomeResolution(outcome=outcome, points=7, possession_change=True)
    if outcome == PossessionOutcome.FIELD_GOAL:
        return OutcomeResolution(outcome=outcome, points=3, possession_change=True)
    if outcome == PossessionOutcome.PUNT:
        return OutcomeResolution(outcome=outcome, points=0, possession_change=True)
    if outcome == PossessionOutcome.TURNOVER:
        return OutcomeResolution(outcome=outcome, points=0, possession_change=True, turnover=True)
    if outcome == PossessionOutcome.TURNOVER_ON_DOWNS:
        return OutcomeResolution(outcome=outcome, points=0, possession_change=True, turnover=True)
    return OutcomeResolution(outcome=outcome, points=0, possession_change=False)
