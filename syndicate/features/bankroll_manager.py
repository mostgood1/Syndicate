from __future__ import annotations

import os
from typing import Any, Mapping

from syndicate.features.correlation_engine import compute_correlation as _compute_correlation
from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _american_to_decimal(odds: float | None) -> float | None:
    if odds is None or odds == 0.0:
        return None
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def _odds_adjustment(odds: Any) -> float | None:
    american_odds = _safe_float(odds)
    if american_odds is None:
        return None
    decimal_odds = _american_to_decimal(american_odds)
    if decimal_odds is None:
        return None
    return max(0.01, decimal_odds - 1.0)


def _implied_probability_from_odds(odds: Any) -> float | None:
    american_odds = _safe_float(odds)
    if american_odds is None:
        return None
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def _confidence_scale(candidate: Mapping[str, Any]) -> float:
    confidence = _safe_float(candidate.get("confidence"))
    if confidence is None:
        confidence = _safe_float(candidate.get("model_confidence"))
    if confidence is None:
        confidence = _safe_float(candidate.get("confidence_score"))
    if confidence is None:
        confidence = 50.0
    if confidence > 1.0:
        confidence /= 100.0
    return _clamp(confidence, 0.0, 1.0)


def _cap_fraction(confidence: float) -> float:
    # Scale between 2% and 5% per play.
    return 0.02 + (0.03 * confidence)


def _volatility_score(candidate: Mapping[str, Any]) -> float:
    volatility = _safe_float(candidate.get("volatility_score"))
    if volatility is None:
        volatility = _safe_float(candidate.get("volatility"))
    if volatility is None:
        return 0.0
    if volatility > 1.0:
        volatility = volatility / (volatility + 1.0)
    return _clamp(volatility, 0.0, 1.0)


def _candidate_edge(candidate: Mapping[str, Any], bet_size_profile: Mapping[str, Any]) -> float:
    edge = _safe_float(candidate.get("adjusted_edge"))
    if edge is None:
        edge = _safe_float(candidate.get("edge"))
    if edge is None:
        edge = _safe_float(bet_size_profile.get("edge"))
    return edge if edge is not None else 0.0


def _portfolio_candidate_score(candidate: Mapping[str, Any], bet_size_profile: Mapping[str, Any]) -> float:
    edge = max(0.0, _candidate_edge(candidate, bet_size_profile))
    confidence = _safe_float(bet_size_profile.get("confidence")) or 0.0
    volatility = _volatility_score(candidate)
    bet_size = _safe_float(bet_size_profile.get("recommended_bet_size")) or 0.0
    return edge * (0.65 + confidence) * (1.0 - (volatility * 0.5)) * (0.75 + bet_size)


def _portfolio_risk_level(*, average_volatility: float, average_correlation: float, total_exposure: float) -> str:
    risk_score = (average_volatility * 0.45) + (max(0.0, average_correlation) * 0.35) + (_clamp(total_exposure, 0.0, 1.0) * 0.20)
    if risk_score < 0.34:
        return "low"
    if risk_score < 0.67:
        return "medium"
    return "high"


def compute_bet_size(candidate: Mapping[str, Any]) -> dict[str, Any]:
    warn_if_compute_in_request_path("compute_bet_size")
    base_candidate = dict(candidate) if isinstance(candidate, Mapping) else {}

    model_probability = _safe_float(base_candidate.get("model_probability"))
    if model_probability is not None and model_probability > 1.0:
        model_probability /= 100.0
    model_probability = _clamp(model_probability if model_probability is not None else 0.5, 0.0, 1.0)

    implied_probability = _safe_float(base_candidate.get("implied_probability"))
    if implied_probability is not None and implied_probability > 1.0:
        implied_probability /= 100.0
    if implied_probability is None:
        implied_probability = _implied_probability_from_odds(base_candidate.get("odds"))
    implied_probability = _clamp(implied_probability if implied_probability is not None else 0.5, 0.0, 1.0)

    odds_adjustment = _odds_adjustment(base_candidate.get("odds"))
    if odds_adjustment is None:
        odds_adjustment = max(0.01, 1.0 - implied_probability)

    edge = model_probability - implied_probability
    kelly_fraction = edge / odds_adjustment if odds_adjustment > 0.0 else 0.0
    kelly_fraction = max(0.0, kelly_fraction)

    confidence = _confidence_scale(base_candidate)
    cap_fraction = _cap_fraction(confidence)
    recommended_bet_size = min(kelly_fraction * confidence, cap_fraction)

    return {
        "model_probability": round(model_probability, 4),
        "implied_probability": round(implied_probability, 4),
        "odds": base_candidate.get("odds"),
        "odds_adjustment": round(odds_adjustment, 4),
        "edge": round(edge, 4),
        "kelly_fraction": round(kelly_fraction, 4),
        "confidence": round(confidence, 4),
        "cap_fraction": round(cap_fraction, 4),
        "recommended_bet_size": round(recommended_bet_size, 4),
    }


