"""Phase 7: score CONTINUOUS projections against realized outcomes.

`#440` Part 4, Phase 7. Plan: `.syndicate/plan_2026-08-16_sim_scheduling.md`.

WHY THIS EXISTS. `intelligence_evaluation.compute_metrics` measures win
rate/ROI/CLV on SETTLED BETS -- a few dozen observations a week per sport, and
production has settled ZERO. Meanwhile the MLB sim writes a full 1000-draw
distribution for every pitcher market and every game total/margin, every night,
whether or not anything was bet. Scoring those needs no bet, no grading and no
settlement, which is where the plan's "10-100x more observations" comes from.
Measured for MLB 2026-08-17: ~30 pitchers/date x 7 markets over 78 local dates
is ~16k pitcher-market observations.

WHAT IT DELIBERATELY DOES NOT DO.

- **It does not read an artifact, the ledger or the board.** Callers supply
  joined observations, exactly as `model_scoring` does one layer down. The
  artifact reading lives in `scripts/score_projections.py` so this stays
  testable without I/O and safe to call from a worker or a script alike.
- **It does not touch `intelligence_evaluation.py`.** That module is the
  settled-bets path this work exists to route around, and it is claimed by
  another lane. Phase 7 needs neither.

THREE HONESTY RULES, each from a rule this repo already paid for.

1. **A cell below the sample floor reports `unmeasured`, not a number.**
   `projection_skill` already treats `unmeasured` as first-class; this follows
   that convention rather than inventing a second one. Slicing by market is
   what makes cells thin, so this is load-bearing, not polish.
2. **Every statistic travels with its `n`.** "A rate, not a count" -- five
   wrong findings in one session came from missing denominators.
3. **The model number is never reported alone.** Every cell carries a
   BASELINE: the constant forecast (the cell's own mean outcome). A prop model
   that cannot beat "always predict this pool's average" has no value however
   well it correlates -- the argument `backtest_mlb_props.py` was written to
   enforce, reused here rather than re-derived.

AND ONE MODELLING RULE. Where the sim's own draws exist, `crps_empirical` is
the score and `crps_normal` is reported BESIDE it as a diagnostic, never
instead of it. `learnings.md` 2026-08-16 (FORBIDDEN: letting a fitted model
judge when a model-free measurement is available) is exactly this situation:
the Normal is a model OF the forecast, not the forecast. The gap between the
two is itself informative -- a large one means the predictive distribution is
materially non-Normal, which is a fact about the sim worth knowing before
anyone fits a Gaussian calibration term to it in Phase 8.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.model_scoring import (
    EXPECTED_DISPERSION_RATIO,
    bias_dispersion_decomposition,
    crps_empirical,
    crps_normal,
    distribution_moments,
)

# A cell with fewer observations than this reports `unmeasured`. 30 is the
# conventional floor already used for WNBA game lines in state.md ("n=30 due
# ~2026-08-26"); keeping one number across the repo beats inventing a second.
DEFAULT_MIN_SAMPLE = 30


@dataclass(frozen=True)
class ProjectionObservation:
    """One (forecast, outcome) pair for one market on one subject.

    `distribution` is the sim's `{value: count}` PMF where it exists. When it
    does, `mean`/`sigma` are derived from it and any supplied values are
    ignored -- two disagreeing summaries of one forecast is a defect, not a
    fallback.
    """

    sport: str
    market: str
    actual: float
    segment: str = "full"
    distribution: Mapping[Any, Any] | None = None
    mean: float | None = None
    sigma: float | None = None
    subject_id: str | None = None
    date: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def resolved(self) -> tuple[float | None, float | None, int]:
        """Returns (mean, sigma, n_draws). The PMF wins where present."""
        if self.distribution:
            moments = distribution_moments(self.distribution)
            if moments["mean"] is not None:
                return moments["mean"], moments["sigma"], int(moments["n_draws"])
        return self.mean, self.sigma, 0


def _round(value: float | None, places: int = 4) -> float | None:
    return None if value is None else round(value, places)


def score_cell(
    observations: Sequence[ProjectionObservation],
    *,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Score one (sport, market, segment) cell. Never raises; a malformed
    observation degrades the sample size rather than the batch."""
    actuals: list[float] = []
    triples: list[tuple[float, float | None, float | None]] = []
    empirical: list[float] = []
    normal: list[float] = []
    both_forms: list[tuple[float, float]] = []
    draws: list[int] = []

    for observation in observations:
        mean, sigma, n_draws = observation.resolved()
        if mean is None:
            continue
        actual = observation.actual
        actuals.append(actual)
        triples.append((actual, mean, sigma))
        if n_draws:
            draws.append(n_draws)

        empirical_score = (
            crps_empirical(actual, observation.distribution) if observation.distribution else None
        )
        normal_score = crps_normal(actual, mean, sigma)
        if empirical_score is not None:
            empirical.append(empirical_score)
        if normal_score is not None:
            normal.append(normal_score)
        if empirical_score is not None and normal_score is not None:
            both_forms.append((empirical_score, normal_score))

    sample_size = len(actuals)
    decomposition = bias_dispersion_decomposition(triples)

    # THE BASELINE. A constant forecast at the cell's own mean outcome. This is
    # in-sample and therefore FLATTERS the baseline, which is the conservative
    # direction: a model that beats it here has beaten a baseline fitted on the
    # answers. Stated rather than buried -- an out-of-sample split is the
    # `#440` D4 change and is not done here.
    baseline_mae: float | None = None
    if actuals:
        pool_mean = fmean(actuals)
        baseline_mae = fmean(abs(value - pool_mean) for value in actuals)

    model_mae = decomposition["mean_absolute_error"]
    beats_baseline: bool | None = None
    if model_mae is not None and baseline_mae is not None:
        beats_baseline = model_mae < baseline_mae

    # The empirical-vs-Normal gap: how much the Gaussian summary misprices this
    # sim's own distribution. Large => do not fit a Gaussian correction to it.
    normal_gap: float | None = None
    if both_forms:
        normal_gap = fmean(normal_value - empirical_value for empirical_value, normal_value in both_forms)

    dispersion = decomposition["dispersion_ratio"]
    dispersion_verdict = None
    if dispersion is not None:
        if dispersion > EXPECTED_DISPERSION_RATIO * 1.1:
            dispersion_verdict = "sigma_too_narrow"
        elif dispersion < EXPECTED_DISPERSION_RATIO * 0.9:
            dispersion_verdict = "sigma_too_wide"
        else:
            dispersion_verdict = "sigma_calibrated"

    measured = sample_size >= min_sample
    return {
        "sample_size": sample_size,
        "min_sample": min_sample,
        # `unmeasured` is first-class, following projection_skill's precedent.
        "verdict": "measured" if measured else "unmeasured",
        "crps_empirical": _round(fmean(empirical)) if measured and empirical else None,
        "crps_empirical_n": len(empirical),
        # Reported BESIDE the empirical score as a diagnostic, never instead.
        "crps_normal_approx": _round(fmean(normal)) if measured and normal else None,
        "crps_normal_n": len(normal),
        "normal_minus_empirical": _round(normal_gap),
        "mean_signed_error": decomposition["mean_signed_error"] if measured else None,
        "mean_absolute_error": model_mae if measured else None,
        "dispersion_ratio": dispersion if measured else None,
        "expected_dispersion_ratio": round(EXPECTED_DISPERSION_RATIO, 4),
        "dispersion_verdict": dispersion_verdict if measured else None,
        "baseline_constant_mae": _round(baseline_mae) if measured else None,
        "beats_constant_baseline": beats_baseline if measured else None,
        "sim_draws_median": _median_int(draws),
    }


