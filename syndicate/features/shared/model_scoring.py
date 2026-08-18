"""Distributional model-quality scoring: CRPS, Brier/log-loss, reliability
curves, bias/dispersion decomposition.

Context: docs/reports/syndicate_learning_loop_plan_2026_08_03.md, Stage 2.

Why this exists: `intelligence_evaluation.compute_metrics` measures win
rate/ROI/CLV on SETTLED BETS ONLY -- a few dozen observations a week per
sport/market, since only published, taken candidates ever get graded. Every
sim in this repo (MLB Monte Carlo, hockeysim, soccersim, smartsim2) already
produces a projected mean and, in most cases, a spread/variance for
continuous quantities (runs, goals, yards, points) on EVERY candidate it
touches -- thousands a night per sport -- whether or not that candidate was
ever bet. Scoring those projections against realized outcomes with a proper
scoring rule (CRPS) needs no bet and no settlement at all, which is 10-100x
more observations per night than the win/loss loop can ever produce.

This module is pure math over (prediction, outcome) pairs -- it does not
read the ledger, the board, or any artifact itself. Callers (the
recalibration job in Stage 3, a future `/intelligence/accuracy` view, or an
ad hoc backtest script) supply the pairs.

Constraints:
- No side effects, no I/O, no caching -- every function here is pure so it
  is trivially unit-testable and safe to call from a request path or a
  background job alike.
- Never raises on malformed/missing input -- skips that observation instead
  (mirrors intelligence_evaluation._coerce_float's philosophy: a bad record
  should degrade sample size, not the whole batch).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Iterable, Mapping, Sequence

_NORMAL = NormalDist()


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


# ---------------------------------------------------------------------------
# CRPS -- Continuous Ranked Probability Score. Lower is better; 0 is
# perfect. Generalizes MAE to a full predictive distribution: a correct
# mean with an overconfident (too-narrow) sigma is penalized more than the
# same mean with a well-calibrated sigma, which plain MAE cannot see at
# all -- exactly the "bias vs. dispersion" distinction the plan doc's P8
# finding says this repo currently cannot make.
# ---------------------------------------------------------------------------


def crps_normal(actual: Any, mean: Any, sigma: Any) -> float | None:
    """Closed-form CRPS for a Normal(mean, sigma) forecast against a
    realized scalar outcome (Gneiting & Raftery 2007, eq. 21). Standard
    closed form -- no simulation needed since the sim's own output is
    already summarized as (mean, sigma) at the point this is called."""
    actual_value = _to_float(actual)
    mean_value = _to_float(mean)
    sigma_value = _to_float(sigma)
    if actual_value is None or mean_value is None or sigma_value is None or sigma_value <= 0:
        return None
    standardized = (actual_value - mean_value) / sigma_value
    return sigma_value * (
        standardized * (2.0 * _NORMAL.cdf(standardized) - 1.0)
        + 2.0 * _NORMAL.pdf(standardized)
        - 1.0 / math.sqrt(math.pi)
    )


def mean_crps(pairs: Iterable[tuple[Any, Any, Any]]) -> dict[str, Any]:
    """pairs: iterable of (actual, mean, sigma). Returns {mean_crps, n}."""
    scores: list[float] = []
    for actual, mean, sigma in pairs:
        score = crps_normal(actual, mean, sigma)
        if score is not None:
            scores.append(score)
    if not scores:
        return {"mean_crps": None, "sample_size": 0}
    return {"mean_crps": sum(scores) / len(scores), "sample_size": len(scores)}


def distribution_moments(distribution: Mapping[Any, Any]) -> dict[str, Any]:
    """Mean/sigma/draw-count of a `{value: count}` empirical PMF.

    The MLB sim persists exactly this shape (`so_dist`, `total_runs_dist`,
    `run_margin_dist`, ...): integer-keyed counts summing to the sim's draw
    count. `prop_projections._dist_mean` computes the mean of the same shape
    for the projection layer; this is the scoring layer's version and it also
    returns the SPREAD, which is the whole reason Phase 7 needs it -- a mean
    alone cannot tell "centred wrong" from "too confident" apart.

    sigma is the POPULATION standard deviation of the draws (the sim ran
    `n_draws` simulations and we have all of them), not a sample estimate.
    """
    total = 0.0
    weighted = 0.0
    pairs: list[tuple[float, float]] = []
    for raw_value, raw_count in (distribution or {}).items():
        value = _to_float(raw_value)
        count = _to_float(raw_count)
        if value is None or count is None or count <= 0:
            continue
        pairs.append((value, count))
        total += count
        weighted += value * count
    if total <= 0:
        return {"mean": None, "sigma": None, "n_draws": 0, "support_size": 0}
    mean = weighted / total
    variance = sum(count * (value - mean) ** 2 for value, count in pairs) / total
    return {
        "mean": mean,
        "sigma": math.sqrt(variance),
        "n_draws": total,
        "support_size": len(pairs),
    }


def crps_empirical(actual: Any, distribution: Mapping[Any, Any]) -> float | None:
    """CRPS against the sim's OWN empirical distribution -- no Normal assumed.

    Why this exists alongside `crps_normal`: `crps_normal` fits a Normal to
    (mean, sigma) and scores that. For the quantities this repo actually
    simulates -- strikeouts, earned runs, total runs, run margin -- the true
    predictive distribution is discrete, bounded below at zero, and skewed, so
    the Normal is a MODEL of the forecast rather than the forecast itself.
    `learnings.md` 2026-08-16 (FORBIDDEN: letting a fitted model judge when a
    model-free measurement is available) applies directly: where the sim's own
    draws are on hand, THEY are the evidence and the Normal is a hypothesis.
    `prop_projections._dist_prob_over` already takes this position for
    probabilities -- "Exact, not a normal approximation".

    Exact, by integrating the definition
        CRPS(F, y) = integral (F(x) - 1{x >= y})^2 dx
    over the step function F. The integrand is piecewise constant between
    consecutive breakpoints (the support points plus y itself), and is
    identically zero outside their range, so the sum below is the whole
    integral -- not a discretisation of it.
    """
    actual_value = _to_float(actual)
    if actual_value is None:
        return None

    weighted: dict[float, float] = {}
    total = 0.0
    for raw_value, raw_count in (distribution or {}).items():
        value = _to_float(raw_value)
        count = _to_float(raw_count)
        if value is None or count is None or count <= 0:
            continue
        weighted[value] = weighted.get(value, 0.0) + count
        total += count
    if total <= 0:
        return None

    support = sorted(weighted)
    breakpoints = sorted({*support, actual_value})

    score = 0.0
    cumulative = 0.0
    support_index = 0
    for index in range(len(breakpoints) - 1):
        left = breakpoints[index]
        right = breakpoints[index + 1]
        # Advance the CDF past every support point at or below `left`; F is
        # right-continuous, so mass exactly at `left` counts on [left, right).
        while support_index < len(support) and support[support_index] <= left:
            cumulative += weighted[support[support_index]]
            support_index += 1
        cdf = cumulative / total
        indicator = 1.0 if left >= actual_value else 0.0
        score += (right - left) * (cdf - indicator) ** 2
    return score


def pinball_loss(actual: Any, predicted_quantile: Any, quantile_level: float) -> float | None:
    """Quantile ("pinball") loss for a single quantile forecast -- the
    scoring rule for predictions expressed as a quantile (e.g. a player
    prop line implicitly claims some quantile) rather than a full
    mean/sigma distribution. quantile_level in (0, 1)."""
    actual_value = _to_float(actual)
    predicted_value = _to_float(predicted_quantile)
    if actual_value is None or predicted_value is None or not (0.0 < quantile_level < 1.0):
        return None
    error = actual_value - predicted_value
    if error >= 0:
        return quantile_level * error
    return (quantile_level - 1.0) * error


# ---------------------------------------------------------------------------
# Brier / log-loss / reliability -- for binary probability forecasts
# (moneyline win probability, over/under, prop over probability). Brier is
# already computed as a single aggregate in
# intelligence_evaluation._calibration; this adds log-loss (penalizes
# confident-and-wrong far more sharply -- the metric that actually matters
# for Kelly staking, which is directly a function of log-odds) and a real
# binned reliability curve (is 70%-confidence actually right ~70% of the
# time?), neither of which exist anywhere in the repo today.
# ---------------------------------------------------------------------------


def brier_score(probability: Any, outcome: Any) -> float | None:
    probability_value = _to_float(probability)
    outcome_value = _to_float(outcome)
    if probability_value is None or outcome_value is None:
        return None
    if not (0.0 <= probability_value <= 1.0) or outcome_value not in (0.0, 1.0):
        return None
    return (probability_value - outcome_value) ** 2


# Clamp away from exact 0/1 so a single confident-and-correct (or
# confident-and-wrong) observation can't produce -inf/+inf and wreck a
# batch mean -- standard practice for log-loss over real-world probability
# forecasts that are themselves never exactly 0 or 1.
_LOG_LOSS_EPSILON = 1e-6


def log_loss(probability: Any, outcome: Any) -> float | None:
    probability_value = _to_float(probability)
    outcome_value = _to_float(outcome)
    if probability_value is None or outcome_value is None:
        return None
    if not (0.0 <= probability_value <= 1.0) or outcome_value not in (0.0, 1.0):
        return None
    clamped = min(max(probability_value, _LOG_LOSS_EPSILON), 1.0 - _LOG_LOSS_EPSILON)
    if outcome_value == 1.0:
        return -math.log(clamped)
    return -math.log(1.0 - clamped)


def binary_calibration_metrics(pairs: Iterable[tuple[Any, Any]]) -> dict[str, Any]:
    """pairs: iterable of (probability, outcome). outcome truthy/1 = the
    forecast event happened. Returns mean Brier/log-loss + sample size."""
    brier_scores: list[float] = []
    log_losses: list[float] = []
    for probability, outcome in pairs:
        outcome_binary = 1.0 if outcome else 0.0
        brier = brier_score(probability, outcome_binary)
        if brier is not None:
            brier_scores.append(brier)
        loss = log_loss(probability, outcome_binary)
        if loss is not None:
            log_losses.append(loss)
    return {
        "brier_score": (sum(brier_scores) / len(brier_scores)) if brier_scores else None,
        "log_loss": (sum(log_losses) / len(log_losses)) if log_losses else None,
        "sample_size": len(brier_scores),
    }


def reliability_curve(pairs: Sequence[tuple[Any, Any]], *, n_bins: int = 10) -> list[dict[str, Any]]:
    """Bins predictions by predicted probability into n_bins equal-width
    buckets over [0, 1] and reports, per non-empty bucket, the predicted
    mean vs. the actual observed rate -- a well-calibrated model has
    predicted_mean == actual_rate in every bucket. This is the diagnostic
    a single aggregate Brier/MAE cannot provide: it can tell you overall
    accuracy is fine while hiding that 80%-confidence picks only hit 60%
    of the time (systematic overconfidence at the top end)."""
    if n_bins <= 0:
        return []
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for probability, outcome in pairs:
        probability_value = _to_float(probability)
        if probability_value is None or not (0.0 <= probability_value <= 1.0):
            continue
        outcome_binary = 1.0 if outcome else 0.0
        bucket_index = min(int(probability_value * n_bins), n_bins - 1)
        buckets[bucket_index].append((probability_value, outcome_binary))

    curve: list[dict[str, Any]] = []
    for bucket_index, entries in enumerate(buckets):
        if not entries:
            continue
        predicted_mean = sum(p for p, _ in entries) / len(entries)
        actual_rate = sum(o for _, o in entries) / len(entries)
        curve.append(
            {
                "bucket_low": round(bucket_index / n_bins, 4),
                "bucket_high": round((bucket_index + 1) / n_bins, 4),
                "predicted_mean": round(predicted_mean, 4),
                "actual_rate": round(actual_rate, 4),
                "sample_size": len(entries),
                "calibration_gap": round(actual_rate - predicted_mean, 4),
            }
        )
    return curve


# ---------------------------------------------------------------------------
# Bias vs. dispersion decomposition -- for continuous (mean, sigma)
# forecasts. A single MAE/RMSE cannot distinguish "the sim is centered
# wrong" (fixable with an additive shift) from "the sim's spread is wrong"
# (fixable with a multiplicative sigma scale) -- these need different
# fixes to CalibrationProfile's tunable seams, so conflating them into one
# error number (today's only option) actively hides which one to change.
# ---------------------------------------------------------------------------


def bias_dispersion_decomposition(triples: Iterable[tuple[Any, Any, Any]]) -> dict[str, Any]:
    """triples: iterable of (actual, mean, sigma). Returns:
    - mean_signed_error: actual - mean, averaged. Positive = sim runs low.
    - mean_absolute_error: MAE, sigma-agnostic (same units as the metric).
    - dispersion_ratio: mean(|actual - mean| / sigma). ~1.0 for a
      well-calibrated Normal (matches the expected |Z| for a standard
      normal, 2/sqrt(2*pi) ~= 0.7979, so compare against THAT constant, not
      1.0 -- see EXPECTED_DISPERSION_RATIO below). Above it: sigma too
      narrow (overconfident). Below it: sigma too wide (underconfident).
    """
    signed_errors: list[float] = []
    absolute_errors: list[float] = []
    dispersion_ratios: list[float] = []
    for actual, mean, sigma in triples:
        actual_value = _to_float(actual)
        mean_value = _to_float(mean)
        if actual_value is None or mean_value is None:
            continue
        error = actual_value - mean_value
        signed_errors.append(error)
        absolute_errors.append(abs(error))
        sigma_value = _to_float(sigma)
        if sigma_value is not None and sigma_value > 0:
            dispersion_ratios.append(abs(error) / sigma_value)
    if not signed_errors:
        return {"mean_signed_error": None, "mean_absolute_error": None, "dispersion_ratio": None, "sample_size": 0}
    return {
        "mean_signed_error": round(sum(signed_errors) / len(signed_errors), 4),
        "mean_absolute_error": round(sum(absolute_errors) / len(absolute_errors), 4),
        "dispersion_ratio": round(sum(dispersion_ratios) / len(dispersion_ratios), 4) if dispersion_ratios else None,
        "sample_size": len(signed_errors),
    }


# Expected value of E[|Z|] for Z ~ Normal(0, 1) -- the reference point
# dispersion_ratio should sit near for a correctly-scaled sigma.
EXPECTED_DISPERSION_RATIO = math.sqrt(2.0 / math.pi)


__all__ = [
    "crps_normal",
    "mean_crps",
    "crps_empirical",
    "distribution_moments",
    "pinball_loss",
    "brier_score",
    "log_loss",
    "binary_calibration_metrics",
    "reliability_curve",
    "bias_dispersion_decomposition",
    "EXPECTED_DISPERSION_RATIO",
]
