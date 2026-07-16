"""SmartSim 2.0 historical truth layer.

Real drive/play-level football history that replaces the synthetic proxy
calibration benchmark while preserving the shared SmartSim Football Core
architecture (truth snapshots adapt into ``CalibrationBenchmarkSnapshot``).
"""

from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_builder import build_historical_truth_snapshot
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract import HistoricalDriveRecord
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract import HistoricalGameRecord
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract import HistoricalTruthMetrics
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract import HistoricalTruthSnapshot
from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import load_ncaaf_canonical_frame
from syndicate.features.football.sim_engine.smartsim2.historical_truth.nfl_historical_loader import load_pbp_seasons

__all__ = [
    "HistoricalDriveRecord",
    "HistoricalGameRecord",
    "HistoricalTruthMetrics",
    "HistoricalTruthSnapshot",
    "build_historical_truth_snapshot",
    "load_ncaaf_canonical_frame",
    "load_pbp_seasons",
]
