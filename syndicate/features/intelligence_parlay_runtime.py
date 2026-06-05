from __future__ import annotations

from itertools import combinations
from typing import Any


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
    decimal_prices = [
        float((leg.get("market_context") or {}).get("decimal_odds"))
        for leg in legs
        if isinstance(leg.get("market_context"), dict) and (leg.get("market_context") or {}).get("decimal_odds") is not None
    ]
    combined_decimal_odds = None
    combined_american_odds = None
    combined_implied_probability = None
    if len(decimal_prices) == len(legs) and decimal_prices:
        combined_decimal_odds = 1.0
        for price in decimal_prices:
            combined_decimal_odds *= price
        combined_decimal_odds = round(combined_decimal_odds, 3)
        combined_american_odds = decimal_to_american(combined_decimal_odds)
        if combined_decimal_odds > 1.0:
            combined_implied_probability = round((1.0 / combined_decimal_odds) * 100.0, 2)
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
        "combined_decimal_odds": combined_decimal_odds,
        "combined_odds": combined_american_odds,
        "combined_implied_probability": combined_implied_probability,
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
    leg_count = int(parlay.get("leg_count") or 0)
    american = american_odds_value = parlay.get("combined_odds")
    american = float(american_odds_value) if isinstance(american_odds_value, (int, float)) else 0.0
    risk_profile = str(preferences.get("risk_profile") or "balanced").strip().lower()
    requested_market_multiplier = 1.0 + (0.8 if preferences.get("requested_markets") else 0.0)
    if risk_profile == "conservative":
        return implied + (score * 0.35) + (market_fit_score * 0.45 * requested_market_multiplier) - pair_penalty - max(0, leg_count - 2) * 6.0
    if risk_profile == "aggressive":
        return (score * 0.4) + (market_fit_score * 0.35 * requested_market_multiplier) - (pair_penalty * 0.75) + max(0.0, american) / 25.0 + leg_count * 8.0
    return score + (market_fit_score * 0.5 * requested_market_multiplier) - pair_penalty + implied * 0.15 + (3.0 if parlay.get("cross_sport") else 0.0)


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
    for leg_count in range(min_leg_count, max_leg_count + 1):
        for legs in combinations(candidate_pool, leg_count):
            if not parlay_matches_preferences_fn(legs, resolved_preferences):
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