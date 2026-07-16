"""Truth-backed calibration audit for SmartSim 2.0.

Evaluates the simulator against the NFL Historical Truth Snapshot (real
nflverse drives) instead of the synthetic proxy benchmark. The simulation
workload (game inputs) still comes from the historical game summaries so
runs remain replayable and comparable with earlier iterations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from syndicate.features.football.sim_engine.smartsim2.calibration.baseline_audit import BaselineAuditResult
from syndicate.features.football.sim_engine.smartsim2.calibration.baseline_audit import build_baseline_audit_snapshot_and_inputs
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationSplit
from syndicate.features.football.sim_engine.smartsim2.calibration.simulator_evaluator import evaluate_simulator
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_builder import build_historical_truth_snapshot
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract import HistoricalTruthSnapshot
from syndicate.features.football.sim_engine.smartsim2.historical_truth.nfl_historical_loader import DEFAULT_CACHE_DIR
from syndicate.features.football.sim_engine.smartsim2.historical_truth.nfl_historical_loader import load_pbp_seasons

DEFAULT_TRUTH_SEASONS: tuple[int, ...] = (2023, 2024, 2025)


def load_truth_snapshot(
    *,
    seasons: Sequence[int] = DEFAULT_TRUTH_SEASONS,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> HistoricalTruthSnapshot:
    pbp = load_pbp_seasons(seasons, cache_dir=cache_dir)
    return build_historical_truth_snapshot(
        pbp,
        seasons=seasons,
        source_name=f"nflverse play-by-play {min(seasons)}-{max(seasons)} (regular season)",
    )


def load_truth_audit_result(
    *,
    sim_data_root: Path,
    game_detail_paths: Sequence[Path],
    seasons: Sequence[int] = DEFAULT_TRUTH_SEASONS,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    split: CalibrationSplit = CalibrationSplit.CALIBRATION,
) -> BaselineAuditResult:
    """Run the simulator workload and evaluate it against historical truth."""
    _, simulation_inputs = build_baseline_audit_snapshot_and_inputs(
        data_root=sim_data_root,
        game_detail_paths=game_detail_paths,
        split=split,
    )
    truth_snapshot = load_truth_snapshot(seasons=seasons, cache_dir=cache_dir)
    benchmark_snapshot = truth_snapshot.to_calibration_snapshot(split=split)
    simulation_outputs = tuple(simulate_game(simulation_input) for simulation_input in simulation_inputs)
    evaluation = evaluate_simulator(benchmark_snapshot, simulation_outputs)
    return BaselineAuditResult(
        benchmark_snapshot=benchmark_snapshot,
        simulation_inputs=simulation_inputs,
        simulation_outputs=simulation_outputs,
        evaluation=evaluation,
    )


__all__ = ["DEFAULT_TRUTH_SEASONS", "load_truth_audit_result", "load_truth_snapshot"]
