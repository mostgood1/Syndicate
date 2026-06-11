from __future__ import annotations

from itertools import combinations
from typing import Any

from syndicate.features.bankroll_manager import compute_bet_size as _compute_bet_size
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


def _parlay_correlation_profile(legs: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    pair_scores: list[float] = []
    pair_details: list[dict[str, Any]] = []
    for first_leg, second_leg in combinations(legs, 2):
        correlation = _candidate_correlation_score(first_leg, second_leg)
        correlation_details = _compute_correlation(first_leg, second_leg)
        pair_scores.append(correlation)
        pair_details.append(
            {
                "legs": [str(first_leg.get("name") or first_leg.get("pick") or "leg_1"), str(second_leg.get("name") or second_leg.get("pick") or "leg_2")],
                "correlation_score": round(correlation, 4),
                "same_game": bool(correlation_details.get("same_game")),
                "same_team": bool(correlation_details.get("same_team")),
                "same_subject": bool(correlation_details.get("same_subject")),
            }
        )
    if not pair_scores:
        return {"average_correlation": 0.0, "max_correlation": 0.0, "pair_scores": [], "pair_details": []}
    average_correlation = sum(pair_scores) / float(len(pair_scores))
    return {
        "average_correlation": round(average_correlation, 4),
        "max_correlation": round(max(abs(score) for score in pair_scores), 4),
        "pair_scores": [round(score, 4) for score in pair_scores],
        "pair_details": pair_details,
    }


def _combined_probability(legs: tuple[dict[str, Any], ...], correlation_profile: dict[str, Any]) -> float | None:
    probability = 1.0
    seen_probability = False
    for leg in legs:
        leg_probability = _candidate_parlay_probability(leg)
        if leg_probability is None:
            return None
        probability *= leg_probability
        seen_probability = True
    if not seen_probability:
        return None
    correlation_multiplier = 1.0 - min(0.25, max(0.0, float(correlation_profile.get("average_correlation") or 0.0)) * 0.35)
    return round(max(0.0, min(1.0, probability * correlation_multiplier)), 4)


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
    smart_min_leg_count = max(2, min(3, min_leg_count))
    smart_max_leg_count = max(2, min(3, max_leg_count))
    if smart_min_leg_count > smart_max_leg_count:
        smart_min_leg_count, smart_max_leg_count = smart_max_leg_count, smart_min_leg_count
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