_DEFAULT_KELLY_MULTIPLIER = 0.25
_SAMPLE_SIZE_FOR_FULL_CREDIBILITY = 50
_MIN_SAMPLE_CREDIBILITY = 0.25


def _kelly_multiplier() -> float:
    raw = str(os.environ.get("SYNDICATE_KELLY_FRACTION_MULTIPLIER") or "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_KELLY_MULTIPLIER
    except ValueError:
        value = _DEFAULT_KELLY_MULTIPLIER
    return _clamp(value, 0.01, 1.0)


def _sample_credibility(settled_sample_size: Any) -> float:
    """How much to trust this market's own probability estimates yet.

    Kelly assumes the probability is CORRECT; it is famously punishing when
    it is not. Most of this repo's probability models are explicitly not
    backtested (the WNBA/NBA live sigma constants and the live win-prob
    logistic all say so in their own docstrings), and settlement was only
    just enabled, so most markets currently have zero settled bets. Sizing
    those at anything near full Kelly would be indefensible.

    Credibility ramps from a floor to 1.0 as real settled results
    accumulate. The floor is deliberately non-zero so an unproven market
    still produces a small, honest suggestion rather than a silent 0 that
    reads as a broken feature.
    """
    sample = _safe_float(settled_sample_size) or 0.0
    if sample <= 0:
        return _MIN_SAMPLE_CREDIBILITY
    ratio = sample / float(_SAMPLE_SIZE_FOR_FULL_CREDIBILITY)
    return _clamp(max(_MIN_SAMPLE_CREDIBILITY, ratio), _MIN_SAMPLE_CREDIBILITY, 1.0)


def compute_board_stake(candidate: Mapping[str, Any], *, settled_sample_size: Any = 0) -> dict[str, Any]:
    """Fractional-Kelly stake for a board candidate, as a fraction of bankroll.

    Wraps compute_bet_size (full Kelly x confidence, capped) and shrinks it
    twice: by a fixed fractional-Kelly multiplier (default quarter Kelly,
    SYNDICATE_KELLY_FRACTION_MULTIPLIER) and by how much settled evidence
    the market actually has. Both shrinkages are reported so the number is
    inspectable rather than a bare figure the reader has to trust.

    This is a sizing calculator over the user's own model output, not
    advice: it states what the stated edge and price imply under a
    deliberately conservative Kelly variant, and says so.
    """
    sizing = compute_bet_size(candidate)
    multiplier = _kelly_multiplier()
    credibility = _sample_credibility(settled_sample_size)
    full_kelly_fraction = _safe_float(sizing.get("kelly_fraction")) or 0.0
    cap_fraction = _safe_float(sizing.get("cap_fraction")) or 0.0
    staked_fraction = full_kelly_fraction * multiplier * credibility
    # The cap is an absolute ceiling and still applies after shrinkage.
    staked_fraction = _clamp(min(staked_fraction, cap_fraction), 0.0, 1.0)
    return {
        **sizing,
        "kelly_multiplier": round(multiplier, 4),
        "sample_credibility": round(credibility, 4),
        "settled_sample_size": int(_safe_float(settled_sample_size) or 0),
        "stake_fraction": round(staked_fraction, 5),
        "stake_units": round(staked_fraction * 100.0, 2),
        "stake_basis": "fractional_kelly_shrunk_by_settled_sample",
    }


def build_portfolio(
    recommendations: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    max_correlation_threshold: float = 0.65,
) -> dict[str, Any]:
    candidates = [dict(candidate) for candidate in recommendations if isinstance(candidate, Mapping)]
    if not candidates:
        return {
            "selected": [],
            "total_exposure": 0.0,
            "expected_return": 0.0,
            "risk_profile": {"level": "low", "average_volatility": 0.0, "average_correlation": 0.0, "diversification_score": 1.0},
            "summary": {"candidate_count": 0, "selected_count": 0, "skipped_high_correlation": 0},
        }

    scored_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        bet_size_profile = compute_bet_size(candidate)
        portfolio_score = _portfolio_candidate_score(candidate, bet_size_profile)
        scored_candidate = dict(candidate)
        scored_candidate.update(
            {
                "bet_size_profile": bet_size_profile,
                "portfolio_score": round(portfolio_score, 4),
                "portfolio_edge": round(_candidate_edge(candidate, bet_size_profile), 4),
                "portfolio_volatility": round(_volatility_score(candidate), 4),
            }
        )
        scored_candidates.append(scored_candidate)

    scored_candidates.sort(
        key=lambda item: (
            float(item.get("portfolio_score") or 0.0),
            float(item.get("portfolio_edge") or 0.0),
            float((item.get("bet_size_profile") or {}).get("recommended_bet_size") or 0.0),
            float(_safe_float(item.get("confidence")) or 0.0),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    skipped_high_correlation = 0
    for candidate in scored_candidates:
        bet_size_profile = candidate.get("bet_size_profile") if isinstance(candidate.get("bet_size_profile"), dict) else compute_bet_size(candidate)
        base_size = _safe_float(bet_size_profile.get("recommended_bet_size")) or 0.0
        if base_size <= 0.0:
            continue

        correlations: list[dict[str, Any]] = []
        strongest_correlation = 0.0
        for existing in selected:
            correlation_result = _compute_correlation(candidate, existing)
            correlation_score = _safe_float(correlation_result.get("correlation_score")) or 0.0
            correlations.append(
                {
                    "with": _safe_text(existing.get("name") or existing.get("pick") or existing.get("market"), "candidate"),
                    "correlation_score": round(correlation_score, 4),
                    "same_game": bool(correlation_result.get("same_game")),
                    "same_team": bool(correlation_result.get("same_team")),
                    "same_subject": bool(correlation_result.get("same_subject")),
                }
            )
            strongest_correlation = max(strongest_correlation, abs(correlation_score))

        if strongest_correlation > max_correlation_threshold:
            skipped_high_correlation += 1
            continue

        diversification_multiplier = 1.0 - min(0.45, strongest_correlation * 0.40)
        effective_bet_size = round(base_size * diversification_multiplier, 4)
        if effective_bet_size <= 0.0:
            continue

        candidate.update(
            {
                "bet_size_profile": bet_size_profile,
                "correlations": correlations,
                "strongest_correlation": round(strongest_correlation, 4),
                "diversification_multiplier": round(diversification_multiplier, 4),
                "effective_bet_size": effective_bet_size,
            }
        )
        selected.append(candidate)

    total_exposure = round(sum(_safe_float(item.get("effective_bet_size")) or 0.0 for item in selected), 4)
    expected_return = round(
        sum(
            (float(item.get("effective_bet_size") or 0.0) * max(0.0, float(item.get("portfolio_edge") or 0.0)))
            for item in selected
        ),
        4,
    )
    average_volatility = round(
        sum(float(item.get("portfolio_volatility") or 0.0) for item in selected) / float(len(selected)) if selected else 0.0,
        4,
    )
    average_correlation = round(
        sum(float(item.get("strongest_correlation") or 0.0) for item in selected) / float(len(selected)) if selected else 0.0,
        4,
    )
    risk_level = _portfolio_risk_level(
        average_volatility=average_volatility,
        average_correlation=average_correlation,
        total_exposure=total_exposure,
    )
    diversification_score = round(max(0.0, 1.0 - max(average_correlation, 0.0)), 4)

    return {
        "selected": selected,
        "total_exposure": total_exposure,
        "expected_return": expected_return,
        "risk_profile": {
            "level": risk_level,
            "average_volatility": average_volatility,
            "average_correlation": average_correlation,
            "diversification_score": diversification_score,
        },
        "summary": {
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "skipped_high_correlation": skipped_high_correlation,
            "max_correlation_threshold": round(max_correlation_threshold, 4),
        },
    }


__all__ = ["compute_bet_size", "build_portfolio"]