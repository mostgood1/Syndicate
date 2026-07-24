"""hockeysim historical-truth layer — real NHL StatsWeb game feeds -> calibration baseline.

The truth lane the Phase-3 calibration scores the engine against. ``nhl_statsweb_loader`` fetches +
caches real finished-game ``landing`` feeds and parses them into ``HistoricalGameRecord``s;
``snapshot_builder`` aggregates them into a ``TruthSnapshot`` whose ``to_calibration_snapshot()``
gives the flat metric targets (goals/game, home split, shots, shooting %, period shape, PP/EN share,
OT/SO rates).
"""
from __future__ import annotations

from .contracts import HistoricalGameRecord, TruthMetrics, TruthSnapshot
from .nhl_statsweb_loader import NhlStatsWebTruthLoader, parse_landing
from .snapshot_builder import build_truth_snapshot

__all__ = [
    "HistoricalGameRecord",
    "TruthMetrics",
    "TruthSnapshot",
    "NhlStatsWebTruthLoader",
    "parse_landing",
    "build_truth_snapshot",
]
