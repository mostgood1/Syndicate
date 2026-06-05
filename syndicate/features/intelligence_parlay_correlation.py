from __future__ import annotations

from itertools import combinations
from typing import Any


def parlay_leg_market_shape(
    leg: dict[str, Any],
    *,
    safe_text,
    market_shape_profile,
    market_key_from_text,
) -> str:
    market_shape = safe_text(leg.get("market_shape"), "")
    if market_shape:
        return market_shape
    market_fit = leg.get("market_fit") if isinstance(leg.get("market_fit"), dict) else {}
    market_shape = safe_text(market_fit.get("market_shape"), "")
    if market_shape:
        return market_shape
    market_key = safe_text(leg.get("market_key"), "")
    if market_key:
        return str(market_shape_profile(market_key, candidate_type=safe_text(leg.get("candidate_type"), "candidate")).get("shape") or "general_market")
    market = safe_text(leg.get("market"), "")
    if market:
        inferred_key = market_key_from_text(market, allow_fallback=True)
        if inferred_key:
            return str(market_shape_profile(inferred_key, candidate_type=safe_text(leg.get("candidate_type"), "candidate")).get("shape") or "general_market")
    return "general_market"


def parlay_leg_market_key(leg: dict[str, Any], *, safe_text, market_key_from_text) -> str:
    market_key = safe_text(leg.get("market_key"), "")
    if market_key:
        return market_key
    market_fit = leg.get("market_fit") if isinstance(leg.get("market_fit"), dict) else {}
    market_key = safe_text(market_fit.get("market_key"), "")
    if market_key:
        return market_key
    market = safe_text(leg.get("market"), "")
    if market:
        inferred_key = market_key_from_text(market, allow_fallback=True)
        if inferred_key:
            return inferred_key
    return "general_market"


def medium_correlation_pair_blocked(sport_slug: str, first_market_key: str, second_market_key: str, *, safe_text, sport_market_pair_blocks) -> bool:
    normalized_sport = safe_text(sport_slug, "").lower()
    normalized_pair = tuple(sorted((safe_text(first_market_key, "general_market").lower(), safe_text(second_market_key, "general_market").lower())))
    return (normalized_sport, normalized_pair) in sport_market_pair_blocks


def parlay_market_pair_penalty(sport_slug: str, first_market_key: str, second_market_key: str, *, safe_text, pair_penalties) -> float:
    normalized_sport = safe_text(sport_slug, "").lower()
    normalized_pair = tuple(sorted((safe_text(first_market_key, "general_market").lower(), safe_text(second_market_key, "general_market").lower())))
    return float(pair_penalties.get((normalized_sport, normalized_pair), 0.0))


def market_script_cluster(market_key: str, *, safe_text, market_script_clusters) -> str | None:
    return market_script_clusters.get(safe_text(market_key, "general_market").lower())


def parlay_script_cluster_pair_penalty(
    sport_slug: str,
    first_market_key: str,
    second_market_key: str,
    *,
    safe_text,
    market_script_clusters,
    script_cluster_pair_fallback_penalties,
) -> tuple[float, str | None]:
    normalized_sport = safe_text(sport_slug, "").lower()
    first_cluster = market_script_cluster(first_market_key, safe_text=safe_text, market_script_clusters=market_script_clusters)
    second_cluster = market_script_cluster(second_market_key, safe_text=safe_text, market_script_clusters=market_script_clusters)
    if not first_cluster or not second_cluster:
        return 0.0, None
    cluster_pair = tuple(sorted((first_cluster, second_cluster)))
    penalty = script_cluster_pair_fallback_penalties.get((normalized_sport, cluster_pair))
    if penalty is None:
        return 0.0, None
    cluster_label = first_cluster if first_cluster == second_cluster else f"{first_cluster}/{second_cluster}"
    return float(penalty), f"shared {cluster_label} script"


