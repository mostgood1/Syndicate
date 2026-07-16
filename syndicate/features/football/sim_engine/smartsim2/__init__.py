from __future__ import annotations

from syndicate.features.football.sim_engine.smartsim2.drive_priors import DrivePriorProfile
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
from syndicate.features.football.sim_engine.smartsim2.drive_priors import drive_outcome_distribution
from syndicate.features.football.sim_engine.smartsim2.play_outcomes import PlayOutcome
from syndicate.features.football.sim_engine.smartsim2.play_simulator import PlayResult
from syndicate.features.football.sim_engine.smartsim2.play_simulator import simulate_play
from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState
from syndicate.features.football.sim_engine.smartsim2.situation_model import SituationContext
from syndicate.features.football.sim_engine.smartsim2.situation_model import classify_situation
from syndicate.features.football.sim_engine.smartsim2.contracts import GameResult
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationOutput
from syndicate.features.football.sim_engine.smartsim2.calibration import BenchmarkDriveRecord
from syndicate.features.football.sim_engine.smartsim2.calibration import BenchmarkGameRecord
from syndicate.features.football.sim_engine.smartsim2.calibration import BaselineAuditResult
from syndicate.features.football.sim_engine.smartsim2.calibration import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2.calibration import CalibrationSplit
from syndicate.features.football.sim_engine.smartsim2.calibration import CalibrationTarget
from syndicate.features.football.sim_engine.smartsim2.calibration import MetricResult
from syndicate.features.football.sim_engine.smartsim2.calibration import classify_metric_severity
from syndicate.features.football.sim_engine.smartsim2.calibration import SimulatorEvaluation
from syndicate.features.football.sim_engine.smartsim2.calibration import compare_metric
from syndicate.features.football.sim_engine.smartsim2.calibration import evaluate_simulator
from syndicate.features.football.sim_engine.smartsim2.calibration import generate_baseline_audit_report
from syndicate.features.football.sim_engine.smartsim2.calibration import generate_calibration_report
from syndicate.features.football.sim_engine.smartsim2.calibration import load_baseline_audit_result
from syndicate.features.football.sim_engine.smartsim2.calibration import summarize_benchmark_snapshot
from syndicate.features.football.sim_engine.smartsim2.calibration import summarize_simulation_outputs
from syndicate.features.football.sim_engine.smartsim2.drive_simulator import simulate_drive
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game


__all__ = [
    "DrivePriorProfile",
    "GameResult",
    "BenchmarkDriveRecord",
    "BenchmarkGameRecord",
    "PossessionOutcome",
    "PossessionState",
    "PlayOutcome",
    "PlayResult",
    "PlayState",
    "CalibrationBenchmarkSnapshot",
    "CalibrationSplit",
    "CalibrationTarget",
    "BaselineAuditResult",
    "MetricResult",
    "classify_metric_severity",
    "SituationContext",
    "SmartSim2SimulationInput",
    "SmartSim2SimulationOutput",
    "build_drive_priors",
    "drive_outcome_distribution",
    "compare_metric",
    "classify_situation",
    "evaluate_simulator",
    "generate_baseline_audit_report",
    "generate_calibration_report",
    "load_baseline_audit_result",
    "simulate_drive",
    "simulate_play",
    "simulate_game",
    "summarize_benchmark_snapshot",
    "summarize_simulation_outputs",
    "SimulatorEvaluation",
]