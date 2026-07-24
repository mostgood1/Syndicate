"""Score measured metrics against a truth :class:`Benchmark`.

0–1 accept score = ``max(0, 1 − mean(normalized abs error))`` over the evaluated metrics, matching
soccer's ``simulator_evaluator`` (which landed 0.948–0.982 on EPL) and football's evaluator. A
``metric_names`` override restricts scoring to a subset (e.g. only the projection-controlled
metrics) so a profile is graded on what it actually governs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .benchmark_contracts import Benchmark


@dataclass(frozen=True)
class MetricScore:
    name: str
    target: float
    measured: float
    normalized_error: float


@dataclass(frozen=True)
class EvaluationResult:
    score: float
    metric_scores: List[MetricScore] = field(default_factory=list)

    def worst(self, k: int = 3) -> List[MetricScore]:
        return sorted(self.metric_scores, key=lambda m: m.normalized_error, reverse=True)[:k]

    def to_dict(self) -> Dict[str, object]:
        return {
            "score": round(self.score, 4),
            "metrics": {
                m.name: {
                    "target": m.target,
                    "measured": m.measured,
                    "normalized_error": round(m.normalized_error, 4),
                }
                for m in self.metric_scores
            },
        }


def evaluate(
    benchmark: Benchmark,
    measured: Dict[str, float],
    *,
    metric_names: Optional[Sequence[str]] = None,
) -> EvaluationResult:
    """Score ``measured`` against ``benchmark``; ``metric_names`` optionally restricts the subset."""
    allow = set(metric_names) if metric_names is not None else None
    scores: List[MetricScore] = []
    for target in benchmark.targets:
        if allow is not None and target.name not in allow:
            continue
        if target.name not in measured:
            continue
        m = float(measured[target.name])
        scores.append(
            MetricScore(
                name=target.name,
                target=target.target,
                measured=m,
                normalized_error=target.normalized_error(m),
            )
        )
    if not scores:
        return EvaluationResult(score=0.0, metric_scores=[])
    mean_err = sum(s.normalized_error for s in scores) / len(scores)
    return EvaluationResult(score=max(0.0, 1.0 - mean_err), metric_scores=scores)
