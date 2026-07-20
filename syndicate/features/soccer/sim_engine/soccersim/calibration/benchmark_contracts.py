from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionOutcome


class CalibrationSplit(str, Enum):
    CALIBRATION = "calibration"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


@dataclass(frozen=True)
class CalibrationTarget:
    name: str
    benchmark_value: float
    simulated_value: float
    unit: str = ""
    sample_size: int = 0
    direction: str = "lower_is_better"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "benchmark_value": self.benchmark_value,
            "simulated_value": self.simulated_value,
            "unit": self.unit,
            "sample_size": self.sample_size,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class BenchmarkPossessionRecord:
    possession_id: str
    match_id: str
    attacking_team: str
    defending_team: str
    season: int | None = None
    half: int = 1
    pitch_position_start: int = 50
    pitch_position_end: int = 50
    events: int = 0
    seconds: int = 0
    progress: int = 0
    goals: int = 0
    outcome: PossessionOutcome = PossessionOutcome.TURNOVER
    shot_taken: bool = False
    shot_on_target: bool = False
    corner_count: int = 0
    reached_final_third: bool = False
    reached_penalty_box: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "possession_id": self.possession_id,
            "match_id": self.match_id,
            "attacking_team": self.attacking_team,
            "defending_team": self.defending_team,
            "season": self.season,
            "half": self.half,
            "pitch_position_start": self.pitch_position_start,
            "pitch_position_end": self.pitch_position_end,
            "events": self.events,
            "seconds": self.seconds,
            "progress": self.progress,
            "goals": self.goals,
            "outcome": self.outcome.value,
            "shot_taken": self.shot_taken,
            "shot_on_target": self.shot_on_target,
            "corner_count": self.corner_count,
            "reached_final_third": self.reached_final_third,
            "reached_penalty_box": self.reached_penalty_box,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BenchmarkMatchRecord:
    match_id: str
    home_team: str
    away_team: str
    season: int | None = None
    home_goals: int = 0
    away_goals: int = 0
    half_home_goals: tuple[int, int] = (0, 0)
    half_away_goals: tuple[int, int] = (0, 0)
    possessions: int = 0
    shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "season": self.season,
            "home_goals": self.home_goals,
            "away_goals": self.away_goals,
            "half_home_goals": list(self.half_home_goals),
            "half_away_goals": list(self.half_away_goals),
            "possessions": self.possessions,
            "shots": self.shots,
            "shots_on_target": self.shots_on_target,
            "corners": self.corners,
            "total_goals": self.total_goals,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CalibrationBenchmarkSnapshot:
    split: CalibrationSplit
    source_name: str
    possession_records: tuple[BenchmarkPossessionRecord, ...] = ()
    match_records: tuple[BenchmarkMatchRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split.value,
            "source_name": self.source_name,
            "possession_records": [record.to_dict() for record in self.possession_records],
            "match_records": [record.to_dict() for record in self.match_records],
            "metadata": dict(self.metadata),
        }


__all__ = [
    "BenchmarkMatchRecord",
    "BenchmarkPossessionRecord",
    "CalibrationBenchmarkSnapshot",
    "CalibrationSplit",
    "CalibrationTarget",
]
