from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any
from typing import Iterable
from typing import Sequence

from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import BenchmarkMatchRecord
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import BenchmarkPossessionRecord
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationOutput


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
    possession_length_events: float
    possession_length_seconds: float
    possessions_per_match: float
    shot_rate: float
    shot_on_target_share: float
    goal_rate: float
    final_third_entry_rate: float
    penalty_box_entry_rate: float
    corners_per_match: float
    shots_per_match: float
    match_totals: float
    home_win_rate: float
    draw_rate: float
    away_win_rate: float
    both_teams_scored_rate: float
    half_scoring: tuple[float, float]
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "possession_length_events": self.possession_length_events,
            "possession_length_seconds": self.possession_length_seconds,
            "possessions_per_match": self.possessions_per_match,
            "shot_rate": self.shot_rate,
            "shot_on_target_share": self.shot_on_target_share,
            "goal_rate": self.goal_rate,
            "final_third_entry_rate": self.final_third_entry_rate,
            "penalty_box_entry_rate": self.penalty_box_entry_rate,
            "corners_per_match": self.corners_per_match,
            "shots_per_match": self.shots_per_match,
            "match_totals": self.match_totals,
            "home_win_rate": self.home_win_rate,
            "draw_rate": self.draw_rate,
            "away_win_rate": self.away_win_rate,
            "both_teams_scored_rate": self.both_teams_scored_rate,
            "half_scoring": list(self.half_scoring),
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


_GOAL_OUTCOMES = {"goal", "penalty_goal"}
_SHOT_OUTCOMES = {"goal", "penalty_goal", "penalty_missed", "shot_saved", "shot_off_target", "shot_blocked"}
_ON_TARGET_OUTCOMES = {"goal", "penalty_goal", "shot_saved"}


