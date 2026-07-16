from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any
from typing import Iterable
from typing import Sequence

from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import BenchmarkDriveRecord
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import BenchmarkGameRecord
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationOutput


@dataclass(frozen=True)
class MetricResult:
    name: str
    benchmark_value: float
    simulated_value: float
    error: float
    absolute_error: float
    relative_error: float | None
    sample_size: int
    unit: str = ""
    direction: str = "lower_is_better"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "benchmark_value": self.benchmark_value,
            "simulated_value": self.simulated_value,
            "error": self.error,
            "absolute_error": self.absolute_error,
            "relative_error": self.relative_error,
            "sample_size": self.sample_size,
            "unit": self.unit,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class SummaryMetrics:
    drive_length_plays: float
    drive_length_seconds: float
    drive_length_yards: float
    possessions_per_game: float
    touchdown_rate: float
    field_goal_rate: float
    punt_rate: float
    turnover_rate: float
    red_zone_conversion_rate: float
    quarter_scoring: tuple[float, float, float, float]
    game_totals: float
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "drive_length_plays": self.drive_length_plays,
            "drive_length_seconds": self.drive_length_seconds,
            "drive_length_yards": self.drive_length_yards,
            "possessions_per_game": self.possessions_per_game,
            "touchdown_rate": self.touchdown_rate,
            "field_goal_rate": self.field_goal_rate,
            "punt_rate": self.punt_rate,
            "turnover_rate": self.turnover_rate,
            "red_zone_conversion_rate": self.red_zone_conversion_rate,
            "quarter_scoring": list(self.quarter_scoring),
            "game_totals": self.game_totals,
            "sample_size": self.sample_size,
        }


def _safe_mean(values: Iterable[float]) -> float:
    samples = [float(value) for value in values]
    return mean(samples) if samples else 0.0


def _rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _absolute_error(benchmark_value: float, simulated_value: float) -> float:
    return abs(simulated_value - benchmark_value)


def _relative_error(benchmark_value: float, simulated_value: float) -> float | None:
    if benchmark_value == 0:
        return None
    return (simulated_value - benchmark_value) / benchmark_value


