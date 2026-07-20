from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Sequence

from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import MetricResult
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import SummaryMetrics
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import compare_summary_metrics
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import covered_metric_names
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import summarize_benchmark_snapshot
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import summarize_simulation_outputs
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationOutput


@dataclass(frozen=True)
class SimulatorEvaluation:
    benchmark_snapshot: CalibrationBenchmarkSnapshot
    benchmark_summary: SummaryMetrics
    simulated_summary: SummaryMetrics
    metric_results: tuple[MetricResult, ...]
    score: float
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_snapshot": self.benchmark_snapshot.to_dict(),
            "benchmark_summary": self.benchmark_summary.to_dict(),
            "simulated_summary": self.simulated_summary.to_dict(),
            "metric_results": [metric.to_dict() for metric in self.metric_results],
            "score": self.score,
            "notes": list(self.notes),
        }


def _score_from_metrics(metrics: Sequence[MetricResult]) -> float:
    if not metrics:
        return 0.0
    normalized_errors = []
    for metric in metrics:
        scale = abs(metric.benchmark_value) if metric.benchmark_value else 1.0
        normalized_errors.append(metric.absolute_error / scale)
    return max(0.0, 1.0 - (sum(normalized_errors) / len(normalized_errors)))


def evaluate_simulator(
    benchmark_snapshot: CalibrationBenchmarkSnapshot,
    simulation_outputs: Sequence[SoccerSimSimulationOutput],
    *,
    notes: Sequence[str] | None = None,
    metric_names: set[str] | None = None,
) -> SimulatorEvaluation:
    """Compare simulated output against a truth snapshot.

    ``metric_names`` overrides the automatic truth-coverage detection
    (``covered_metric_names``) -- pass it when the snapshot's record shape
    has fields that don't reflect real measurements (e.g. a corners field
    left at its dataclass default because the source doesn't report
    corners), which would otherwise score as a measured value of zero.
    """
    benchmark_summary = summarize_benchmark_snapshot(benchmark_snapshot)
    simulated_summary = summarize_simulation_outputs(simulation_outputs)
    metric_results = compare_summary_metrics(
        benchmark_summary, simulated_summary, include=metric_names or covered_metric_names(benchmark_snapshot)
    )
    score = _score_from_metrics(metric_results)
    return SimulatorEvaluation(
        benchmark_snapshot=benchmark_snapshot,
        benchmark_summary=benchmark_summary,
        simulated_summary=simulated_summary,
        metric_results=metric_results,
        score=score,
        notes=tuple(notes or ()),
    )


__all__ = ["SimulatorEvaluation", "evaluate_simulator"]
