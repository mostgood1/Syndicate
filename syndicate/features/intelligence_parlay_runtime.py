from __future__ import annotations

import math
import os
from itertools import combinations
from typing import Any

from syndicate.features.bankroll_manager import compute_bet_size as _compute_bet_size
from syndicate.features.correlation_engine import (
    CORRELATION_BASIS_MEASURED as _CORRELATION_BASIS_MEASURED,
)
from syndicate.features.correlation_engine import compute_correlation as _compute_correlation


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_text(value, "")
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except Exception:
        return None


def _safe_probability(value: Any) -> float | None:
    probability = _safe_float(value)
    if probability is None:
        return None
    if probability > 1.0:
        probability /= 100.0
    if probability < 0.0:
        return None
    return max(0.0, min(1.0, probability))


def _candidate_portfolio_score(candidate: dict[str, Any]) -> float:
    adjusted_edge = _safe_float(candidate.get("adjusted_edge"))
    edge = adjusted_edge if adjusted_edge is not None else _safe_float(candidate.get("edge"))
    if edge is None:
        edge = (_safe_float(candidate.get("score")) or 0.0) / 100.0
    confidence = _safe_probability(candidate.get("confidence")) or 0.0
    score = _safe_float(candidate.get("score")) or 0.0
    return (max(0.0, edge) * 1.6) + (confidence * 0.8) + (score / 250.0)


def _candidate_parlay_probability(candidate: dict[str, Any]) -> float | None:
    for key in ("model_probability", "fair_probability", "confidence"):
        probability = _safe_probability(candidate.get(key))
        if probability is not None:
            return probability
    return None