def _median_int(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def score_projections(
    observations: Iterable[ProjectionObservation],
    *,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Group observations into (sport, market, segment) cells and score each.

    The top-level counters report what was DROPPED as well as what was scored,
    because an instrument that silently narrows its own sample reads as
    "covered everything" when it did not.
    """
    grouped: dict[tuple[str, str, str], list[ProjectionObservation]] = defaultdict(list)
    dropped_no_mean = 0
    total = 0

    for observation in observations:
        total += 1
        mean, _sigma, _draws = observation.resolved()
        if mean is None:
            dropped_no_mean += 1
            continue
        grouped[(observation.sport, observation.market, observation.segment)].append(observation)

    cells: list[dict[str, Any]] = []
    for (sport, market, segment), items in sorted(grouped.items()):
        cell = score_cell(items, min_sample=min_sample)
        cell.update({"sport": sport, "market": market, "segment": segment})
        dates = {item.date for item in items if item.date}
        cell["date_count"] = len(dates)
        cell["date_span"] = [min(dates), max(dates)] if dates else None
        cells.append(cell)

    measured_cells = [cell for cell in cells if cell["verdict"] == "measured"]
    return {
        "cells": cells,
        "counters": {
            "observations_in": total,
            "observations_scored": total - dropped_no_mean,
            "dropped_no_model_mean": dropped_no_mean,
            "cells_total": len(cells),
            "cells_measured": len(measured_cells),
            "cells_unmeasured": len(cells) - len(measured_cells),
            "min_sample": min_sample,
        },
    }


__all__ = [
    "ProjectionObservation",
    "score_cell",
    "score_projections",
    "DEFAULT_MIN_SAMPLE",
]