def parlay_script_cluster_penalty_multiplier(
    first_leg: dict[str, Any],
    second_leg: dict[str, Any],
    *,
    safe_text,
    candidate_team_key,
    candidate_subject_key,
    market_script_clusters,
    explicit_script_cluster_penalty_multipliers,
    parlay_leg_market_key_fn,
) -> tuple[float, str | None]:
    first_team = candidate_team_key(first_leg)
    second_team = candidate_team_key(second_leg)
    first_subject = candidate_subject_key(first_leg)
    second_subject = candidate_subject_key(second_leg)
    if not (first_team and second_team and first_subject and second_subject and first_subject != second_subject):
        return 1.0, None
    sport_slug = safe_text(first_leg.get("sport_slug"), "sport").lower()
    first_cluster = market_script_cluster(parlay_leg_market_key_fn(first_leg), safe_text=safe_text, market_script_clusters=market_script_clusters)
    second_cluster = market_script_cluster(parlay_leg_market_key_fn(second_leg), safe_text=safe_text, market_script_clusters=market_script_clusters)
    if not first_cluster or not second_cluster:
        return 1.0, None
    cluster_pair = tuple(sorted((first_cluster, second_cluster)))
    multiplier = explicit_script_cluster_penalty_multipliers.get((sport_slug, cluster_pair))
    if multiplier is None:
        return 1.0, None
    cluster_label = first_cluster if first_cluster == second_cluster else f"{first_cluster}/{second_cluster}"
    return float(multiplier), f"shared {cluster_label} script"


def parlay_leg_is_live(leg: dict[str, Any], *, safe_text) -> bool:
    if leg.get("is_live") is True:
        return True
    return "live" in safe_text(leg.get("surface_title"), "").lower()


def parlay_pair_penalty_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any], *, safe_text, live_multiplier, mixed_timing_multiplier) -> tuple[float, str | None]:
    first_live = parlay_leg_is_live(first_leg, safe_text=safe_text)
    second_live = parlay_leg_is_live(second_leg, safe_text=safe_text)
    if first_live and second_live:
        return live_multiplier, "live"
    if first_live or second_live:
        return mixed_timing_multiplier, "mixed timing"
    return 1.0, None


def parlay_pair_direction_multiplier(
    first_leg: dict[str, Any],
    second_leg: dict[str, Any],
    *,
    safe_text,
    candidate_selection_direction,
    market_script_clusters,
    script_cluster_opposing_direction_multipliers,
    opposing_direction_multiplier,
    parlay_leg_market_key_fn,
) -> tuple[float, str | None]:
    first_direction = candidate_selection_direction(first_leg)
    second_direction = candidate_selection_direction(second_leg)
    if first_direction != 0 and second_direction != 0 and first_direction != second_direction:
        sport_slug = safe_text(first_leg.get("sport_slug"), "sport").lower()
        first_cluster = market_script_cluster(parlay_leg_market_key_fn(first_leg), safe_text=safe_text, market_script_clusters=market_script_clusters)
        second_cluster = market_script_cluster(parlay_leg_market_key_fn(second_leg), safe_text=safe_text, market_script_clusters=market_script_clusters)
        if first_cluster and second_cluster:
            cluster_pair = tuple(sorted((first_cluster, second_cluster)))
            override = script_cluster_opposing_direction_multipliers.get((sport_slug, cluster_pair))
            if override is not None:
                return float(override), "opposing directions"
        return opposing_direction_multiplier, "opposing directions"
    return 1.0, None


def parlay_pair_subject_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any], *, candidate_subject_key, different_subject_multiplier) -> tuple[float, str | None]:
    first_subject = candidate_subject_key(first_leg)
    second_subject = candidate_subject_key(second_leg)
    if first_subject and second_subject and first_subject != second_subject:
        return different_subject_multiplier, "different players"
    return 1.0, None