def _candidate_correlation_score(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> float:
    try:
        return float(_compute_correlation(first_leg, second_leg).get("correlation_score") or 0.0)
    except Exception:
        return 0.0


def _parlay_is_low_correlation(legs: tuple[dict[str, Any], ...], threshold: float) -> bool:
    for first_leg, second_leg in combinations(legs, 2):
        if abs(_candidate_correlation_score(first_leg, second_leg)) > threshold:
            return False
    return True


#: Env flag for the MEASURED-JOINT n-leg pricer (`#621` Phase 5). ABSENT means
#: absent: every path below short-circuits and `_combined_probability` runs the
#: identical average-correlation Frechet interpolation it ran before, on the
#: identical inputs. That is asserted by an `off != on` reachability test rather
#: than believed (`tests/test_parlay_measured_joint.py`).
_MEASURED_JOINT_FLAG = "SYNDICATE_PARLAY_MEASURED_JOINT"

#: MLB ONLY, AND SAID OUT LOUD. The measured pairwise correlation comes from
#: `sim.joint`, a packed Spearman matrix that ONLY the MLB sim publishes -- no
#: other sport's engine emits a joint at all. Two gates therefore stand between
#: a non-MLB parlay and this code, and they are deliberately redundant:
#:   1. `correlation_engine`'s measured resolver is installed by
#:      `correlation_wiring.install_measured_correlation`, which builds an MLB
#:      index; every non-MLB pair comes back `None` and is a FALLBACK, counted.
#:   2. this sport check, which refuses the whole ticket up front.
#: Without (2) a cross-sport or NBA-only ticket would take the "measured" branch
#: with 0 measured pairs and 100% fallbacks -- arithmetically the same answer,
#: but reported as if a joint had been consulted. A generic path that silently
#: no-ops elsewhere is exactly what this constant exists to prevent.
_MEASURED_JOINT_SPORTS = frozenset({"mlb", "baseball_mlb", "baseball", "major league baseball"})

#: How far the MEASURED joint is allowed to move a parlay off independence, as a
#: fraction of the distance to the Frechet bound.
#:
#: WHY THERE IS STILL A CAP, AND WHY IT IS NOT 0.25.
#: `_PARLAY_CORRELATION_MAX_SHIFT` (0.25) bounds a number whose MAGNITUDE is not
#: trusted at all -- a sum of categorical flags that has never been scored
#: against an outcome, trusted for its sign and little else. That is not this
#: input. This shift is derived from a per-pair Spearman coefficient measured
#: over 1,000 simulations of the actual game, passed through
#: `threshold_correlation` so it is expressed in the same units as the bet, and
#: assembled by a second-order expansion that is EXACT in the pairwise
#: covariances. Holding it to a bound built for a flag-sum would clip real
#: measured dependence -- same-batter `home_runs x total_bases` measures
#: rho_S +0.86..+0.90 on the slates below, and 0.25 discards nearly all of it.
#:
#: It is NOT removed, for two reasons that survive the input getting better:
#:   * The expansion is second-order. Its truncation error grows with the size
#:     of the correction, so the regime where an uncapped shift would matter
#:     most is precisely the regime where the estimator is least trustworthy.
#:   * A mis-measured pair (a name collision, a stale label, a degenerate sim
#:     column) reaches bet SIZING through `bankroll_manager`. This repo has
#:     shipped a fictional edge to a picks surface and backed it out; the cap is
#:     the blast radius of that mistake, and it should be small even when the
#:     expected case is good.
#:
#: 0.85 IS SET FROM THE MEASURED DISTRIBUTION, over 181,476 same-game two-leg
#: tickets on 71 published joints (2026-09-05..09,
#: `scripts/measure_measured_joint_parlay.py`), which shows the cap has exactly
#: one job:
#:     cross-player pairs   n=173,808   p50 |w| 0.037   p99 0.187   MAX 0.365
#:     same-player pairs    n=  7,668   p50 |w| 0.593   p90 0.986   max 1.005
#: 95.8% of the population is cross-player and NEVER approaches any of these
#: bounds -- 0.25 was not restraining them, it was silently clipping 98.2% of
#: the same-player pairs. That tail is REAL, not noise: `home_runs > 0.5`
#: LOGICALLY IMPLIES `total_bases > 1.5`, so its true weight is 1.000 and the
#: estimator finds 0.81-0.98. At 0.85 the cap binds on 0.72% of all pairs and
#: every one of them is same-player.
#:
#: THE COST OF 0.85, STATED. Those logically-nested same-player pairs are
#: underpriced by the last 15% of the distance to a bound the ticket cannot
#: exceed anyway. That is a deliberate, bounded error in the CONSERVATIVE
#: direction (a lower `P(all legs win)` is a lower EV, not a higher one), and it
#: buys a reserve no single measurement can spend.
_MEASURED_JOINT_MAX_SHIFT = 0.85


def _effective_max_shift(pairs_measured: int, pairs_total: int) -> float:
    """Authority granted IN PROPORTION to what was actually measured.

    A ticket whose every pair came out of the joint earns the full measured
    bound. One where two of three pairs fell back to the heuristic is mostly
    still being priced off a flag-sum, and it gets a bound mostly still set for
    a flag-sum. This is the one place the coverage count is load-bearing rather
    than reportage: a measured share that drops silently makes the estimator
    quieter, instead of lending the heuristic authority it never earned.
    """
    if pairs_total <= 0:
        return _PARLAY_CORRELATION_MAX_SHIFT
    share = max(0.0, min(1.0, float(pairs_measured) / float(pairs_total)))
    return _PARLAY_CORRELATION_MAX_SHIFT + (
        (_MEASURED_JOINT_MAX_SHIFT - _PARLAY_CORRELATION_MAX_SHIFT) * share
    )


#: Process-cumulative coverage, because "the measured path is live" and "the
#: measured path answered for nothing" are otherwise indistinguishable -- the
#: failure `correlation_wiring`'s own docstring names. `pairs_fallback` is the
#: honest denominator: a pair absent from the 153-label matrix is NOT an
#: uncorrelated pair, it is a pair we did not measure, and it is counted here
#: instead of being folded silently into a zero.
_MEASURED_JOINT_COVERAGE: dict[str, int] = {
    "parlays_seen": 0,
    "parlays_measured": 0,
    "parlays_not_mlb": 0,
    "parlays_no_measured_pair": 0,
    "legs_total": 0,
    "legs_measured": 0,
    "pairs_total": 0,
    "pairs_measured": 0,
    "pairs_fallback": 0,
    "pairs_fallback_no_marginal": 0,
}


def measured_joint_enabled() -> bool:
    """Is the measured-joint pricer switched on for this process?"""
    return str(os.environ.get(_MEASURED_JOINT_FLAG, "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def measured_joint_coverage() -> dict[str, int]:
    """A snapshot of the coverage counters. Read it; do not mutate it."""
    return dict(_MEASURED_JOINT_COVERAGE)


def reset_measured_joint_coverage() -> None:
    for key in _MEASURED_JOINT_COVERAGE:
        _MEASURED_JOINT_COVERAGE[key] = 0


def _legs_are_measured_joint_sport(legs: tuple[dict[str, Any], ...]) -> bool:
    for leg in legs:
        sport = _safe_text(leg.get("sport_slug") or leg.get("sport"), "").lower()
        if sport not in _MEASURED_JOINT_SPORTS:
            return False
    return bool(legs)


def _threshold_correlation(rho: float, p_a: float | None, p_b: float | None) -> float | None:
    """Rank correlation of COUNTS -> correlation of the THRESHOLDED indicators.

    Imported lazily and by exception rather than at module scope: this module is
    cross-sport and `threshold_correlation` lives under `features/mlb/`. A
    top-level import would make every sport's parlay pricing fail to load on an
    MLB-side error. `None` here means "could not convert", which is a FALLBACK,
    never a zero.
    """
    try:
        from syndicate.features.mlb.threshold_correlation import threshold_correlation
    except Exception:
        return None
    try:
        return float(threshold_correlation(float(rho), p_a, p_b))
    except Exception:
        return None


def _parlay_correlation_profile(legs: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    measured_joint_on = measured_joint_enabled()
    sport_ok = _legs_are_measured_joint_sport(legs) if measured_joint_on else False
    leg_probabilities = [_candidate_parlay_probability(leg) for leg in legs]

    pair_scores: list[float] = []
    pair_details: list[dict[str, Any]] = []
    #: "i:j" -> indicator correlation to use in the n-leg expansion. Keyed by a
    #: STRING because this rides inside `correlation_profile` into a JSON
    #: payload, and a tuple key would raise at serialization time on a surface
    #: nobody tests with a 3-leg MLB ticket.
    pair_phi: dict[str, float] = {}
    pairs_measured = 0
    pairs_fallback = 0
    pairs_fallback_no_marginal = 0
    measured_leg_indices: set[int] = set()

    for (index_a, first_leg), (index_b, second_leg) in combinations(list(enumerate(legs)), 2):
        # ONE call, where there used to be two on identical arguments. Net
        # behaviour is unchanged (`_candidate_correlation_score` swallowed an
        # exception that the very next line then raised anyway), and it halves
        # the resolver traffic on a function that is already O(n^2).
        correlation_details = _compute_correlation(first_leg, second_leg)
        correlation = float(correlation_details.get("correlation_score") or 0.0)
        pair_scores.append(correlation)
        basis = _safe_text(correlation_details.get("correlation_basis"), "")
        detail: dict[str, Any] = {
            "legs": [str(first_leg.get("name") or first_leg.get("pick") or "leg_1"), str(second_leg.get("name") or second_leg.get("pick") or "leg_2")],
            "correlation_score": round(correlation, 4),
            "same_game": bool(correlation_details.get("same_game")),
            "same_team": bool(correlation_details.get("same_team")),
            "same_subject": bool(correlation_details.get("same_subject")),
        }
        if measured_joint_on and sport_ok:
            detail["correlation_basis"] = basis
            phi: float | None = None
            if basis == _CORRELATION_BASIS_MEASURED:
                p_a = leg_probabilities[index_a]
                p_b = leg_probabilities[index_b]
                if p_a is None or p_b is None:
                    pairs_fallback_no_marginal += 1
                else:
                    phi = _threshold_correlation(correlation, p_a, p_b)
            if phi is None:
                # EXPLICIT FALLBACK, NOT A ZERO. The pair keeps the heuristic
                # coefficient it would have had today, in the same per-pair
                # role. Mapping "unmeasured" onto 0.0 would assert independence,
                # which is a claim, not an absence.
                pairs_fallback += 1
                pair_phi["%d:%d" % (index_a, index_b)] = correlation
                detail["measured_joint_pair"] = False
            else:
                pairs_measured += 1
                measured_leg_indices.add(index_a)
                measured_leg_indices.add(index_b)
                pair_phi["%d:%d" % (index_a, index_b)] = phi
                detail["measured_joint_pair"] = True
                detail["threshold_correlation"] = round(phi, 4)
        pair_details.append(detail)

    if not pair_scores:
        return {"average_correlation": 0.0, "max_correlation": 0.0, "pair_scores": [], "pair_details": []}
    average_correlation = sum(pair_scores) / float(len(pair_scores))
    profile = {
        "average_correlation": round(average_correlation, 4),
        "max_correlation": round(max(abs(score) for score in pair_scores), 4),
        "pair_scores": [round(score, 4) for score in pair_scores],
        "pair_details": pair_details,
    }
    if measured_joint_on:
        applied = bool(sport_ok and pairs_measured > 0)
        profile["measured_joint"] = {
            "applied": applied,
            "sport_eligible": bool(sport_ok),
            "legs_total": len(legs),
            "legs_measured": len(measured_leg_indices),
            "pairs_total": len(pair_scores),
            "pairs_measured": pairs_measured,
            "pairs_fallback": pairs_fallback,
            "pairs_fallback_no_marginal": pairs_fallback_no_marginal,
            "max_shift": round(_effective_max_shift(pairs_measured, len(pair_scores)), 4),
            "max_shift_full": _MEASURED_JOINT_MAX_SHIFT,
            "pair_phi": pair_phi if applied else {},
        }
        _MEASURED_JOINT_COVERAGE["parlays_seen"] += 1
        _MEASURED_JOINT_COVERAGE["legs_total"] += len(legs)
        if not sport_ok:
            _MEASURED_JOINT_COVERAGE["parlays_not_mlb"] += 1
        else:
            _MEASURED_JOINT_COVERAGE["pairs_total"] += len(pair_scores)
            _MEASURED_JOINT_COVERAGE["pairs_measured"] += pairs_measured
            _MEASURED_JOINT_COVERAGE["pairs_fallback"] += pairs_fallback
            _MEASURED_JOINT_COVERAGE["pairs_fallback_no_marginal"] += pairs_fallback_no_marginal
            _MEASURED_JOINT_COVERAGE["legs_measured"] += len(measured_leg_indices)
            if applied:
                _MEASURED_JOINT_COVERAGE["parlays_measured"] += 1
            else:
                _MEASURED_JOINT_COVERAGE["parlays_no_measured_pair"] += 1
    return profile


#: How far the correlation SCORE is allowed to move a parlay off independence,
#: as a fraction of the distance to the Frechet bound. Capped because
#: `correlation_score` is a heuristic built from categorical flags
#: (`correlation_engine.compute_correlation`), NOT a measured correlation
#: coefficient -- so it is trusted for its SIGN and only partly for its
#: magnitude. Matches the authority the previous multiplier had (a <=25% move).
#: Raise it only against measured same-game correlations (`#621`).
_PARLAY_CORRELATION_MAX_SHIFT = 0.25


def _frechet_bounds(leg_probabilities: list[float]) -> tuple[float, float]:
    """The only values `P(all legs win)` can take, whatever the dependence.

    Upper: everything cannot be likelier than its likeliest single leg.
    Lower: `sum(p) - (n - 1)`, floored at 0 -- the most the legs can avoid
    overlapping. Interpolating between them cannot produce an invalid
    probability, which is why the adjustment is expressed this way rather than
    as a free multiplier on the product.
    """
    return (
        max(0.0, sum(leg_probabilities) - (len(leg_probabilities) - 1)),
        min(leg_probabilities),
    )


def _correlation_adjusted_probability(
    leg_probabilities: list[float],
    average_correlation: float,
    *,
    max_shift: float = _PARLAY_CORRELATION_MAX_SHIFT,
) -> float:
    """`P(all legs win)`, moved off independence in the direction the legs imply.

    THE PREVIOUS FORM HAD THE SIGN WRONG IN BOTH DIRECTIONS:

        correlation_multiplier = 1.0 - min(0.25, max(0.0, avg_corr) * 0.35)

      * POSITIVE correlation REDUCED the parlay. For an AND of legs, positive
        dependence makes the joint MORE likely than the product, not less -- so
        genuinely correlated same-game parlays were systematically underpriced.
      * NEGATIVE correlation did NOTHING, because `max(0.0, ...)` discarded it.
        That is the dangerous half: `compute_correlation` returns -0.30 for the
        same subject in opposite directions, -0.06 for opposing teams in one
        game, and takes a further -0.08 for opposed directions -- exactly the
        legs that CONFLICT. Priced as independent, a conflicting parlay's
        probability, and therefore its EV, was OVERSTATED.

    Now: interpolate between independence and the Frechet bound on the side the
    sign points to. Exact at zero correlation, monotone in it, and bounded by
    construction -- at full weight it reaches the comonotone (or countermonotone)
    extreme and never passes it.

    NOT A COPULA, and deliberately not dressed as one. `average_correlation` is
    a sum of categorical flags, not a measured coefficient, so its magnitude is
    capped (`_PARLAY_CORRELATION_MAX_SHIFT`). Replacing it with a MEASURED
    same-game correlation is `#621`; this function is where that value lands,
    and its shape does not change when it does -- `_measured_joint_probability`
    below computes a weight from the FULL pairwise matrix and hands it straight
    back to this function under a different `max_shift`. The default keeps every
    existing caller byte-for-byte identical.
    """
    independent = 1.0
    for leg_probability in leg_probabilities:
        independent *= leg_probability
    lower, upper = _frechet_bounds(leg_probabilities)
    weight = max(-1.0, min(1.0, average_correlation))
    weight = max(-max_shift, min(max_shift, weight))
    if weight >= 0.0:
        adjusted = independent + weight * (upper - independent)
    else:
        adjusted = independent + weight * (independent - lower)
    return max(0.0, min(1.0, adjusted))


def measured_joint_weight(
    leg_probabilities: list[float], pair_phi: dict[str, float]
) -> float | None:
    """The Frechet weight implied by the FULL measured pairwise matrix.

    THE THING THIS REPLACES. `_combined_probability` collapsed n(n-1)/2 pairwise
    coefficients into ONE arithmetic mean and interpolated by it. That discards
    the structure the joint exists to carry: a 3-leg MLB ticket of
    `Judge TB 1.5` + `Judge HR 0.5` + `Volpe hits 0.5` has one pair at +0.70 and
    two near +0.03, and their mean, +0.25, describes none of the three. Worse,
    the mean is invariant to WHICH pair is hot, so two tickets with completely
    different dependence structures price identically.

    THE ESTIMATOR, and it is not a second copula. For indicators X_i with
    P(X_i)=p_i, the exact expansion of P(all win) in the pairwise covariances is

        P = prod(p) + SUM_{i<j} Cov(X_i, X_j) * prod_{k != i,j} p_k + O(3rd)

    and `Cov(X_i, X_j) = phi_ij * sqrt(p_i q_i p_j q_j)`, where `phi_ij` is the
    INDICATOR correlation -- exactly what `threshold_correlation` produces from
    the joint's rank correlation of counts. For n=2 it is EXACT, not an
    approximation. Every pair enters on its own terms; nothing is averaged.

    The result is then expressed as a fraction of the distance from independence
    to the Frechet bound, so it re-enters `_correlation_adjusted_probability`
    unchanged in shape and is bounded by construction: a third-order term this
    expansion omits cannot push the answer outside the range a probability can
    occupy, because the interpolation clamps it there first.

    Returns None when there is nothing to say (fewer than 2 legs, a degenerate
    marginal, no span to the bound) -- never 0.0-as-unknown.
    """
    n = len(leg_probabilities)
    if n < 2 or not pair_phi:
        return None
    for p in leg_probabilities:
        if not (0.0 < p < 1.0):
            return None
    independent = 1.0
    for p in leg_probabilities:
        independent *= p
    if independent <= 0.0:
        return None
    correction = 0.0
    for key, phi in pair_phi.items():
        try:
            left, right = key.split(":")
            index_a, index_b = int(left), int(right)
        except (AttributeError, TypeError, ValueError):
            continue
        if not (0 <= index_a < n and 0 <= index_b < n) or index_a == index_b:
            continue
        p_a, p_b = leg_probabilities[index_a], leg_probabilities[index_b]
        covariance = float(phi) * math.sqrt(p_a * (1.0 - p_a) * p_b * (1.0 - p_b))
        others = independent / (p_a * p_b)
        correction += covariance * others
    if correction == 0.0:
        return 0.0
    lower, upper = _frechet_bounds(leg_probabilities)
    if correction > 0.0:
        span = upper - independent
        if span <= 0.0:
            return None
        return correction / span
    span = independent - lower
    if span <= 0.0:
        return None
    return correction / span


def _measured_joint_probability(
    leg_probabilities: list[float], measured_joint: dict[str, Any]
) -> float | None:
    pair_phi = measured_joint.get("pair_phi") or {}
    if not isinstance(pair_phi, dict) or not pair_phi:
        return None
    weight = measured_joint_weight(leg_probabilities, pair_phi)
    if weight is None:
        return None
    max_shift = float(measured_joint.get("max_shift") or _MEASURED_JOINT_MAX_SHIFT)
    return _correlation_adjusted_probability(leg_probabilities, weight, max_shift=max_shift)


def _combined_probability(legs: tuple[dict[str, Any], ...], correlation_profile: dict[str, Any]) -> float | None:
    leg_probabilities: list[float] = []
    for leg in legs:
        leg_probability = _candidate_parlay_probability(leg)
        if leg_probability is None:
            return None
        leg_probabilities.append(float(leg_probability))
    if not leg_probabilities:
        return None
    measured_joint = correlation_profile.get("measured_joint")
    if isinstance(measured_joint, dict) and measured_joint.get("applied"):
        measured = _measured_joint_probability(leg_probabilities, measured_joint)
        if measured is not None:
            return round(measured, 4)
        # The measured path declined (a degenerate marginal, no span). Today's
        # behaviour is the documented fallback, and the decline is recorded so
        # it is a number rather than a silence.
        measured_joint["applied"] = False
        measured_joint["declined"] = True
        _MEASURED_JOINT_COVERAGE["parlays_measured"] = max(
            0, _MEASURED_JOINT_COVERAGE["parlays_measured"] - 1
        )
        _MEASURED_JOINT_COVERAGE["parlays_no_measured_pair"] += 1
    average_correlation = float(correlation_profile.get("average_correlation") or 0.0)
    return round(_correlation_adjusted_probability(leg_probabilities, average_correlation), 4)


def _combined_expected_value(combined_probability: float | None, combined_decimal_odds: float | None, combined_bet_size: float) -> float | None:
    if combined_probability is None or combined_decimal_odds is None:
        return None
    expected_value = combined_bet_size * ((combined_probability * combined_decimal_odds) - 1.0)
    return round(expected_value, 4)


def _best_leg_candidate(candidate_pool: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidate_pool:
        return None
    return max(candidate_pool, key=_candidate_portfolio_score)


def build_parlay_payload(
    legs: tuple[dict[str, Any], ...],
    preferences: dict[str, Any],
    *,
    round_robin: bool = False,
    ticket_index: int | None = None,
    ticket_total: int | None = None,
    anchor_legs: list[dict[str, Any]] | None = None,
    candidate_summary,
    parlay_pair_penalty_fn,
    decimal_to_american,
    american_odds_value,
    american_odds_match,
    safe_text,
    parlay_stake_plan,
    parlay_rationale,
    parlay_label,
) -> dict[str, Any] | None:
    summary_legs = [candidate_summary(leg) for leg in legs]
    avg_score = sum(float(leg.get("score") or 0.0) for leg in legs) / float(len(legs))
    market_fit_scores = [float((leg.get("market_fit") or {}).get("market_fit_score") or 0.0) for leg in legs]
    avg_market_fit_score = sum(market_fit_scores) / float(len(market_fit_scores)) if market_fit_scores else 0.0
    pair_penalty = parlay_pair_penalty_fn(legs)
    correlation_profile = _parlay_correlation_profile(legs)
    decimal_prices = [
        float((leg.get("market_context") or {}).get("decimal_odds"))
        for leg in legs
        if isinstance(leg.get("market_context"), dict) and (leg.get("market_context") or {}).get("decimal_odds") is not None
    ]
    combined_decimal_odds = None
    combined_american_odds = None
    combined_implied_probability = None
    combined_probability = _combined_probability(legs, correlation_profile)
    combined_bet_size = None
    leg_bet_sizes: list[float] = []
    for leg in legs:
        leg_bet_size_profile = _compute_bet_size(leg)
        leg_bet_size = _safe_float(leg_bet_size_profile.get("recommended_bet_size"))
        if leg_bet_size is not None:
            leg_bet_sizes.append(leg_bet_size)
    if leg_bet_sizes:
        combined_bet_size = round(min(leg_bet_sizes), 4)
    if len(decimal_prices) == len(legs) and decimal_prices:
        combined_decimal_odds = 1.0
        for price in decimal_prices:
            combined_decimal_odds *= price
        combined_decimal_odds = round(combined_decimal_odds, 3)
        combined_american_odds = decimal_to_american(combined_decimal_odds)
        if combined_decimal_odds > 1.0:
            combined_implied_probability = round((1.0 / combined_decimal_odds) * 100.0, 2)
    combined_edge = None
    if combined_probability is not None and combined_implied_probability is not None:
        combined_edge = round(combined_probability - (combined_implied_probability / 100.0), 4)
    combined_expected_value = _combined_expected_value(combined_probability, combined_decimal_odds, combined_bet_size or 0.0)
    if not american_odds_match(american_odds_value(combined_american_odds), preferences, parlay=True):
        return None

    sports = sorted({safe_text(leg.get("sport"), "Sport") for leg in summary_legs})
    market_shapes = sorted({safe_text(leg.get("market_shape"), "market_shape") for leg in summary_legs if safe_text(leg.get("market_shape"), "")})
    market_labels = sorted({safe_text(leg.get("market_label"), "Market") for leg in summary_legs if safe_text(leg.get("market_label"), "")})
    stake_plan = parlay_stake_plan(preferences, ticket_total=ticket_total if round_robin else None)
    rationale = parlay_rationale(summary_legs)
    if market_labels:
        rationale = f"{rationale} Market focus: {', '.join(market_labels)}."
    if pair_penalty.get("pair_penalty_notes"):
        rationale = f"{rationale} Pair correlation penalties: {'; '.join(pair_penalty['pair_penalty_notes'])}."
    if stake_plan.get("stake_note"):
        rationale = f"{rationale} {stake_plan['stake_note']}"
    payload = {
        "label": parlay_label(legs, preferences, round_robin=round_robin, ticket_index=ticket_index, ticket_total=ticket_total),
        "legs": summary_legs,
        "leg_count": len(legs),
        "combined_score": round(avg_score, 2),
        "combined_market_fit_score": round(avg_market_fit_score, 2),
        "pair_correlation_penalty": pair_penalty.get("pair_penalty"),
        "pair_correlation_notes": pair_penalty.get("pair_penalty_notes"),
        "pair_correlation_breakdown": pair_penalty.get("pair_penalty_breakdown"),
        "correlation_profile": correlation_profile,
        "combined_decimal_odds": combined_decimal_odds,
        "combined_odds": combined_american_odds,
        "combined_implied_probability": combined_implied_probability,
        "combined_probability": combined_probability,
        "combined_edge": combined_edge,
        "combined_expected_value": combined_expected_value,
        "combined_bet_size": combined_bet_size,
        "rationale": rationale,
        "parlay_type": safe_text(preferences.get("parlay_type"), "standard"),
        "risk_profile": safe_text(preferences.get("risk_profile"), "balanced"),
        "correlation_tolerance": safe_text(preferences.get("correlation_tolerance"), "medium"),
        "cross_sport": len(sports) > 1,
        "sports": sports,
        "market_labels": market_labels,
        "market_shapes": market_shapes,
        "bankroll_amount": preferences.get("bankroll_amount"),
        "max_exposure_pct": preferences.get("max_exposure_pct"),
        "max_exposure_amount": preferences.get("max_exposure_amount"),
        "suggested_stake": stake_plan.get("suggested_stake"),
        "suggested_total_exposure": stake_plan.get("suggested_total_exposure"),
        "exposure_cap_amount": stake_plan.get("exposure_cap_amount"),
        "exposure_cap_source": stake_plan.get("exposure_cap_source"),
    }
    if isinstance(correlation_profile.get("measured_joint"), dict):
        # Surfaced at the TOP level as well as inside `correlation_profile`,
        # because "did the measured joint price this ticket, and over how many
        # pairs" has to be answerable from the served payload without knowing
        # where to dig. Present only when the flag is on -- absent means absent.
        payload["measured_joint"] = correlation_profile["measured_joint"]
    if round_robin:
        payload["round_robin_unit"] = preferences.get("round_robin_unit") or len(legs)
        if anchor_legs:
            payload["round_robin_group"] = anchor_legs
            payload["round_robin_group_size"] = len(anchor_legs)
    return payload


def parlay_rank_score(parlay: dict[str, Any], preferences: dict[str, Any]) -> float:
    score = float(parlay.get("combined_score") or 0.0)
    market_fit_score = float(parlay.get("combined_market_fit_score") or 0.0)
    pair_penalty = float(parlay.get("pair_correlation_penalty") or 0.0)
    implied = float(parlay.get("combined_implied_probability") or 0.0)
    combined_edge = float(parlay.get("combined_edge") or 0.0)
    combined_expected_value = float(parlay.get("combined_expected_value") or 0.0)
    leg_count = int(parlay.get("leg_count") or 0)
    american = american_odds_value = parlay.get("combined_odds")
    american = float(american_odds_value) if isinstance(american_odds_value, (int, float)) else 0.0
    risk_profile = str(preferences.get("risk_profile") or "balanced").strip().lower()
    requested_market_multiplier = 1.0 + (0.8 if preferences.get("requested_markets") else 0.0)
    if risk_profile == "conservative":
        return implied + (score * 0.35) + (market_fit_score * 0.45 * requested_market_multiplier) + (combined_edge * 80.0) + (combined_expected_value * 50.0) - pair_penalty - max(0, leg_count - 2) * 6.0
    if risk_profile == "aggressive":
        return (score * 0.4) + (market_fit_score * 0.35 * requested_market_multiplier) + (combined_edge * 90.0) + (combined_expected_value * 55.0) - (pair_penalty * 0.75) + max(0.0, american) / 25.0 + leg_count * 8.0
    return score + (market_fit_score * 0.5 * requested_market_multiplier) + (combined_edge * 85.0) + (combined_expected_value * 50.0) - pair_penalty + implied * 0.15 + (3.0 if parlay.get("cross_sport") else 0.0)


def build_round_robin_parlays(
    candidate_pool: list[dict[str, Any]],
    *,
    limit: int,
    preferences: dict[str, Any],
    max_leg_count: int,
    has_tight_exposure_cap,
    parlay_matches_preferences_fn,
    parlay_identity,
    build_parlay_payload_fn,
    candidate_summary,
    parlay_rank_score_fn,
) -> list[dict[str, Any]]:
    anchor_size = max(3, min(5, max_leg_count))
    if has_tight_exposure_cap(preferences):
        anchor_size = min(anchor_size, 3)
    if anchor_size > len(candidate_pool):
        return []
    anchor_groups: list[tuple[dict[str, Any], ...]] = []
    seen_groups: set[tuple[str, ...]] = set()
    for legs in combinations(candidate_pool, anchor_size):
        if not parlay_matches_preferences_fn(legs, preferences):
            continue
        identity = tuple(sorted(parlay_identity(leg) for leg in legs))
        if identity in seen_groups:
            continue
        seen_groups.add(identity)
        anchor_groups.append(legs)
    if not anchor_groups:
        return []

    best_anchor = sorted(
        anchor_groups,
        key=lambda legs: sum(float(leg.get("score") or 0.0) for leg in legs) / float(len(legs)),
        reverse=True,
    )[0]
    ticket_size = preferences.get("round_robin_unit") or 2
    ticket_size = max(2, min(ticket_size, anchor_size))
    tickets: list[dict[str, Any]] = []
    anchor_summary = [candidate_summary(leg) for leg in best_anchor]
    raw_tickets = list(combinations(best_anchor, ticket_size))
    for index, legs in enumerate(raw_tickets, start=1):
        if not parlay_matches_preferences_fn(legs, preferences):
            continue
        payload = build_parlay_payload_fn(
            legs,
            preferences,
            round_robin=True,
            ticket_index=index,
            ticket_total=len(raw_tickets),
            anchor_legs=anchor_summary,
        )
        if payload is not None:
            tickets.append(payload)
    tickets = sorted(tickets, key=lambda parlay: parlay_rank_score_fn(parlay, preferences), reverse=True)
    return tickets[:limit]


def build_parlays(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    preferences: dict[str, Any] | None = None,
    safe_text,
    has_tight_exposure_cap,
    parlay_matches_preferences_fn,
    parlay_identity,
    build_parlay_payload_fn,
    build_round_robin_parlays_fn,
    parlay_rank_score_fn,
) -> list[dict[str, Any]]:
    resolved_preferences = preferences or {}
    usable = [candidate for candidate in candidates if safe_text(candidate.get("odds"), "-") != "-"]
    if len(usable) < 2:
        usable = list(candidates)
    leg_min = resolved_preferences.get("parlay_leg_min")
    leg_max = resolved_preferences.get("parlay_leg_max")
    min_leg_count = max(2, min(5, int(leg_min))) if leg_min is not None else 2
    max_leg_count = max(2, min(5, int(leg_max))) if leg_max is not None else 3
    if min_leg_count > max_leg_count:
        min_leg_count, max_leg_count = max_leg_count, min_leg_count
    if str(resolved_preferences.get("parlay_type") or "standard").strip().lower() == "standard" and has_tight_exposure_cap(resolved_preferences):
        max_leg_count = min(max_leg_count, 2)
        min_leg_count = min(min_leg_count, max_leg_count)
    candidate_pool = usable[: max(8, min(len(usable), max_leg_count + 4))]
    if resolved_preferences.get("parlay_type") == "round_robin":
        return build_round_robin_parlays_fn(
            candidate_pool,
            limit=limit,
            preferences=resolved_preferences,
            max_leg_count=max_leg_count,
        )

    parlays: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    correlation_threshold = _safe_float(resolved_preferences.get("max_correlation_threshold"))
    if correlation_threshold is None:
        correlation_threshold = _safe_float(resolved_preferences.get("correlation_threshold"))
    if correlation_threshold is None:
        correlation_threshold = 0.45
    # Honor the requested leg window as-is. min/max_leg_count are already
    # clamped to [2, 5] above; a further min(3, ...) here silently rebuilt
    # every "four-leg parlay" request as 3-leg tickets. The combination
    # search stays bounded by search_window (<= limit*3+5 candidates), so
    # 5-leg requests are C(20,5)-scale at worst, not explosive.
    smart_min_leg_count = min_leg_count
    smart_max_leg_count = max_leg_count
    same_game_parlay = _safe_text(resolved_preferences.get("parlay_type"), "standard") == "same_game"

    ranked_pool = sorted(candidate_pool, key=_candidate_portfolio_score, reverse=True)
    search_window = ranked_pool[: max(8, min(len(ranked_pool), limit * 3 + 5))]
    for target_leg_count in range(smart_min_leg_count, smart_max_leg_count + 1):
        for legs in combinations(search_window, target_leg_count):
            if not parlay_matches_preferences_fn(legs, resolved_preferences):
                continue
            if not same_game_parlay and not _parlay_is_low_correlation(legs, correlation_threshold):
                continue
            identity = tuple(sorted(parlay_identity(leg) for leg in legs))
            if identity in seen:
                continue
            seen.add(identity)
            payload = build_parlay_payload_fn(legs, resolved_preferences)
            if payload is not None:
                parlays.append(payload)
    parlays = sorted(parlays, key=lambda parlay: parlay_rank_score_fn(parlay, resolved_preferences), reverse=True)
    return parlays[:limit]