def _normalize_outcome(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _count_drive_outcomes(records: Sequence[BenchmarkDriveRecord]) -> dict[str, int]:
    counts = {
        "touchdown": 0,
        "field_goal": 0,
        "missed_field_goal": 0,
        "punt": 0,
        "turnover": 0,
        "turnover_on_downs": 0,
        "end_of_quarter_stop": 0,
        "end_of_half_stop": 0,
    }
    for record in records:
        outcome = _normalize_outcome(record.outcome)
        if outcome in counts:
            counts[outcome] += 1
        elif record.touchdown:
            counts["touchdown"] += 1
        elif record.field_goal_attempt:
            counts["field_goal"] += 1
        elif record.punt:
            counts["punt"] += 1
        elif record.turnover:
            counts["turnover"] += 1
    return counts


def _count_simulated_drive_outcomes(outputs: Sequence[SmartSim2SimulationOutput]) -> dict[str, int]:
    counts = {
        "touchdown": 0,
        "field_goal": 0,
        "missed_field_goal": 0,
        "punt": 0,
        "turnover": 0,
        "turnover_on_downs": 0,
        "end_of_quarter_stop": 0,
        "end_of_half_stop": 0,
    }
    for output in outputs:
        for drive in output.drive_log:
            outcome = _normalize_outcome(drive.get("outcome"))
            if outcome in counts:
                counts[outcome] += 1
    return counts


def summarize_drive_outcome_frequencies(records: Sequence[BenchmarkDriveRecord]) -> dict[str, float]:
    counts = _count_drive_outcomes(records)
    total = sum(counts.values()) or 1
    return {key: value / total for key, value in counts.items()}


def summarize_simulated_drive_outcome_frequencies(outputs: Sequence[SmartSim2SimulationOutput]) -> dict[str, float]:
    counts = _count_simulated_drive_outcomes(outputs)
    total = sum(counts.values()) or 1
    return {key: value / total for key, value in counts.items()}


def _extract_drive_records(records: Sequence[BenchmarkDriveRecord]) -> SummaryMetrics:
    drive_lengths = [record.plays for record in records]
    drive_seconds = [record.seconds for record in records]
    drive_yards = [record.yards for record in records]
    drive_count = len(records)
    game_ids = {record.game_id for record in records}
    scoring_drives = [record for record in records if record.points > 0]
    touchdown_drives = [record for record in records if record.touchdown or _normalize_outcome(record.outcome) == "touchdown"]
    field_goals = [record for record in records if record.field_goal_attempt or _normalize_outcome(record.outcome) == "field_goal"]
    punts = [record for record in records if record.punt or _normalize_outcome(record.outcome) == "punt"]
    turnovers = [record for record in records if record.turnover or _normalize_outcome(record.outcome) in {"turnover", "turnover_on_downs"}]
    red_zone_entries = [record for record in records if record.red_zone_entry or record.goal_to_go]
    red_zone_scores = [record for record in records if (record.red_zone_entry or record.goal_to_go) and record.points > 0]

    quarter_totals = []
    for quarter in range(1, 5):
        quarter_totals.append(_safe_mean(record.points for record in records if record.quarter == quarter))

    return SummaryMetrics(
        drive_length_plays=_safe_mean(drive_lengths),
        drive_length_seconds=_safe_mean(drive_seconds),
        drive_length_yards=_safe_mean(drive_yards),
        possessions_per_game=_rate(drive_count, max(1, len(game_ids))),
        touchdown_rate=_rate(len(touchdown_drives), drive_count),
        field_goal_rate=_rate(len(field_goals), drive_count),
        punt_rate=_rate(len(punts), drive_count),
        turnover_rate=_rate(len(turnovers), drive_count),
        red_zone_conversion_rate=_rate(len(red_zone_scores), len(red_zone_entries)),
        quarter_scoring=tuple(quarter_totals),
        game_totals=_safe_mean(record.points for record in records),
        sample_size=drive_count,
    )


def _extract_game_records(records: Sequence[BenchmarkGameRecord]) -> SummaryMetrics:
    game_count = len(records)
    possessions = [record.possessions for record in records]
    totals = [record.total_points for record in records]
    quarter_totals = []
    for quarter in range(4):
        quarter_totals.append(_safe_mean(record.quarter_home_points[quarter] + record.quarter_away_points[quarter] for record in records))
    return SummaryMetrics(
        drive_length_plays=0.0,
        drive_length_seconds=0.0,
        drive_length_yards=0.0,
        possessions_per_game=_safe_mean(possessions),
        touchdown_rate=0.0,
        field_goal_rate=0.0,
        punt_rate=0.0,
        turnover_rate=0.0,
        red_zone_conversion_rate=0.0,
        quarter_scoring=tuple(quarter_totals),
        game_totals=_safe_mean(totals),
        sample_size=game_count,
    )


def summarize_benchmark_snapshot(snapshot: CalibrationBenchmarkSnapshot) -> SummaryMetrics:
    drive_summary = _extract_drive_records(snapshot.drive_records)
    game_summary = _extract_game_records(snapshot.game_records)
    if drive_summary.sample_size == 0:
        return game_summary
    if game_summary.sample_size == 0:
        return drive_summary
    return SummaryMetrics(
        drive_length_plays=drive_summary.drive_length_plays,
        drive_length_seconds=drive_summary.drive_length_seconds,
        drive_length_yards=drive_summary.drive_length_yards,
        possessions_per_game=game_summary.possessions_per_game,
        touchdown_rate=drive_summary.touchdown_rate,
        field_goal_rate=drive_summary.field_goal_rate,
        punt_rate=drive_summary.punt_rate,
        turnover_rate=drive_summary.turnover_rate,
        red_zone_conversion_rate=drive_summary.red_zone_conversion_rate,
        quarter_scoring=game_summary.quarter_scoring,
        game_totals=game_summary.game_totals,
        sample_size=drive_summary.sample_size + game_summary.sample_size,
    )


def _drive_reached_red_zone(drive: dict[str, Any], outcome: str) -> bool:
    if outcome == "touchdown":
        return True
    start_state = drive.get("start_state") or {}
    if float(start_state.get("field_position") or 0) >= 75:
        return True
    for step in drive.get("steps") or ():
        step_start = step.get("start_state") or {}
        if float(step_start.get("field_position") or 0) >= 75:
            return True
    return False


def summarize_simulation_outputs(outputs: Sequence[SmartSim2SimulationOutput]) -> SummaryMetrics:
    drive_plays: list[float] = []
    drive_seconds: list[float] = []
    drive_yards: list[float] = []
    possessions_per_game: list[float] = []
    touchdowns = 0
    field_goals = 0
    punts = 0
    turnovers = 0
    red_zone_entries = 0
    red_zone_scores = 0
    quarter_points = [0.0, 0.0, 0.0, 0.0]
    total_points: list[float] = []
    game_count = len(outputs)

    for output in outputs:
        drive_log = list(output.drive_log)
        possession_count = len(drive_log)
        possessions_per_game.append(float(possession_count))
        total_points.append(float(output.final_score["home"] + output.final_score["away"]))
        for drive in drive_log:
            plays = float(drive.get("play_count") or 0)
            seconds = float(drive.get("clock_consumed") or 0)
            yards = float(drive.get("yards_gained") or 0)
            outcome = _normalize_outcome(drive.get("outcome"))
            points = float(drive.get("points_scored") or 0)
            drive_plays.append(plays)
            drive_seconds.append(seconds)
            drive_yards.append(yards)
            if outcome == "touchdown":
                touchdowns += 1
            elif outcome == "field_goal":
                field_goals += 1
            elif outcome == "punt":
                punts += 1
            elif outcome in {"turnover", "turnover_on_downs"}:
                turnovers += 1
            if _drive_reached_red_zone(drive, outcome):
                red_zone_entries += 1
                if points > 0 and outcome in {"touchdown", "field_goal"}:
                    red_zone_scores += 1
        for quarter in output.quarter_log:
            index = max(1, min(4, int(quarter.get("quarter") or 1))) - 1
            quarter_points[index] += float(quarter.get("home_points") or 0) + float(quarter.get("away_points") or 0)

    drive_count = len(drive_plays)
    quarter_means = tuple(value / game_count if game_count else 0.0 for value in quarter_points)
    return SummaryMetrics(
        drive_length_plays=_safe_mean(drive_plays),
        drive_length_seconds=_safe_mean(drive_seconds),
        drive_length_yards=_safe_mean(drive_yards),
        possessions_per_game=_safe_mean(possessions_per_game),
        touchdown_rate=_rate(touchdowns, drive_count),
        field_goal_rate=_rate(field_goals, drive_count),
        punt_rate=_rate(punts, drive_count),
        turnover_rate=_rate(turnovers, drive_count),
        red_zone_conversion_rate=_rate(red_zone_scores, red_zone_entries),
        quarter_scoring=quarter_means,
        game_totals=_safe_mean(total_points),
        sample_size=game_count,
    )


def compare_metric(name: str, benchmark_value: float, simulated_value: float, *, sample_size: int = 0, unit: str = "", direction: str = "lower_is_better") -> MetricResult:
    error = simulated_value - benchmark_value
    return MetricResult(
        name=name,
        benchmark_value=benchmark_value,
        simulated_value=simulated_value,
        error=error,
        absolute_error=_absolute_error(benchmark_value, simulated_value),
        relative_error=_relative_error(benchmark_value, simulated_value),
        sample_size=sample_size,
        unit=unit,
        direction=direction,
    )


def compare_summary_metrics(benchmark: SummaryMetrics, simulated: SummaryMetrics) -> tuple[MetricResult, ...]:
    results = [
        compare_metric("drive_length_plays", benchmark.drive_length_plays, simulated.drive_length_plays, sample_size=benchmark.sample_size, unit="plays"),
        compare_metric("drive_length_seconds", benchmark.drive_length_seconds, simulated.drive_length_seconds, sample_size=benchmark.sample_size, unit="seconds"),
        compare_metric("drive_length_yards", benchmark.drive_length_yards, simulated.drive_length_yards, sample_size=benchmark.sample_size, unit="yards"),
        compare_metric("possessions_per_game", benchmark.possessions_per_game, simulated.possessions_per_game, sample_size=benchmark.sample_size, unit="possessions"),
        compare_metric("touchdown_rate", benchmark.touchdown_rate, simulated.touchdown_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("field_goal_rate", benchmark.field_goal_rate, simulated.field_goal_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("punt_rate", benchmark.punt_rate, simulated.punt_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("turnover_rate", benchmark.turnover_rate, simulated.turnover_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("red_zone_conversion_rate", benchmark.red_zone_conversion_rate, simulated.red_zone_conversion_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("game_totals", benchmark.game_totals, simulated.game_totals, sample_size=benchmark.sample_size, unit="points"),
    ]
    for quarter_index, (benchmark_value, simulated_value) in enumerate(zip(benchmark.quarter_scoring, simulated.quarter_scoring), start=1):
        results.append(
            compare_metric(
                f"quarter_{quarter_index}_scoring",
                benchmark_value,
                simulated_value,
                sample_size=benchmark.sample_size,
                unit="points",
            )
        )
    return tuple(results)


__all__ = [
    "MetricResult",
    "SummaryMetrics",
    "compare_metric",
    "compare_summary_metrics",
    "summarize_drive_outcome_frequencies",
    "summarize_simulated_drive_outcome_frequencies",
    "summarize_benchmark_snapshot",
    "summarize_simulation_outputs",
]
