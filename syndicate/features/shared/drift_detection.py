"""Generic rolling-window drift detection over any scalar metric (bias,
CRPS, CLV, win rate, calibration error) -- Stage 5 of the learning-loop
plan.

Context: nothing in the repo surfaces "MLB total-runs sim has run 0.3 high
for 10 days" or "our edge on NBA spreads disappeared when the book
changed" (plan doc P8). syndicate.features.ncaaf.smartsim2_performance_tracking
already has a first-half-vs-second-half `detect_drift` for its own
NCAAF-specific log shape and fixed thresholds -- this generalizes the same
idea (compare a recent window against a baseline window, flag when the gap
is too large to be noise) into a sport-agnostic, metric-agnostic function
any caller can point at any two windows of numbers.

Pure math, no I/O -- callers (a future scheduled job, an ops endpoint, or
an ad hoc script) supply the two windows of values themselves.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _variance(values: Sequence[float], mean_value: float) -> float:
    if len(values) < 2:
        return 0.0
    return sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)


def detect_metric_drift(
    recent_values: Sequence[float],
    baseline_values: Sequence[float],
    *,
    min_sample_size: int = 10,
    z_threshold: float = 2.5,
) -> dict[str, Any]:
    """Two-sample z-style comparison of a recent window against a baseline
    window for the same metric. Flags drift when the gap between the two
    means is large relative to their combined variability -- NOT just a
    raw threshold on the delta, so a metric that's naturally noisy (small
    per-day sample sizes) doesn't trip constantly while a metric that's
    naturally stable flags on a genuinely small but real shift.

    ``z_threshold=2.5`` is a starting point (roughly a 99% one-sided
    threshold under a normal approximation) -- same "no real history to
    calibrate against yet" caveat every other new threshold in this plan
    carries (DecisionPolicy's promotion_margin, build_segmented_reliability_profile's
    shrinkage_k). Revisit once real drift/no-drift examples exist.

    Below ``min_sample_size`` in either window, this deliberately reports
    "insufficient data" rather than a possibly-wild z-score from a
    handful of points -- a confident-looking flag built on 3 observations
    is worse than no flag at all.
    """
    recent_clean = [float(v) for v in recent_values if v is not None]
    baseline_clean = [float(v) for v in baseline_values if v is not None]

    if len(recent_clean) < min_sample_size or len(baseline_clean) < min_sample_size:
        return {
            "flagged": False,
            "reason": "insufficient_data",
            "n_recent": len(recent_clean),
            "n_baseline": len(baseline_clean),
            "min_sample_size": min_sample_size,
        }

    recent_mean = _mean(recent_clean)
    baseline_mean = _mean(baseline_clean)
    recent_variance = _variance(recent_clean, recent_mean)
    baseline_variance = _variance(baseline_clean, baseline_mean)
    standard_error = math.sqrt(recent_variance / len(recent_clean) + baseline_variance / len(baseline_clean))

    delta = recent_mean - baseline_mean
    if standard_error <= 0:
        # Both windows are perfectly constant -- any nonzero delta at all
        # is a real, deterministic shift (z would otherwise be undefined/
        # infinite), zero delta is definitionally no drift.
        z_score = None
        flagged = delta != 0.0
    else:
        z_score = delta / standard_error
        flagged = abs(z_score) >= z_threshold

    return {
        "flagged": flagged,
        "reason": "drift_detected" if flagged else "within_expected_range",
        "recent_mean": round(recent_mean, 6),
        "baseline_mean": round(baseline_mean, 6),
        "delta": round(delta, 6),
        "z_score": round(z_score, 4) if z_score is not None else None,
        "z_threshold": z_threshold,
        "n_recent": len(recent_clean),
        "n_baseline": len(baseline_clean),
    }


__all__ = ["detect_metric_drift"]
