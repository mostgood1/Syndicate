from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome


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
class BenchmarkDriveRecord:
    drive_id: str
    game_id: str
    offense_team: str
    defense_team: str
    season: int | None = None
    week: int | None = None
    quarter: int = 1
    down_start: int = 1
    distance_start: int = 10
    field_position_start: int = 25
    field_position_end: int = 25
    plays: int = 0
    seconds: int = 0
    yards: int = 0
    points: int = 0
    outcome: PossessionOutcome = PossessionOutcome.END_OF_QUARTER_STOP
    red_zone_entry: bool = False
    goal_to_go: bool = False
    turnover: bool = False
    field_goal_attempt: bool = False
    punt: bool = False
    touchdown: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "drive_id": self.drive_id,
            "game_id": self.game_id,
            "offense_team": self.offense_team,
            "defense_team": self.defense_team,
            "season": self.season,
            "week": self.week,
            "quarter": self.quarter,
            "down_start": self.down_start,
            "distance_start": self.distance_start,
            "field_position_start": self.field_position_start,
            "field_position_end": self.field_position_end,
            "plays": self.plays,
            "seconds": self.seconds,
            "yards": self.yards,
            "points": self.points,
            "outcome": self.outcome.value,
            "red_zone_entry": self.red_zone_entry,
            "goal_to_go": self.goal_to_go,
            "turnover": self.turnover,
            "field_goal_attempt": self.field_goal_attempt,
            "punt": self.punt,
            "touchdown": self.touchdown,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BenchmarkGameRecord:
    game_id: str
    home_team: str
    away_team: str
    season: int | None = None
    week: int | None = None
    home_points: int = 0
    away_points: int = 0
    quarter_home_points: tuple[int, int, int, int] = (0, 0, 0, 0)
    quarter_away_points: tuple[int, int, int, int] = (0, 0, 0, 0)
    possessions: int = 0
    drives: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_points(self) -> int:
        return self.home_points + self.away_points

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "season": self.season,
            "week": self.week,
            "home_points": self.home_points,
            "away_points": self.away_points,
            "quarter_home_points": list(self.quarter_home_points),
            "quarter_away_points": list(self.quarter_away_points),
            "possessions": self.possessions,
            "drives": self.drives,
            "total_points": self.total_points,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CalibrationBenchmarkSnapshot:
    split: CalibrationSplit
    source_name: str
    drive_records: tuple[BenchmarkDriveRecord, ...] = ()
    game_records: tuple[BenchmarkGameRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split.value,
            "source_name": self.source_name,
            "drive_records": [record.to_dict() for record in self.drive_records],
            "game_records": [record.to_dict() for record in self.game_records],
            "metadata": dict(self.metadata),
        }


__all__ = [
    "BenchmarkDriveRecord",
    "BenchmarkGameRecord",
    "CalibrationBenchmarkSnapshot",
    "CalibrationSplit",
    "CalibrationTarget",
]
