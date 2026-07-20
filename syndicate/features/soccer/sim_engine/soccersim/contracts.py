from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any
from typing import Mapping


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _serialize(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class PossessionOutcome(str, Enum):
    # Step-level (non-terminal) outcomes.
    ADVANCE = "advance"
    FAST_BREAK = "fast_break"
    RETAIN = "retain"
    FOUL_WON = "foul_won"
    CORNER_WON = "corner_won"
    # Terminal possession outcomes.
    GOAL = "goal"
    PENALTY_GOAL = "penalty_goal"
    PENALTY_MISSED = "penalty_missed"
    SHOT_SAVED = "shot_saved"
    SHOT_OFF_TARGET = "shot_off_target"
    SHOT_BLOCKED = "shot_blocked"
    TURNOVER = "turnover"
    OFFSIDE = "offside"
    END_OF_HALF_STOP = "end_of_half_stop"
    END_OF_MATCH_STOP = "end_of_match_stop"


@dataclass(frozen=True)
class PossessionState:
    possession_owner: str
    pitch_position: int
    phase: str
    half: int
    clock_remaining: int
    possession_index: int = 0
    score_home: int = 0
    score_away: int = 0
    home_team: str = "HOME"
    away_team: str = "AWAY"

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class PossessionStepResult:
    step_index: int
    start_state: PossessionState
    end_state: PossessionState
    outcome: PossessionOutcome
    pitch_progress: int = 0
    clock_consumed: int = 0
    goals_scored: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class PossessionResult:
    possession_index: int
    start_state: PossessionState
    end_state: PossessionState
    outcome: PossessionOutcome
    goals_scored: int = 0
    pitch_progress: int = 0
    clock_consumed: int = 0
    event_count: int = 0
    shot_taken: bool = False
    shot_on_target: bool = False
    corner_count: int = 0
    reached_final_third: bool = False
    reached_penalty_box: bool = False
    possession_change: bool = False
    next_possession_owner: str = ""
    steps: tuple[PossessionStepResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class HalfResult:
    half: int
    start_clock: int
    end_clock: int
    stoppage_seconds: int
    home_goals: int
    away_goals: int
    possession_count: int
    shot_count: int

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class SoccerSimSimulationInput:
    home_team: str
    away_team: str
    seed: int | None = None
    halves: int = 2
    half_seconds: int = 2700
    home_attack_rating: float = 0.0
    home_defense_rating: float = 0.0
    away_attack_rating: float = 0.0
    away_defense_rating: float = 0.0
    pace_seconds_per_event: float = 12.0
    initial_pitch_position: int = 50
    initial_possession_owner: str = "home"
    knockout: bool = False
    feature_generation_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class SoccerSimSimulationOutput:
    simulation_kind: str
    seed: int | None
    input_state: dict[str, Any]
    event_log: tuple[dict[str, Any], ...]
    possession_log: tuple[dict[str, Any], ...]
    half_log: tuple[dict[str, Any], ...]
    final_score: dict[str, int]
    win_probability: dict[str, float]
    spread: dict[str, float]
    total: dict[str, float]
    distribution_summary: dict[str, Any]
    compatibility_summary: dict[str, Any]
    final_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


MatchResult = SoccerSimSimulationOutput
SimulationOutput = SoccerSimSimulationOutput
