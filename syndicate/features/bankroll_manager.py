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


def _decimal_price(value: Any) -> float | None:
    """A decimal (European) price, or None. Anything at or below 1.0 is not a
    price -- it would imply a probability >= 1 -- and is treated as absent."""
    price = _safe_float(value)
    if price is None or price <= 1.0:
        return None
    return price


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


def _refused_bet_size(candidate: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    """The compute_bet_size shape with every sizing number at zero and the
    refusal named. Probabilities are reported as None -- the value that was
    actually available -- never as an invented 0.5."""
    confidence = _confidence_scale(candidate)
    return {
        "model_probability": None,
        "implied_probability": None,
        "odds": candidate.get("odds"),
        "odds_adjustment": 0.0,
        "edge": 0.0,
        "kelly_fraction": 0.0,
        "confidence": round(confidence, 4),
        "cap_fraction": round(_cap_fraction(confidence), 4),
        "recommended_bet_size": 0.0,
        "reason": reason,
        # Nothing was differenced, so no basis was used. `None`, not
        # `"implied"`: a refusal must not read as a sized bet.
        "kelly_basis": None,
    }


# ---------------------------------------------------------------------------
# KELLY BASIS -- what the model probability is differenced AGAINST.
# ---------------------------------------------------------------------------
#: Env flag. Truthy => `edge = model - fair` when the candidate carries a
#: `fair_probability`; absent/false => `edge = model - implied(price)`, which is
#: the path every caller ran before 2026-09-08 and is bit-identical to it.
KELLY_ON_FAIR_ENV = "SYNDICATE_KELLY_ON_FAIR"
KELLY_BASIS_IMPLIED = "implied"
KELLY_BASIS_FAIR = "fair"


def kelly_on_fair_enabled() -> bool:
    raw = str(os.environ.get(KELLY_ON_FAIR_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def compute_bet_size(candidate: Mapping[str, Any], *, fair_probability: Any = None) -> dict[str, Any]:
    """Full Kelly x confidence, capped. Returns a dict; never raises on input.

    THE TWO BASES (`kelly_basis` in the result says which ran):

      `implied`  `edge = model - implied(price)`. Textbook Kelly: with `b` the
                 net payout, `(p*b - (1-p))/b == (p - 1/(b+1))/b`, and `1/(b+1)`
                 IS the price's own vig-inclusive implied probability. Default.

      `fair`     `edge = model - fair`, payout still from the QUOTED price. Only
                 when `SYNDICATE_KELLY_ON_FAIR` is truthy AND a `fair_probability`
                 (keyword, or the candidate's own key) is present. A caller with
                 no fair -- the Layer 1 pool, the parlay runtime -- stays on
                 `implied` whatever the flag says, and the result says so.

    THE TWO DIFFER BY EXACTLY `implied - fair`, WHICH HAS THE SIGN OF `-ev_pct`.
    On `portfolio_commit`'s rows `fair` is the consensus de-vig and `ev_pct > 0`
    means the price beats it, so `fair > implied` and the fair basis stakes
    LESS: it stakes only the model's disagreement with the market and drops the
    price-shopping term `fair - implied`. On a row priced at the hold
    (`ev_pct = -hold`) the sign flips and the fair basis stakes MORE. Neither is
    "the correct Kelly" -- they are two claims about what the edge IS, and the
    flag records which one the book was sized on so a settled sample can be cut
    by it. Measured at -110, model 0.5715, fair 0.5395 (ev 4.5%):

        implied  edge 0.0477  kelly 0.0525
        fair     edge 0.0320  kelly 0.0352
    """
    warn_if_compute_in_request_path("compute_bet_size")
    base_candidate = dict(candidate) if isinstance(candidate, Mapping) else {}

    model_probability = _safe_float(base_candidate.get("model_probability"))
    if model_probability is not None and model_probability > 1.0:
        model_probability /= 100.0

    fair = _safe_float(fair_probability if fair_probability is not None else base_candidate.get("fair_probability"))
    if fair is not None and fair > 1.0:
        fair /= 100.0
    if fair is not None and not (0.0 < fair < 1.0):
        fair = None

    implied_probability = _safe_float(base_candidate.get("implied_probability"))
    if implied_probability is not None and implied_probability > 1.0:
        implied_probability /= 100.0
    if implied_probability is None:
        implied_probability = _implied_probability_from_odds(base_candidate.get("odds"))
    # A decimal price is a price. Without this, a candidate carrying only
    # `decimal_price` would be refused below as unpriced, when it is priced.
    decimal_price = _decimal_price(base_candidate.get("decimal_price"))
    if implied_probability is None and decimal_price is not None:
        implied_probability = 1.0 / decimal_price

    # WP3 (2026-09-08): an absent probability used to default to 0.5 on
    # EITHER side, which made the edge 0 and the stake 0 silently -- a "no
    # bet" indistinguishable from "no input". It is now a named refusal that
    # keeps the full return shape (every caller reads the keys with .get and
    # treats 0 as no stake), so nothing downstream changes except that the
    # reason is visible.
    if model_probability is None:
        return _refused_bet_size(base_candidate, reason="no_model_probability")
    if implied_probability is None:
        return _refused_bet_size(base_candidate, reason="no_implied_probability")
    model_probability = _clamp(model_probability, 0.0, 1.0)
    implied_probability = _clamp(implied_probability, 0.0, 1.0)

    odds_adjustment = _odds_adjustment(base_candidate.get("odds"))
    if odds_adjustment is None and decimal_price is not None:
        odds_adjustment = max(0.01, decimal_price - 1.0)
    if odds_adjustment is None:
        odds_adjustment = max(0.01, 1.0 - implied_probability)

    kelly_basis = KELLY_BASIS_IMPLIED
    subtracted = implied_probability
    if fair is not None and kelly_on_fair_enabled():
        kelly_basis = KELLY_BASIS_FAIR
        subtracted = fair
    edge = model_probability - subtracted
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
        # WHICH PROBABILITY `edge` WAS DIFFERENCED AGAINST. Carried on every
        # result so a book sized under the flag can be told from one that was
        # not; the two are different claims and their ROIs are not poolable.
        "kelly_basis": kelly_basis,
        "fair_probability": round(fair, 4) if fair is not None else None,
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


def compute_board_stake(
    candidate: Mapping[str, Any],
    *,
    settled_sample_size: Any = 0,
    fair_probability: Any = None,
) -> dict[str, Any]:
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
    # `fair_probability` rides through to `compute_bet_size`, which decides the
    # basis; see its docstring. Absent => the vigged implied path, unchanged.
    sizing = compute_bet_size(candidate, fair_probability=fair_probability)
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


_DEFAULT_GAME_EXPOSURE_CAP = 0.05
_CORRELATED_LEG_DECAY = 0.5


def _game_exposure_cap() -> float:
    raw = str(os.environ.get("SYNDICATE_MAX_GAME_EXPOSURE_FRACTION") or "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_GAME_EXPOSURE_CAP
    except ValueError:
        value = _DEFAULT_GAME_EXPOSURE_CAP
    return _clamp(value, 0.001, 1.0)


def _exposure_group_key(candidate: Mapping[str, Any]) -> str:
    """Legs that rise and fall together. Prefer a real event/game id; fall
    back to the matchup text so a board whose builders never stamped an id
    still gets budgeted rather than silently treated as all-independent."""
    for field in ("event_id", "game_id", "gamePk", "game_pk"):
        value = _safe_text(candidate.get(field), "")
        if value:
            return f"{_safe_text(candidate.get('sport_slug') or candidate.get('sport'), '')}:{value}"
    matchup = _safe_text(candidate.get("matchup") or candidate.get("game") or "", "")
    return f"{_safe_text(candidate.get('sport_slug') or candidate.get('sport'), '')}:{matchup.lower()}"


def apply_exposure_budgets(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Cap total staked exposure per game and shrink correlated legs.

    The greedy low-correlation selection this replaces was removed for good
    reason -- a 0.65 threshold collapsed 100+ candidates to ~5 -- but
    nothing took its place, so the board could serve five legs off one game
    with no exposure penalty at all, each sized as if it were independent.
    Five correlated legs at 2% each is a 10% swing on one game's outcome,
    not five diversified 2% bets.

    Shrinks rather than drops, matching the standing call that board
    visibility stays complete and the judgment is carried on the card
    instead of hidden by removing it. Within a game the best-ranked leg
    keeps its full stake and each subsequent leg decays; if the group still
    exceeds the cap, every leg is scaled down proportionally so the
    ordering is preserved.
    """
    warn_if_compute_in_request_path("apply_exposure_budgets")
    cap = _game_exposure_cap()
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        stake = candidate.get("stake")
        if not isinstance(stake, Mapping):
            continue
        groups.setdefault(_exposure_group_key(candidate), []).append(candidate)

    adjusted_groups = 0
    for group in groups.values():
        if not group:
            continue
        ranked = sorted(
            group,
            key=lambda item: _safe_float(item.get("adjusted_score")) or _safe_float((item.get("stake") or {}).get("stake_fraction")) or 0.0,
            reverse=True,
        )
        decayed: list[float] = []
        for index, candidate in enumerate(ranked):
            base = _safe_float((candidate.get("stake") or {}).get("stake_fraction")) or 0.0
            decayed.append(base * (_CORRELATED_LEG_DECAY**index))
        total = sum(decayed)
        scale = 1.0 if total <= cap or total <= 0 else cap / total
        group_changed = False
        for candidate, decayed_stake in zip(ranked, decayed):
            stake = dict(candidate.get("stake") or {})
            original = _safe_float(stake.get("stake_fraction")) or 0.0
            final_stake = _clamp(decayed_stake * scale, 0.0, 1.0)
            if abs(final_stake - original) > 1e-9:
                group_changed = True
            stake["stake_fraction_pre_exposure"] = round(original, 5)
            stake["stake_fraction"] = round(final_stake, 5)
            stake["stake_units"] = round(final_stake * 100.0, 2)
            stake["exposure_group_size"] = len(ranked)
            stake["exposure_capped"] = bool(scale < 1.0)
            candidate["stake"] = stake
        if group_changed:
            adjusted_groups += 1

    return {
        "groups": len(groups),
        "adjusted_groups": adjusted_groups,
        "game_exposure_cap": round(cap, 4),
        "correlated_leg_decay": _CORRELATED_LEG_DECAY,
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