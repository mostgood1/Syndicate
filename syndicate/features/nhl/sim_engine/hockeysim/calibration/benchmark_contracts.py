"""Benchmark contracts for hockeysim calibration.

A :class:`Benchmark` is a set of metric *targets* (from a truth :class:`TruthSnapshot`) each with a
*tolerance* — the error scale the evaluator normalizes against (roughly "how far off before this
metric scores zero"). Mirrors soccer/football ``benchmark_contracts``: the benchmark is data, the
scoring lives in ``simulator_evaluator``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..historical_truth.contracts import TruthSnapshot

# Default per-metric tolerances (absolute error that maps to a normalized error of 1.0).
# Chosen to be "a clearly meaningful miss" for each quantity, so a well-calibrated engine scores
# close to 1.0 and an obviously-wrong one is penalized.
_DEFAULT_TOLERANCES: Dict[str, float] = {
    "goals_per_game": 0.75,        # ~12% of a ~6.4 baseline
    "home_goals_per_game": 0.5,
    "away_goals_per_game": 0.5,
    "shots_per_game": 6.0,
    "shooting_pct": 0.02,
    "period1_share": 0.04,
    "period2_share": 0.04,
    "period3_share": 0.04,
    "pp_goal_share": 0.04,
    "empty_net_share": 0.02,
    "home_win_pct": 0.05,
    "ot_rate": 0.05,
    "shootout_rate": 0.03,
}


@dataclass(frozen=True)
class MetricTarget:
    name: str
    target: float
    tolerance: float

    def normalized_error(self, measured: float) -> float:
        tol = self.tolerance if self.tolerance > 0 else 1.0
        return abs(float(measured) - float(self.target)) / tol


@dataclass(frozen=True)
class Benchmark:
    targets: Tuple[MetricTarget, ...]

    @classmethod
    def from_truth(
        cls,
        snapshot: TruthSnapshot,
        *,
        tolerances: Optional[Dict[str, float]] = None,
    ) -> "Benchmark":
        tol = {**_DEFAULT_TOLERANCES, **(tolerances or {})}
        cal = snapshot.to_calibration_snapshot()
        targets = tuple(
            MetricTarget(name=name, target=float(value), tolerance=float(tol.get(name, 1.0)))
            for name, value in cal.items()
        )
        return cls(targets=targets)

    def metric_names(self) -> List[str]:
        return [t.name for t in self.targets]

    def target_map(self) -> Dict[str, float]:
        return {t.name: t.target for t in self.targets}

    def get(self, name: str) -> Optional[MetricTarget]:
        for t in self.targets:
            if t.name == name:
                return t
        return None
