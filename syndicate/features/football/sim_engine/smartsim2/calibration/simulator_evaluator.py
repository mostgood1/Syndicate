from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Sequence

from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import MetricResult
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import SummaryMetrics
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import compare_summary_metrics
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import summarize_benchmark_snapshot
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import summarize_simulation_outputs
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationOutput


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
    simulation_outputs: Sequence[SmartSim2SimulationOutput],
    *,
    notes: Sequence[str] | None = None,
) -> SimulatorEvaluation:
    benchmark_summary = summarize_benchmark_snapshot(benchmark_snapshot)
    simulated_summary = summarize_simulation_outputs(simulation_outputs)
    metric_results = compare_summary_metrics(benchmark_summary, simulated_summary)
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