def summarize_possession_outcome_frequencies(records: Sequence[BenchmarkPossessionRecord]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for record in records:
        outcome = _normalize_outcome(record.outcome)
        counts[outcome] = counts.get(outcome, 0) + 1
    total = sum(counts.values()) or 1
    return {key: value / total for key, value in counts.items()}


def summarize_simulated_possession_outcome_frequencies(outputs: Sequence[SoccerSimSimulationOutput]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for output in outputs:
        for possession in output.possession_log:
            outcome = _normalize_outcome(possession.get("outcome"))
            counts[outcome] = counts.get(outcome, 0) + 1
    total = sum(counts.values()) or 1
    return {key: value / total for key, value in counts.items()}


def _extract_possession_records(records: Sequence[BenchmarkPossessionRecord]) -> SummaryMetrics:
    possession_count = len(records)
    match_ids = {record.match_id for record in records}
    shots = [record for record in records if record.shot_taken or _normalize_outcome(record.outcome) in _SHOT_OUTCOMES]
    on_target = [record for record in shots if record.shot_on_target or _normalize_outcome(record.outcome) in _ON_TARGET_OUTCOMES]
    goals = [record for record in records if record.goals > 0 or _normalize_outcome(record.outcome) in _GOAL_OUTCOMES]
    final_third = [record for record in records if record.reached_final_third]
    penalty_box = [record for record in records if record.reached_penalty_box]
    corner_total = sum(record.corner_count for record in records)

    return SummaryMetrics(
        possession_length_events=_safe_mean(record.events for record in records),
        possession_length_seconds=_safe_mean(record.seconds for record in records),
        possessions_per_match=_rate(possession_count, max(1, len(match_ids))),
        shot_rate=_rate(len(shots), possession_count),
        shot_on_target_share=_rate(len(on_target), len(shots)),
        goal_rate=_rate(len(goals), possession_count),
        final_third_entry_rate=_rate(len(final_third), possession_count),
        penalty_box_entry_rate=_rate(len(penalty_box), possession_count),
        corners_per_match=_rate(corner_total, max(1, len(match_ids))),
        shots_per_match=_rate(len(shots), max(1, len(match_ids))),
        match_totals=0.0,
        home_win_rate=0.0,
        draw_rate=0.0,
        away_win_rate=0.0,
        both_teams_scored_rate=0.0,
        half_scoring=(0.0, 0.0),
        sample_size=possession_count,
    )


def _extract_match_records(records: Sequence[BenchmarkMatchRecord]) -> SummaryMetrics:
    match_count = len(records)
    home_wins = sum(1 for record in records if record.home_goals > record.away_goals)
    draws = sum(1 for record in records if record.home_goals == record.away_goals)
    away_wins = match_count - home_wins - draws
    both_scored = sum(1 for record in records if record.home_goals > 0 and record.away_goals > 0)
    half_totals = []
    for half_index in range(2):
        half_totals.append(
            _safe_mean(record.half_home_goals[half_index] + record.half_away_goals[half_index] for record in records)
        )
    return SummaryMetrics(
        possession_length_events=0.0,
        possession_length_seconds=0.0,
        possessions_per_match=_safe_mean(record.possessions for record in records),
        shot_rate=0.0,
        shot_on_target_share=_rate(sum(record.shots_on_target for record in records), sum(record.shots for record in records)),
        goal_rate=0.0,
        final_third_entry_rate=0.0,
        penalty_box_entry_rate=0.0,
        corners_per_match=_safe_mean(record.corners for record in records),
        shots_per_match=_safe_mean(record.shots for record in records),
        match_totals=_safe_mean(record.total_goals for record in records),
        home_win_rate=_rate(home_wins, match_count),
        draw_rate=_rate(draws, match_count),
        away_win_rate=_rate(away_wins, match_count),
        both_teams_scored_rate=_rate(both_scored, match_count),
        half_scoring=tuple(half_totals),
        sample_size=match_count,
    )


def summarize_benchmark_snapshot(snapshot: CalibrationBenchmarkSnapshot) -> SummaryMetrics:
    possession_summary = _extract_possession_records(snapshot.possession_records)
    match_summary = _extract_match_records(snapshot.match_records)
    if possession_summary.sample_size == 0:
        return match_summary
    if match_summary.sample_size == 0:
        return possession_summary
    return SummaryMetrics(
        possession_length_events=possession_summary.possession_length_events,
        possession_length_seconds=possession_summary.possession_length_seconds,
        possessions_per_match=match_summary.possessions_per_match,
        shot_rate=possession_summary.shot_rate,
        shot_on_target_share=possession_summary.shot_on_target_share,
        goal_rate=possession_summary.goal_rate,
        final_third_entry_rate=possession_summary.final_third_entry_rate,
        penalty_box_entry_rate=possession_summary.penalty_box_entry_rate,
        corners_per_match=match_summary.corners_per_match,
        shots_per_match=match_summary.shots_per_match,
        match_totals=match_summary.match_totals,
        home_win_rate=match_summary.home_win_rate,
        draw_rate=match_summary.draw_rate,
        away_win_rate=match_summary.away_win_rate,
        both_teams_scored_rate=match_summary.both_teams_scored_rate,
        half_scoring=match_summary.half_scoring,
        sample_size=possession_summary.sample_size + match_summary.sample_size,
    )


def summarize_simulation_outputs(outputs: Sequence[SoccerSimSimulationOutput]) -> SummaryMetrics:
    possession_events: list[float] = []
    possession_seconds: list[float] = []
    possessions_per_match: list[float] = []
    shots = 0
    on_target = 0
    goals = 0
    final_third_entries = 0
    penalty_box_entries = 0
    corner_total = 0
    home_wins = 0
    draws = 0
    away_wins = 0
    both_scored = 0
    half_points = [0.0, 0.0]
    total_goals: list[float] = []
    match_count = len(outputs)
    shots_per_match: list[float] = []

    for output in outputs:
        possession_log = list(output.possession_log)
        possessions_per_match.append(float(len(possession_log)))
        home = int(output.final_score["home"])
        away = int(output.final_score["away"])
        total_goals.append(float(home + away))
        if home > away:
            home_wins += 1
        elif away > home:
            away_wins += 1
        else:
            draws += 1
        if home > 0 and away > 0:
            both_scored += 1
        match_shots = 0
        for possession in possession_log:
            possession_events.append(float(possession.get("event_count") or 0))
            possession_seconds.append(float(possession.get("clock_consumed") or 0))
            outcome = _normalize_outcome(possession.get("outcome"))
            if possession.get("shot_taken") or outcome in _SHOT_OUTCOMES:
                shots += 1
                match_shots += 1
                if possession.get("shot_on_target") or outcome in _ON_TARGET_OUTCOMES:
                    on_target += 1
            if float(possession.get("goals_scored") or 0) > 0 or outcome in _GOAL_OUTCOMES:
                goals += 1
            if possession.get("reached_final_third"):
                final_third_entries += 1
            if possession.get("reached_penalty_box"):
                penalty_box_entries += 1
            corner_total += int(possession.get("corner_count") or 0)
        shots_per_match.append(float(match_shots))
        for half_entry in output.half_log:
            half_index = max(1, min(2, int(half_entry.get("half") or 1))) - 1
            half_points[half_index] += float(half_entry.get("home_goals") or 0) + float(half_entry.get("away_goals") or 0)

    possession_count = len(possession_events)
    half_means = tuple(value / match_count if match_count else 0.0 for value in half_points)
    return SummaryMetrics(
        possession_length_events=_safe_mean(possession_events),
        possession_length_seconds=_safe_mean(possession_seconds),
        possessions_per_match=_safe_mean(possessions_per_match),
        shot_rate=_rate(shots, possession_count),
        shot_on_target_share=_rate(on_target, shots),
        goal_rate=_rate(goals, possession_count),
        final_third_entry_rate=_rate(final_third_entries, possession_count),
        penalty_box_entry_rate=_rate(penalty_box_entries, possession_count),
        corners_per_match=_rate(corner_total, max(1, match_count)),
        shots_per_match=_safe_mean(shots_per_match),
        match_totals=_safe_mean(total_goals),
        home_win_rate=_rate(home_wins, match_count),
        draw_rate=_rate(draws, match_count),
        away_win_rate=_rate(away_wins, match_count),
        both_teams_scored_rate=_rate(both_scored, match_count),
        half_scoring=half_means,
        sample_size=match_count,
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


# Metrics only measurable from possession-level truth records vs only from
# match-level truth records. Comparisons are emitted only for metrics the
# benchmark snapshot actually covers, so absent truth granularity reads as
# "not measured" instead of a benchmark value of zero.
POSSESSION_LEVEL_METRICS = {
    "possession_length_events",
    "possession_length_seconds",
    "shot_rate",
    "goal_rate",
    "final_third_entry_rate",
    "penalty_box_entry_rate",
}
MATCH_LEVEL_METRICS = {
    "possessions_per_match",
    "corners_per_match",
    "shots_per_match",
    "match_totals",
    "home_win_rate",
    "draw_rate",
    "away_win_rate",
    "both_teams_scored_rate",
    "half_1_scoring",
    "half_2_scoring",
}


def compare_summary_metrics(
    benchmark: SummaryMetrics,
    simulated: SummaryMetrics,
    *,
    include: set[str] | None = None,
) -> tuple[MetricResult, ...]:
    results = [
        compare_metric("possession_length_events", benchmark.possession_length_events, simulated.possession_length_events, sample_size=benchmark.sample_size, unit="events"),
        compare_metric("possession_length_seconds", benchmark.possession_length_seconds, simulated.possession_length_seconds, sample_size=benchmark.sample_size, unit="seconds"),
        compare_metric("possessions_per_match", benchmark.possessions_per_match, simulated.possessions_per_match, sample_size=benchmark.sample_size, unit="possessions"),
        compare_metric("shot_rate", benchmark.shot_rate, simulated.shot_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("shot_on_target_share", benchmark.shot_on_target_share, simulated.shot_on_target_share, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("goal_rate", benchmark.goal_rate, simulated.goal_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("final_third_entry_rate", benchmark.final_third_entry_rate, simulated.final_third_entry_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("penalty_box_entry_rate", benchmark.penalty_box_entry_rate, simulated.penalty_box_entry_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("corners_per_match", benchmark.corners_per_match, simulated.corners_per_match, sample_size=benchmark.sample_size, unit="corners"),
        compare_metric("shots_per_match", benchmark.shots_per_match, simulated.shots_per_match, sample_size=benchmark.sample_size, unit="shots"),
        compare_metric("match_totals", benchmark.match_totals, simulated.match_totals, sample_size=benchmark.sample_size, unit="goals"),
        compare_metric("home_win_rate", benchmark.home_win_rate, simulated.home_win_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("draw_rate", benchmark.draw_rate, simulated.draw_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("away_win_rate", benchmark.away_win_rate, simulated.away_win_rate, sample_size=benchmark.sample_size, unit="rate"),
        compare_metric("both_teams_scored_rate", benchmark.both_teams_scored_rate, simulated.both_teams_scored_rate, sample_size=benchmark.sample_size, unit="rate"),
    ]
    for half_index, (benchmark_value, simulated_value) in enumerate(zip(benchmark.half_scoring, simulated.half_scoring), start=1):
        results.append(
            compare_metric(
                f"half_{half_index}_scoring",
                benchmark_value,
                simulated_value,
                sample_size=benchmark.sample_size,
                unit="goals",
            )
        )
    if include is not None:
        results = [result for result in results if result.name in include]
    return tuple(results)


def covered_metric_names(snapshot: CalibrationBenchmarkSnapshot) -> set[str]:
    """Metric names the snapshot's truth granularity can actually benchmark."""
    covered: set[str] = set()
    if snapshot.possession_records:
        covered |= POSSESSION_LEVEL_METRICS | {"shot_on_target_share"}
    if snapshot.match_records:
        covered |= MATCH_LEVEL_METRICS | {"shot_on_target_share"}
        if not any(record.possessions for record in snapshot.match_records):
            covered.discard("possessions_per_match")
    return covered


__all__ = [
    "MATCH_LEVEL_METRICS",
    "MetricResult",
    "POSSESSION_LEVEL_METRICS",
    "SummaryMetrics",
    "compare_metric",
    "compare_summary_metrics",
    "covered_metric_names",
    "summarize_possession_outcome_frequencies",
    "summarize_simulated_possession_outcome_frequencies",
    "summarize_benchmark_snapshot",
    "summarize_simulation_outputs",
]
