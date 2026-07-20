from __future__ import annotations

from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import BenchmarkMatchRecord
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import BenchmarkPossessionRecord
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import CalibrationSplit
from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import CalibrationTarget
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import MetricResult
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import SummaryMetrics
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import compare_metric
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import compare_summary_metrics
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import summarize_benchmark_snapshot
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import summarize_possession_outcome_frequencies
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import summarize_simulated_possession_outcome_frequencies
from syndicate.features.soccer.sim_engine.soccersim.calibration.evaluation_metrics import summarize_simulation_outputs
from syndicate.features.soccer.sim_engine.soccersim.calibration.simulator_evaluator import SimulatorEvaluation
from syndicate.features.soccer.sim_engine.soccersim.calibration.simulator_evaluator import evaluate_simulator
from syndicate.features.soccer.sim_engine.soccersim.calibration.calibration_report_generator import generate_calibration_report

__all__ = [
    "BenchmarkMatchRecord",
    "BenchmarkPossessionRecord",
    "CalibrationBenchmarkSnapshot",
    "CalibrationSplit",
    "CalibrationTarget",
    "MetricResult",
    "SimulatorEvaluation",
    "SummaryMetrics",
    "compare_metric",
    "compare_summary_metrics",
    "evaluate_simulator",
    "generate_calibration_report",
    "summarize_benchmark_snapshot",
    "summarize_possession_outcome_frequencies",
    "summarize_simulated_possession_outcome_frequencies",
    "summarize_simulation_outputs",
]