def parlay_pair_team_multiplier(
    first_leg: dict[str, Any],
    second_leg: dict[str, Any],
    *,
    safe_text,
    candidate_team_key,
    candidate_subject_key,
    market_script_clusters,
    same_team_sport_market_pair_penalty_multipliers,
    same_team_script_cluster_penalty_multipliers,
    opposing_team_sport_market_pair_penalty_multipliers,
    opposing_team_script_cluster_penalty_multipliers,
    opposing_team_multiplier,
    parlay_leg_market_key_fn,
) -> tuple[float, str | None]:
    first_team = candidate_team_key(first_leg)
    second_team = candidate_team_key(second_leg)
    first_subject = candidate_subject_key(first_leg)
    second_subject = candidate_subject_key(second_leg)
    if first_team and second_team and first_subject and second_subject and first_subject != second_subject:
        sport_slug = safe_text(first_leg.get("sport_slug"), "sport").lower()
        market_pair = tuple(sorted((parlay_leg_market_key_fn(first_leg), parlay_leg_market_key_fn(second_leg))))
        cluster_pair = tuple(sorted(filter(None, (
            market_script_cluster(market_pair[0], safe_text=safe_text, market_script_clusters=market_script_clusters),
            market_script_cluster(market_pair[1], safe_text=safe_text, market_script_clusters=market_script_clusters),
        ))))
        if first_team == second_team:
            override = same_team_sport_market_pair_penalty_multipliers.get((sport_slug, market_pair))
            if override is not None:
                return float(override), "same team"
            cluster_override = same_team_script_cluster_penalty_multipliers.get((sport_slug, cluster_pair))
            if cluster_override is not None:
                return float(cluster_override), "same team"
            return 1.0, None
        override = opposing_team_sport_market_pair_penalty_multipliers.get((sport_slug, market_pair))
        if override is not None:
            return float(override), "opposing teams"
        cluster_override = opposing_team_script_cluster_penalty_multipliers.get((sport_slug, cluster_pair))
        if cluster_override is not None:
            return float(cluster_override), "opposing teams"
        return opposing_team_multiplier, "opposing teams"
    return 1.0, None


