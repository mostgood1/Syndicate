"""Contracts for the SmartSim 2.0 historical truth layer.

The truth layer replaces the synthetic proxy benchmark with measured
drive/play-level football history while preserving the shared SmartSim
Football Core architecture: truth snapshots adapt into the existing
``CalibrationBenchmarkSnapshot`` contract, so the evaluator and the
simulator are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import BenchmarkDriveRecord
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import BenchmarkGameRecord
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationSplit
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome

# Canonical historical drive results.
RESULT_TOUCHDOWN = "touchdown"
RESULT_FIELD_GOAL = "field_goal"
RESULT_MISSED_FIELD_GOAL = "missed_field_goal"
RESULT_PUNT = "punt"
RESULT_TURNOVER = "turnover"
RESULT_TURNOVER_ON_DOWNS = "turnover_on_downs"
RESULT_END_OF_HALF = "end_of_half"
RESULT_SAFETY = "safety"
RESULT_OTHER = "other"

CANONICAL_RESULTS = (
    RESULT_TOUCHDOWN,
    RESULT_FIELD_GOAL,
    RESULT_MISSED_FIELD_GOAL,
    RESULT_PUNT,
    RESULT_TURNOVER,
    RESULT_TURNOVER_ON_DOWNS,
    RESULT_END_OF_HALF,
    RESULT_SAFETY,
    RESULT_OTHER,
)

_RESULT_TO_POSSESSION_OUTCOME = {
    RESULT_TOUCHDOWN: PossessionOutcome.TOUCHDOWN,
    RESULT_FIELD_GOAL: PossessionOutcome.FIELD_GOAL,
    RESULT_MISSED_FIELD_GOAL: PossessionOutcome.MISSED_FIELD_GOAL,
    RESULT_PUNT: PossessionOutcome.PUNT,
    RESULT_TURNOVER: PossessionOutcome.TURNOVER,
    RESULT_TURNOVER_ON_DOWNS: PossessionOutcome.TURNOVER_ON_DOWNS,
    RESULT_END_OF_HALF: PossessionOutcome.END_OF_HALF_STOP,
    RESULT_SAFETY: PossessionOutcome.TURNOVER,
    RESULT_OTHER: PossessionOutcome.END_OF_QUARTER_STOP,
}


@dataclass(frozen=True)
class HistoricalDriveRecord:
    drive_id: str
    game_id: str
    season: int
    week: int
    offense_team: str
    defense_team: str
    quarter_start: int
    result: str
    plays: int
    seconds: int
    yards: int
    points: int
    start_yardline_100: int  # distance from opponent goal at drive start (100 = own goal line)
    red_zone_entry: bool
    goal_to_go_entry: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def field_position_start(self) -> int:
        """Offense-perspective field position (1-99, higher = closer to scoring)."""
        return max(1, min(99, 100 - int(self.start_yardline_100)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "drive_id": self.drive_id,
            "game_id": self.game_id,
            "season": self.season,
            "week": self.week,
            "offense_team": self.offense_team,
            "defense_team": self.defense_team,
            "quarter_start": self.quarter_start,
            "result": self.result,
            "plays": self.plays,
            "seconds": self.seconds,
            "yards": self.yards,
            "points": self.points,
            "start_yardline_100": self.start_yardline_100,
            "red_zone_entry": self.red_zone_entry,
            "goal_to_go_entry": self.goal_to_go_entry,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HistoricalGameRecord:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    quarter_home_points: tuple[int, int, int, int]
    quarter_away_points: tuple[int, int, int, int]
    drives: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_points(self) -> int:
        return self.home_points + self.away_points

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "season": self.season,
            "week": self.week,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_points": self.home_points,
            "away_points": self.away_points,
            "quarter_home_points": list(self.quarter_home_points),
            "quarter_away_points": list(self.quarter_away_points),
            "drives": self.drives,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HistoricalTruthMetrics:
    possessions_per_game: float
    plays_per_drive: float
    seconds_per_drive: float
    yards_per_drive: float
    touchdown_rate: float
    field_goal_rate: float
    missed_field_goal_rate: float
    punt_rate: float
    turnover_rate: float
    turnover_on_downs_rate: float
    end_of_half_rate: float
    red_zone_entry_rate: float
    red_zone_conversion_rate: float
    quarter_scoring: tuple[float, float, float, float]
    game_totals: float
    drive_sample_size: int
    game_sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "possessions_per_game": self.possessions_per_game,
            "plays_per_drive": self.plays_per_drive,
            "seconds_per_drive": self.seconds_per_drive,
            "yards_per_drive": self.yards_per_drive,
            "touchdown_rate": self.touchdown_rate,
            "field_goal_rate": self.field_goal_rate,
            "missed_field_goal_rate": self.missed_field_goal_rate,
            "punt_rate": self.punt_rate,
            "turnover_rate": self.turnover_rate,
            "turnover_on_downs_rate": self.turnover_on_downs_rate,
            "end_of_half_rate": self.end_of_half_rate,
            "red_zone_entry_rate": self.red_zone_entry_rate,
            "red_zone_conversion_rate": self.red_zone_conversion_rate,
            "quarter_scoring": list(self.quarter_scoring),
            "game_totals": self.game_totals,
            "drive_sample_size": self.drive_sample_size,
            "game_sample_size": self.game_sample_size,
        }


@dataclass(frozen=True)
class HistoricalTruthSnapshot:
    league: str
    seasons: tuple[int, ...]
    source_name: str
    drive_records: tuple[HistoricalDriveRecord, ...]
    game_records: tuple[HistoricalGameRecord, ...]
    metrics: HistoricalTruthMetrics
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "league": self.league,
            "seasons": list(self.seasons),
            "source_name": self.source_name,
            "drive_records": [record.to_dict() for record in self.drive_records],
            "game_records": [record.to_dict() for record in self.game_records],
            "metrics": self.metrics.to_dict(),
            "metadata": dict(self.metadata),
        }

    def to_calibration_snapshot(self, *, split: CalibrationSplit = CalibrationSplit.CALIBRATION) -> CalibrationBenchmarkSnapshot:
        """Adapt the truth snapshot into the existing calibration contract.

        This preserves the shared SmartSim Football Core architecture: the
        evaluator consumes the same ``CalibrationBenchmarkSnapshot`` shape it
        always has, now backed by measured drives instead of synthesized ones.
        """
        drive_records = tuple(
            BenchmarkDriveRecord(
                drive_id=record.drive_id,
                game_id=record.game_id,
                offense_team=record.offense_team,
                defense_team=record.defense_team,
                season=record.season,
                week=record.week,
                quarter=record.quarter_start,
                field_position_start=record.field_position_start,
                field_position_end=max(1, min(99, record.field_position_start + record.yards)),
                plays=record.plays,
                seconds=record.seconds,
                yards=record.yards,
                points=record.points,
                outcome=_RESULT_TO_POSSESSION_OUTCOME.get(record.result, PossessionOutcome.END_OF_QUARTER_STOP),
                red_zone_entry=record.red_zone_entry,
                goal_to_go=record.goal_to_go_entry,
                turnover=record.result in {RESULT_TURNOVER, RESULT_TURNOVER_ON_DOWNS},
                field_goal_attempt=record.result in {RESULT_FIELD_GOAL, RESULT_MISSED_FIELD_GOAL},
                punt=record.result == RESULT_PUNT,
                touchdown=record.result == RESULT_TOUCHDOWN,
                metadata={"source": "historical_truth", **record.metadata},
            )
            for record in self.drive_records
        )
        game_records = tuple(
            BenchmarkGameRecord(
                game_id=record.game_id,
                home_team=record.home_team,
                away_team=record.away_team,
                season=record.season,
                week=record.week,
                home_points=record.home_points,
                away_points=record.away_points,
                quarter_home_points=record.quarter_home_points,
                quarter_away_points=record.quarter_away_points,
                possessions=record.drives,
                drives=record.drives,
                metadata={"source": "historical_truth", **record.metadata},
            )
            for record in self.game_records
        )
        return CalibrationBenchmarkSnapshot(
            split=split,
            source_name=self.source_name,
            drive_records=drive_records,
            game_records=game_records,
            metadata={"league": self.league, "seasons": list(self.seasons), **self.metadata},
        )


__all__ = [
    "CANONICAL_RESULTS",
    "RESULT_TOUCHDOWN",
    "RESULT_FIELD_GOAL",
    "RESULT_MISSED_FIELD_GOAL",
    "RESULT_PUNT",
    "RESULT_TURNOVER",
    "RESULT_TURNOVER_ON_DOWNS",
    "RESULT_END_OF_HALF",
    "RESULT_SAFETY",
    "RESULT_OTHER",
    "HistoricalDriveRecord",
    "HistoricalGameRecord",
    "HistoricalTruthMetrics",
    "HistoricalTruthSnapshot",
]
