"""hockeysim calibration lane — score the engine/projection against a truth benchmark.

``benchmark_contracts`` (targets + tolerances from a TruthSnapshot) + ``evaluation_metrics``
(measure what the projection profile produces) + ``simulator_evaluator`` (0-1 accept score) +
``profile_calibration`` (derive profile overrides from truth) + ``calibration_report_generator``.
"""
from __future__ import annotations

from .benchmark_contracts import Benchmark, MetricTarget
from .calibration_report_generator import render_calibration_report
from .evaluation_metrics import (
    CALIBRATED_METRIC_NAMES,
    PROJECTION_METRIC_NAMES,
    measure_projection_profile,
)
from .profile_calibration import derive_projection_overrides
from .simulator_evaluator import EvaluationResult, MetricScore, evaluate

__all__ = [
    "Benchmark",
    "MetricTarget",
    "measure_projection_profile",
    "PROJECTION_METRIC_NAMES",
    "CALIBRATED_METRIC_NAMES",
    "evaluate",
    "EvaluationResult",
    "MetricScore",
    "derive_projection_overrides",
    "render_calibration_report",
]