def format_pair_penalty_value(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parlay_pair_feature_profile(
    first_leg: dict[str, Any],
    second_leg: dict[str, Any],
    *,
    penalty_source: str,
    script_context: str | None,
    safe_text,
    candidate_team_key,
    candidate_subject_key,
    candidate_selection_direction,
    market_script_clusters,
    parlay_leg_market_key_fn,
) -> dict[str, Any]:
    first_market_key = parlay_leg_market_key_fn(first_leg)
    second_market_key = parlay_leg_market_key_fn(second_leg)
    first_cluster = market_script_cluster(first_market_key, safe_text=safe_text, market_script_clusters=market_script_clusters)
    second_cluster = market_script_cluster(second_market_key, safe_text=safe_text, market_script_clusters=market_script_clusters)
    first_team = candidate_team_key(first_leg)
    second_team = candidate_team_key(second_leg)
    first_subject = candidate_subject_key(first_leg)
    second_subject = candidate_subject_key(second_leg)
    first_direction = candidate_selection_direction(first_leg)
    second_direction = candidate_selection_direction(second_leg)

    team_relationship = None
    if first_team and second_team:
        team_relationship = "same_team" if first_team == second_team else "opposing_teams"
    subject_relationship = None
    if first_subject and second_subject:
        subject_relationship = "same_player" if first_subject == second_subject else "different_players"
    direction_relationship = None
    if first_direction != 0 and second_direction != 0:
        direction_relationship = "same_direction" if first_direction == second_direction else "opposing_directions"
    cluster_pair = [first_cluster, second_cluster] if first_cluster and second_cluster else None
    return {
        "penalty_source": penalty_source,
        "same_game": safe_text(first_leg.get("matchup"), "") == safe_text(second_leg.get("matchup"), ""),
        "team_relationship": team_relationship,
        "subject_relationship": subject_relationship,
        "direction_relationship": direction_relationship,
        "market_keys": [first_market_key, second_market_key],
        "script_cluster_pair": cluster_pair,
        "script_context": script_context,
    }


def parlay_pair_penalty(
    legs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    safe_text,
    market_label,
    candidate_team_key,
    candidate_subject_key,
    candidate_selection_direction,
    market_script_clusters,
    pair_penalties,
    script_cluster_pair_fallback_penalties,
    explicit_script_cluster_penalty_multipliers,
    script_cluster_opposing_direction_multipliers,
    same_team_sport_market_pair_penalty_multipliers,
    same_team_script_cluster_penalty_multipliers,
    opposing_team_sport_market_pair_penalty_multipliers,
    opposing_team_script_cluster_penalty_multipliers,
    live_multiplier,
    mixed_timing_multiplier,
    opposing_direction_multiplier,
    different_subject_multiplier,
    opposing_team_multiplier,
    parlay_leg_market_key_fn,
) -> dict[str, Any]:
    total_penalty = 0.0
    notes: list[str] = []
    breakdown: list[dict[str, Any]] = []
    for first_leg, second_leg in combinations(list(legs), 2):
        if safe_text(first_leg.get("matchup"), "") != safe_text(second_leg.get("matchup"), ""):
            continue
        first_sport = safe_text(first_leg.get("sport_slug"), "sport").lower()
        second_sport = safe_text(second_leg.get("sport_slug"), "sport").lower()
        if first_sport != second_sport:
            continue
        first_market_key = parlay_leg_market_key_fn(first_leg)
        second_market_key = parlay_leg_market_key_fn(second_leg)
        penalty = parlay_market_pair_penalty(first_sport, first_market_key, second_market_key, safe_text=safe_text, pair_penalties=pair_penalties)
        penalty_source = "market_pair" if penalty > 0.0 else "script_cluster_fallback"
        base_penalty = penalty
        script_context = None
        script_multiplier = 1.0
        if penalty <= 0.0:
            penalty, script_context = parlay_script_cluster_pair_penalty(
                first_sport,
                first_market_key,
                second_market_key,
                safe_text=safe_text,
                market_script_clusters=market_script_clusters,
                script_cluster_pair_fallback_penalties=script_cluster_pair_fallback_penalties,
            )
            if penalty <= 0.0:
                continue
            base_penalty = penalty
        else:
            script_multiplier, script_context = parlay_script_cluster_penalty_multiplier(
                first_leg,
                second_leg,
                safe_text=safe_text,
                candidate_team_key=candidate_team_key,
                candidate_subject_key=candidate_subject_key,
                market_script_clusters=market_script_clusters,
                explicit_script_cluster_penalty_multipliers=explicit_script_cluster_penalty_multipliers,
                parlay_leg_market_key_fn=parlay_leg_market_key_fn,
            )
        timing_multiplier, timing_context = parlay_pair_penalty_multiplier(
            first_leg,
            second_leg,
            safe_text=safe_text,
            live_multiplier=live_multiplier,
            mixed_timing_multiplier=mixed_timing_multiplier,
        )
        direction_multiplier, direction_context = parlay_pair_direction_multiplier(
            first_leg,
            second_leg,
            safe_text=safe_text,
            candidate_selection_direction=candidate_selection_direction,
            market_script_clusters=market_script_clusters,
            script_cluster_opposing_direction_multipliers=script_cluster_opposing_direction_multipliers,
            opposing_direction_multiplier=opposing_direction_multiplier,
            parlay_leg_market_key_fn=parlay_leg_market_key_fn,
        )
        subject_multiplier, subject_context = parlay_pair_subject_multiplier(
            first_leg,
            second_leg,
            candidate_subject_key=candidate_subject_key,
            different_subject_multiplier=different_subject_multiplier,
        )
        team_multiplier, team_context = parlay_pair_team_multiplier(
            first_leg,
            second_leg,
            safe_text=safe_text,
            candidate_team_key=candidate_team_key,
            candidate_subject_key=candidate_subject_key,
            market_script_clusters=market_script_clusters,
            same_team_sport_market_pair_penalty_multipliers=same_team_sport_market_pair_penalty_multipliers,
            same_team_script_cluster_penalty_multipliers=same_team_script_cluster_penalty_multipliers,
            opposing_team_sport_market_pair_penalty_multipliers=opposing_team_sport_market_pair_penalty_multipliers,
            opposing_team_script_cluster_penalty_multipliers=opposing_team_script_cluster_penalty_multipliers,
            opposing_team_multiplier=opposing_team_multiplier,
            parlay_leg_market_key_fn=parlay_leg_market_key_fn,
        )
        penalty = round(penalty * script_multiplier * timing_multiplier * direction_multiplier * subject_multiplier * team_multiplier, 2)
        total_penalty += penalty
        context_parts = [part for part in (script_context, timing_context, direction_context, subject_context, team_context) if part]
        context_note = f" {' + '.join(context_parts)}" if context_parts else ""
        notes.append(f"{market_label(first_market_key)} + {market_label(second_market_key)}{context_note} correlation penalty {format_pair_penalty_value(penalty)}")
        factor_entries = [{"kind": "base_pair_penalty", "source": penalty_source, "value": round(float(base_penalty), 2), "context": script_context}]
        for factor_kind, multiplier, context in (
            ("script_cluster_multiplier", script_multiplier, script_context),
            ("timing_multiplier", timing_multiplier, timing_context),
            ("direction_multiplier", direction_multiplier, direction_context),
            ("subject_multiplier", subject_multiplier, subject_context),
            ("team_multiplier", team_multiplier, team_context),
        ):
            if context and float(multiplier) != 1.0:
                factor_entries.append({"kind": factor_kind, "multiplier": round(float(multiplier), 2), "context": context})
        breakdown.append(
            {
                "sport_slug": first_sport,
                "matchup": safe_text(first_leg.get("matchup"), ""),
                "market_keys": [first_market_key, second_market_key],
                "market_labels": [market_label(first_market_key), market_label(second_market_key)],
                "pair_penalty": penalty,
                "feature_profile": parlay_pair_feature_profile(
                    first_leg,
                    second_leg,
                    penalty_source=penalty_source,
                    script_context=script_context,
                    safe_text=safe_text,
                    candidate_team_key=candidate_team_key,
                    candidate_subject_key=candidate_subject_key,
                    candidate_selection_direction=candidate_selection_direction,
                    market_script_clusters=market_script_clusters,
                    parlay_leg_market_key_fn=parlay_leg_market_key_fn,
                ),
                "factors": factor_entries,
            }
        )
    return {"pair_penalty": round(total_penalty, 2), "pair_penalty_notes": notes, "pair_penalty_breakdown": breakdown}


def medium_correlation_shape_limit(
    shape: str,
    *,
    safe_text,
    medium_correlation_shape_limits,
    medium_correlation_sport_shape_limits,
    medium_correlation_sport_market_limits,
    sport_slug: str | None = None,
    market_key: str | None = None,
) -> int:
    sport_key = safe_text(sport_slug, "").lower()
    market_key_value = safe_text(market_key, "").lower()
    normalized = safe_text(shape, "general_market") or "general_market"
    if sport_key and market_key_value:
        market_override = medium_correlation_sport_market_limits.get((sport_key, market_key_value))
        if market_override is not None:
            return int(market_override)
    if sport_key:
        override = medium_correlation_sport_shape_limits.get((sport_key, normalized))
        if override is not None:
            return int(override)
    return int(medium_correlation_shape_limits.get(normalized, medium_correlation_shape_limits["general_market"]))


def parlay_matches_preferences(
    legs: tuple[dict[str, Any], ...],
    preferences: dict[str, Any],
    *,
    safe_text,
    sport_market_pair_blocks,
    medium_correlation_shape_limits,
    medium_correlation_sport_shape_limits,
    medium_correlation_sport_market_limits,
    parlay_leg_market_shape_fn,
    parlay_leg_market_key_fn,
) -> bool:
    matchups = {safe_text(leg.get("matchup"), "") for leg in legs}
    sports = {safe_text(leg.get("sport_slug"), "sport") for leg in legs}
    markets = {safe_text(leg.get("market"), "market") for leg in legs}
    market_shapes = {parlay_leg_market_shape_fn(leg) for leg in legs}
    shape_counts: dict[str, int] = {}
    for leg in legs:
        shape = parlay_leg_market_shape_fn(leg)
        shape_counts[shape] = shape_counts.get(shape, 0) + 1
    parlay_type = safe_text(preferences.get("parlay_type"), "standard")
    correlation_tolerance = safe_text(preferences.get("correlation_tolerance"), "medium")
    correlation_explicit = bool(preferences.get("correlation_explicit"))

    if parlay_type == "same_game" and len(matchups) != 1:
        return False
    if parlay_type != "same_game" and correlation_tolerance in {"low", "medium"} and len(matchups) < len(legs):
        return False
    if preferences.get("cross_sport_required") and len(sports) < 2:
        return False
    if correlation_tolerance == "low" and len(markets) < len(legs):
        return False
    if correlation_tolerance == "low" and len(market_shapes) < len(legs):
        return False
    if correlation_tolerance == "medium" and correlation_explicit and shape_counts:
        sport_shape_counts: dict[tuple[str, str], int] = {}
        sport_shape_market_counts: dict[tuple[str, str, str], int] = {}
        matchup_sport_market_pairs: set[tuple[str, str, tuple[str, str]]] = set()
        for leg in legs:
            sport_shape_key = (safe_text(leg.get("sport_slug"), "sport").lower(), parlay_leg_market_shape_fn(leg))
            sport_shape_counts[sport_shape_key] = sport_shape_counts.get(sport_shape_key, 0) + 1
            sport_shape_market_key = (safe_text(leg.get("sport_slug"), "sport").lower(), parlay_leg_market_shape_fn(leg), parlay_leg_market_key_fn(leg))
            sport_shape_market_counts[sport_shape_market_key] = sport_shape_market_counts.get(sport_shape_market_key, 0) + 1
        if parlay_type == "same_game":
            for first_leg, second_leg in combinations(legs, 2):
                if safe_text(first_leg.get("matchup"), "") != safe_text(second_leg.get("matchup"), ""):
                    continue
                first_sport = safe_text(first_leg.get("sport_slug"), "sport").lower()
                second_sport = safe_text(second_leg.get("sport_slug"), "sport").lower()
                if first_sport != second_sport:
                    continue
                first_market_key = parlay_leg_market_key_fn(first_leg)
                second_market_key = parlay_leg_market_key_fn(second_leg)
                matchup_sport_market_pairs.add((first_sport, safe_text(first_leg.get("matchup"), ""), tuple(sorted((first_market_key, second_market_key)))))
        for (sport_slug, shape), count in sport_shape_counts.items():
            if count > medium_correlation_shape_limit(
                shape,
                safe_text=safe_text,
                medium_correlation_shape_limits=medium_correlation_shape_limits,
                medium_correlation_sport_shape_limits=medium_correlation_sport_shape_limits,
                medium_correlation_sport_market_limits=medium_correlation_sport_market_limits,
                sport_slug=sport_slug,
            ):
                return False
        for (sport_slug, shape, market_key), count in sport_shape_market_counts.items():
            if count > medium_correlation_shape_limit(
                shape,
                safe_text=safe_text,
                medium_correlation_shape_limits=medium_correlation_shape_limits,
                medium_correlation_sport_shape_limits=medium_correlation_sport_shape_limits,
                medium_correlation_sport_market_limits=medium_correlation_sport_market_limits,
                sport_slug=sport_slug,
                market_key=market_key,
            ):
                return False
        for sport_slug, _matchup, market_pair in matchup_sport_market_pairs:
            if medium_correlation_pair_blocked(sport_slug, market_pair[0], market_pair[1], safe_text=safe_text, sport_market_pair_blocks=sport_market_pair_blocks):
                return False
    return True