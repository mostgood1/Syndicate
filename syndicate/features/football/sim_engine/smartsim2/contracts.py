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
    GAIN = "gain"
    EXPLOSIVE_GAIN = "explosive_gain"
    SACK = "sack"
    PENALTY = "penalty"
    INCOMPLETE_PASS = "incomplete_pass"
    FIELD_GOAL_ATTEMPT = "field_goal_attempt"
    TOUCHDOWN = "touchdown"
    FIELD_GOAL = "field_goal"
    MISSED_FIELD_GOAL = "missed_field_goal"
    PUNT = "punt"
    TURNOVER = "turnover"
    TURNOVER_ON_DOWNS = "turnover_on_downs"
    END_OF_QUARTER_STOP = "end_of_quarter_stop"
    END_OF_HALF_STOP = "end_of_half_stop"


@dataclass(frozen=True)
class PossessionState:
    possession_owner: str
    field_position: int
    down: int
    distance: int
    quarter: int
    clock_remaining: int
    drive_index: int = 0
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
    yards_gained: int = 0
    clock_consumed: int = 0
    points_scored: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class DriveResult:
    drive_index: int
    possession_index: int
    start_state: PossessionState
    end_state: PossessionState
    outcome: PossessionOutcome
    points_scored: int = 0
    yards_gained: int = 0
    clock_consumed: int = 0
    play_count: int = 0
    possession_change: bool = False
    next_possession_owner: str = ""
    steps: tuple[PossessionStepResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class QuarterResult:
    quarter: int
    start_clock: int
    end_clock: int
    home_points: int
    away_points: int
    drive_count: int
    possession_count: int

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class SmartSim2SimulationInput:
    home_team: str
    away_team: str
    seed: int | None = None
    quarters: int = 4
    quarter_seconds: int = 900
    home_offense_rating: float = 0.0
    home_defense_rating: float = 0.0
    away_offense_rating: float = 0.0
    away_defense_rating: float = 0.0
    pace_seconds_per_play: float = 24.0
    initial_field_position: int = 25
    initial_down: int = 1
    initial_distance: int = 10
    initial_possession_owner: str = "home"
    feature_generation_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class SmartSim2SimulationOutput:
    simulation_kind: str
    seed: int | None
    input_state: dict[str, Any]
    possession_log: tuple[dict[str, Any], ...]
    drive_log: tuple[dict[str, Any], ...]
    quarter_log: tuple[dict[str, Any], ...]
    final_score: dict[str, int]
    win_probability: dict[str, float]
    spread: dict[str, float]
    total: dict[str, float]
    distribution_summary: dict[str, Any]
    compatibility_summary: dict[str, Any]
    final_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


GameResult = SmartSim2SimulationOutput
SimulationOutput = SmartSim2SimulationOutput