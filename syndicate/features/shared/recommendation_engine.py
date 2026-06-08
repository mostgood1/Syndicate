from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.intelligence_evaluation import build_reliability_profile
from syndicate.features.shared.source_roots import repo_root_from


SCHEMA_VERSION = 1
MODEL_VERSION = "recommendation-engine-v1"
DEFAULT_EVALUATION_LEDGER = repo_root_from(__file__) / "reports" / "intelligence" / "evaluation_ledger.jsonl"


@dataclass(frozen=True)
class DecisionPolicy:
    name: str
    edge_weight: float
    confidence_weight: float
    roi_weight: float
    calibration_weight: float
    market_fit_weight: float
    min_edge_bias: float = 0.0
    promotion_margin: float = 0.015
    min_sample_size: int = 8


POLICY_REGISTRY: dict[str, DecisionPolicy] = {
    "balanced": DecisionPolicy(
        name="balanced",
        edge_weight=0.30,
        confidence_weight=0.30,
        roi_weight=0.20,
        calibration_weight=0.15,
        market_fit_weight=0.05,
    ),
    "conservative": DecisionPolicy(
        name="conservative",
        edge_weight=0.15,
        confidence_weight=0.40,
        roi_weight=0.15,
        calibration_weight=0.25,
        market_fit_weight=0.05,
        min_edge_bias=0.015,
        promotion_margin=0.02,
    ),
    "aggressive": DecisionPolicy(
        name="aggressive",
        edge_weight=0.45,
        confidence_weight=0.15,
        roi_weight=0.20,
        calibration_weight=0.10,
        market_fit_weight=0.10,
        min_edge_bias=-0.005,
        promotion_margin=0.01,
    ),
}
DEFAULT_POLICY = "balanced"


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _coerce_probability(value: Any) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    if 0.0 <= numeric <= 1.0:
        return numeric
    if 1.0 < numeric <= 100.0:
        return numeric / 100.0
    return None


def _parse_american_odds(value: Any) -> float | None:
    text = str(value or "").strip().replace("+", "")
    if not text or text == "-":
        return None
    numeric = _coerce_float(text)
    if numeric is None:
        return None
    if numeric == 0:
        return None
    if numeric > 0:
        return 100.0 / (numeric + 100.0)
    absolute = abs(numeric)
    return absolute / (absolute + 100.0)


def _load_records_from_ledger(ledger_path: Path | str | None = None) -> list[dict[str, Any]]:
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_EVALUATION_LEDGER
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _record_market(record: Mapping[str, Any]) -> str | None:
    recommendation = _copy_mapping(record.get("recommendation"))
    response = _copy_mapping(record.get("response"))
    query = _copy_mapping(record.get("query"))
    value = (
        recommendation.get("market")
        or recommendation.get("market_key")
        or recommendation.get("market_label")
        or record.get("market")
        or response.get("market")
        or query.get("market")
    )
    text = str(value or "").strip().lower()
    return text or None


def _record_sport(record: Mapping[str, Any]) -> str | None:
    recommendation = _copy_mapping(record.get("recommendation"))
    response = _copy_mapping(record.get("response"))
    query = _copy_mapping(record.get("query"))
    value = (
        recommendation.get("sport")
        or recommendation.get("sport_slug")
        or record.get("sport")
        or response.get("sport")
        or query.get("sport")
    )
    text = str(value or "").strip().lower()
    return text or None


def _record_policy(record: Mapping[str, Any]) -> str | None:
    recommendation = _copy_mapping(record.get("recommendation"))
    response = _copy_mapping(record.get("response"))
    value = (
        record.get("decision_strategy")
        or recommendation.get("decision_strategy")
        or recommendation.get("policy")
        or response.get("decision_strategy")
        or response.get("policy")
    )
    text = str(value or "").strip().lower()
    return text or None


def _record_matches_policy(record: Mapping[str, Any], policy_name: str) -> bool:
    record_policy = _record_policy(record)
    if record_policy is None:
        return policy_name == DEFAULT_POLICY
    return record_policy == policy_name


def _event_id(candidate: Mapping[str, Any]) -> str:
    for key in ("event_id", "game_id", "game_pk", "matchup", "subject_key", "name"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    base = json.dumps({key: candidate.get(key) for key in ("sport_slug", "market", "pick", "line", "odds")}, sort_keys=True, default=str)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _selection(candidate: Mapping[str, Any]) -> str:
    selection = str(candidate.get("pick") or candidate.get("selection") or candidate.get("name") or "").strip()
    return selection or "Unknown selection"


def _market(candidate: Mapping[str, Any]) -> str:
    market = candidate.get("market_key") or candidate.get("market") or candidate.get("market_label") or "market"
    return str(market).strip().lower() or "market"


def _fair_probability(candidate: Mapping[str, Any]) -> float:
    for key in ("fair_probability", "model_probability", "confidence"):
        probability = _coerce_probability(candidate.get(key))
        if probability is not None:
            return probability
    score = _coerce_float(candidate.get("score"))
    if score is not None:
        return max(0.01, min(0.99, score / 100.0))
    return 0.5


def calculate_edge(candidate: Mapping[str, Any], *, fair_probability: float | None = None, implied_probability: float | None = None) -> dict[str, Any]:
    base_candidate = _copy_mapping(candidate)
    fair_probability_value = fair_probability if fair_probability is not None else _fair_probability(base_candidate)
    if implied_probability is None:
        implied_probability = _coerce_probability(base_candidate.get("implied_probability"))
    if implied_probability is None:
        market_context = _copy_mapping(base_candidate.get("market_context"))
        implied_probability = _coerce_probability(market_context.get("implied_probability"))
    if implied_probability is None:
        implied_probability = _parse_american_odds(base_candidate.get("odds"))
    edge = None
    if fair_probability_value is not None and implied_probability is not None:
        edge = round(float(fair_probability_value) - float(implied_probability), 4)
    elif _coerce_float(base_candidate.get("edge")) is not None:
        edge = round(float(_coerce_float(base_candidate.get("edge")) or 0.0) / 100.0, 4)
    return {
        "fair_probability": round(float(fair_probability_value), 4),
        "implied_probability": round(float(implied_probability), 4) if implied_probability is not None else None,
        "edge": edge,
    }


def _normalize_policy_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return DEFAULT_POLICY
    if text in POLICY_REGISTRY:
        return text
    if text in {"default", "base", "standard"}:
        return DEFAULT_POLICY
    return DEFAULT_POLICY


def _policy_spec(value: Any | None) -> DecisionPolicy:
    return POLICY_REGISTRY.get(_normalize_policy_name(value), POLICY_REGISTRY[DEFAULT_POLICY])


def _policy_experiment_key(candidates: Iterable[Mapping[str, Any]], *, sport: str | None = None) -> str:
    keys: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        keys.append(
            {
                "event_id": candidate.get("event_id") or candidate.get("game_id") or candidate.get("name"),
                "market": _market(candidate),
                "selection": _selection(candidate),
                "sport": str(sport or candidate.get("sport") or candidate.get("sport_slug") or "").strip().lower(),
            }
        )
    base = json.dumps(sorted(keys, key=lambda item: (str(item.get("sport")), str(item.get("event_id")), str(item.get("market")), str(item.get("selection")))), sort_keys=True, default=str)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _policy_bucket(experiment_key: str) -> int:
    return int(hashlib.sha1(experiment_key.encode("utf-8")).hexdigest(), 16) % 100


def _settled_outcome(record: Mapping[str, Any]) -> str | None:
    result = str(record.get("result") or "").strip().lower()
    if result in {"win", "loss"}:
        return result
    return None


def _policy_record_features(record: Mapping[str, Any]) -> dict[str, float]:
    recommendation = _copy_mapping(record.get("recommendation"))
    response = _copy_mapping(record.get("response"))
    source = recommendation or response or _copy_mapping(record)
    edge = abs(_coerce_float(source.get("edge")) or _coerce_float(record.get("edge")) or 0.0)
    confidence = _coerce_probability(source.get("confidence"))
    if confidence is None:
        confidence = _coerce_probability(source.get("model_probability"))
    if confidence is None:
        confidence = _coerce_probability(source.get("fair_probability"))
    if confidence is None:
        confidence = 0.5
    implied_probability = _coerce_probability(record.get("implied_probability"))
    if implied_probability is None:
        implied_probability = _coerce_probability(source.get("implied_probability"))
    calibration_error = 0.0
    outcome = _settled_outcome(record)
    if implied_probability is not None and outcome in {"win", "loss"}:
        actual = 1.0 if outcome == "win" else 0.0
        calibration_error = abs(implied_probability - actual)
    market_fit = _coerce_float(source.get("market_fit_score")) or _coerce_float(record.get("market_fit_score")) or 0.0
    roi = _coerce_float(record.get("pnl")) or 0.0
    stake = _coerce_float(record.get("stake")) or 1.0
    if stake:
        roi /= float(stake)
    return {
        "edge": edge,
        "confidence": max(0.0, min(1.0, confidence)),
        "calibration_error": max(0.0, min(1.0, calibration_error)),
        "market_fit": max(0.0, market_fit),
        "roi": roi,
    }


def _policy_alignment(policy: DecisionPolicy, features: Mapping[str, float]) -> float:
    edge_signal = min(1.0, float(features.get("edge") or 0.0) * 5.0)
    confidence_signal = max(0.0, min(1.0, float(features.get("confidence") or 0.0)))
    roi_signal = max(0.0, min(1.0, (float(features.get("roi") or 0.0) + 0.25) / 0.5))
    calibration_signal = 1.0 - max(0.0, min(1.0, float(features.get("calibration_error") or 0.0) / 0.25))
    market_fit_signal = min(1.0, float(features.get("market_fit") or 0.0) / 100.0)
    alignment = (
        policy.edge_weight * edge_signal
        + policy.confidence_weight * confidence_signal
        + policy.roi_weight * roi_signal
        + policy.calibration_weight * calibration_signal
        + policy.market_fit_weight * market_fit_signal
    )
    return max(0.0, min(1.0, alignment))


def compare_policies(
    records: Iterable[Mapping[str, Any]] | None = None,
    *,
    sport: str | None = None,
    policies: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    history_rows = [dict(record) for record in (records or []) if isinstance(record, Mapping)]
    selected_policies = [
        _normalize_policy_name(policy_name)
        for policy_name in (policies or POLICY_REGISTRY.keys())
        if _normalize_policy_name(policy_name) in POLICY_REGISTRY
    ]
    if DEFAULT_POLICY not in selected_policies:
        selected_policies.insert(0, DEFAULT_POLICY)
    comparisons: list[dict[str, Any]] = []
    for policy_name in selected_policies:
        policy = _policy_spec(policy_name)
        scoped_rows = [
            record
            for record in history_rows
            if (sport is None or _record_sport(record) in {None, sport})
            and _record_matches_policy(record, policy.name)
        ]
        settled_rows = [record for record in scoped_rows if _settled_outcome(record) is not None]
        if not settled_rows:
            comparisons.append(
                {
                    "policy": policy.name,
                    "sample_size": 0,
                    "settled_count": 0,
                    "weighted_roi": 0.0,
                    "weighted_win_rate": 0.0,
                    "average_alignment": 0.0,
                    "average_edge": 0.0,
                    "average_confidence": 0.0,
                    "average_calibration_error": 0.0,
                    "promotion_score": 0.0,
                    "promotion_margin": policy.promotion_margin,
                    "min_sample_size": policy.min_sample_size,
                }
            )
            continue
        weighted_return_total = 0.0
        weighted_win_total = 0.0
        weighted_alignment_total = 0.0
        weighted_edge_total = 0.0
        weighted_confidence_total = 0.0
        weighted_calibration_total = 0.0
        weight_total = 0.0
        for record in settled_rows:
            features = _policy_record_features(record)
            alignment = _policy_alignment(policy, features)
            weight = 0.65 + alignment
            outcome = _settled_outcome(record)
            pnl = _coerce_float(record.get("pnl")) or 0.0
            stake = _coerce_float(record.get("stake")) or 1.0
            record_return = pnl / float(stake) if stake else pnl
            weighted_return_total += record_return * weight
            weighted_win_total += (1.0 if outcome == "win" else 0.0) * weight
            weighted_alignment_total += alignment * weight
            weighted_edge_total += float(features.get("edge") or 0.0) * weight
            weighted_confidence_total += float(features.get("confidence") or 0.0) * weight
            weighted_calibration_total += float(features.get("calibration_error") or 0.0) * weight
            weight_total += weight
        weighted_roi = weighted_return_total / weight_total if weight_total else 0.0
        weighted_win_rate = weighted_win_total / weight_total if weight_total else 0.0
        average_alignment = weighted_alignment_total / weight_total if weight_total else 0.0
        average_edge = weighted_edge_total / weight_total if weight_total else 0.0
        average_confidence = weighted_confidence_total / weight_total if weight_total else 0.0
        average_calibration_error = weighted_calibration_total / weight_total if weight_total else 0.0
        promotion_score = (
            weighted_roi * 100.0
            + weighted_win_rate * 40.0
            + average_edge * 18.0
            + average_confidence * 10.0
            - average_calibration_error * 20.0
            + average_alignment * 12.0
        )
        comparisons.append(
            {
                "policy": policy.name,
                "sample_size": len(settled_rows),
                "settled_count": len(settled_rows),
                "weighted_roi": round(weighted_roi, 4),
                "weighted_win_rate": round(weighted_win_rate, 4),
                "average_alignment": round(average_alignment, 4),
                "average_edge": round(average_edge, 4),
                "average_confidence": round(average_confidence, 4),
                "average_calibration_error": round(average_calibration_error, 4),
                "promotion_score": round(promotion_score, 4),
                "promotion_margin": policy.promotion_margin,
                "min_sample_size": policy.min_sample_size,
            }
        )
    comparisons.sort(key=lambda item: (float(item.get("promotion_score") or 0.0), float(item.get("weighted_roi") or 0.0), float(item.get("weighted_win_rate") or 0.0)), reverse=True)
    return comparisons


def build_policy_optimization_summary(
    records: Iterable[Mapping[str, Any]] | None = None,
    *,
    sport: str | None = None,
    experiment_key: str | None = None,
    policies: Iterable[str] | None = None,
) -> dict[str, Any]:
    comparison = compare_policies(records, sport=sport, policies=policies)
    incumbent = next((item for item in comparison if item.get("policy") == DEFAULT_POLICY), comparison[0] if comparison else {"policy": DEFAULT_POLICY})
    leader = comparison[0] if comparison else incumbent
    selected_policy = DEFAULT_POLICY
    promoted = False
    if leader and incumbent:
        lead_score = float(leader.get("promotion_score") or 0.0)
        incumbent_score = float(incumbent.get("promotion_score") or 0.0)
        lead_delta = lead_score - incumbent_score
        leader_policy = str(leader.get("policy") or DEFAULT_POLICY)
        if leader_policy == DEFAULT_POLICY:
            selected_policy = DEFAULT_POLICY
        elif int(leader.get("sample_size") or 0) >= int(leader.get("min_sample_size") or POLICY_REGISTRY[DEFAULT_POLICY].min_sample_size) and lead_delta >= float(leader.get("promotion_margin") or POLICY_REGISTRY[leader_policy].promotion_margin):
            selected_policy = leader_policy
            promoted = True
        elif experiment_key and abs(lead_delta) <= max(float(leader.get("promotion_margin") or 0.015), float(incumbent.get("promotion_margin") or 0.015)):
            bucket = _policy_bucket(experiment_key)
            selected_policy = leader_policy if bucket >= 50 else DEFAULT_POLICY
        else:
            selected_policy = DEFAULT_POLICY
    return {
        "selected_policy": selected_policy,
        "incumbent_policy": DEFAULT_POLICY,
        "leader_policy": leader.get("policy") if leader else DEFAULT_POLICY,
        "promoted": promoted,
        "policy_comparison": comparison,
    }


def select_policy(
    records: Iterable[Mapping[str, Any]] | None = None,
    *,
    sport: str | None = None,
    experiment_key: str | None = None,
    policies: Iterable[str] | None = None,
) -> str:
    summary = build_policy_optimization_summary(records, sport=sport, experiment_key=experiment_key, policies=policies)
    return str(summary.get("selected_policy") or DEFAULT_POLICY)


def _market_profile(records: list[dict[str, Any]], *, sport: str | None, market: str) -> dict[str, Any]:
    scoped_records = [record for record in records if (sport is None or _record_sport(record) in {None, sport}) and _record_market(record) == market]
    return build_reliability_profile(records=scoped_records, sport=sport)


def _candidate_policy_key(candidates: Iterable[Mapping[str, Any]], *, sport: str | None = None) -> str:
    return _policy_experiment_key(candidates, sport=sport)


def filter_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    policy: str | None = None,
    min_edge: float = 0.0,
) -> list[dict[str, Any]]:
    candidate_rows = [_copy_mapping(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    history_rows = [dict(record) for record in (evaluation_records or _load_records_from_ledger(ledger_path)) if isinstance(record, Mapping)]
    sport_profile = build_reliability_profile(records=history_rows, sport=sport)
    policy_spec = _policy_spec(policy or select_policy(history_rows, sport=sport))
    filtered: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        market = _market(candidate)
        market_profile = _market_profile(history_rows, sport=sport, market=market)
        edge_data = calculate_edge(candidate)
        fair_probability = edge_data["fair_probability"]
        implied_probability = edge_data["implied_probability"]
        edge = edge_data["edge"]
        reliability_multiplier = float(sport_profile.get("reliability_multiplier") or 1.0) * float(market_profile.get("reliability_multiplier") or 1.0)
        calibration_error = float(market_profile.get("calibration_error") or sport_profile.get("calibration_error") or 0.0)
        market_roi = _coerce_float(market_profile.get("metrics", {}).get("roi"))
        market_sample = int(market_profile.get("sample_size") or 0)
        threshold = float(min_edge) + float(policy_spec.min_edge_bias)
        if market_sample >= 3 and market_roi is not None and market_roi < -0.04:
            threshold += min(0.06, abs(market_roi) * 0.30)
        if market_sample >= 3 and calibration_error > 0.18:
            threshold += min(0.04, calibration_error * 0.15)
        if reliability_multiplier < 0.88:
            threshold += 0.01
        if edge is not None and edge < threshold:
            continue
        enriched = dict(candidate)
        enriched.update(
            {
                "event_id": _event_id(candidate),
                "market": market,
                "selection": _selection(candidate),
                "fair_probability": fair_probability,
                "implied_probability": implied_probability,
                "edge": edge,
                "recommendation_id": candidate.get("recommendation_id") or f"reco_{uuid.uuid4().hex[:12]}",
                "model_version": str(candidate.get("model_version") or MODEL_VERSION),
                "risk_flags": [
                    note
                    for note in (
                        f"Calibration error is {calibration_error:.2f} for {market}.",
                        f"Market ROI is {market_roi:.2f}." if market_roi is not None else "",
                        f"Reliability multiplier is {reliability_multiplier:.3f}.",
                    )
                    if note
                ],
                "market_profile": market_profile,
                "sport_profile": sport_profile,
            }
        )
        filtered.append(enriched)
    return filtered


def rank_recommendations(
    candidates: Iterable[Mapping[str, Any]],
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    policy: str | None = None,
    experiment_key: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    candidate_rows = [_copy_mapping(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    if experiment_key is None:
        experiment_key = _candidate_policy_key(candidate_rows, sport=sport)
    selected_policy = _normalize_policy_name(policy or select_policy(evaluation_records or _load_records_from_ledger(ledger_path), sport=sport, experiment_key=experiment_key))
    policy_spec = _policy_spec(selected_policy)
    filtered_candidates = filter_candidates(
        candidate_rows,
        sport=sport,
        ledger_path=ledger_path,
        evaluation_records=evaluation_records,
        policy=selected_policy,
    )
    history_rows = [dict(record) for record in (evaluation_records or _load_records_from_ledger(ledger_path)) if isinstance(record, Mapping)]
    sport_profile = build_reliability_profile(records=history_rows, sport=sport)
    scored: list[dict[str, Any]] = []
    for candidate in filtered_candidates:
        market = str(candidate.get("market") or "market").strip().lower() or "market"
        market_profile = _market_profile(history_rows, sport=sport, market=market)
        edge = candidate.get("edge")
        fair_probability = float(candidate.get("fair_probability") or 0.5)
        confidence = _coerce_probability(candidate.get("confidence")) or fair_probability
        base_score = _coerce_float(candidate.get("score")) or 0.0
        market_fit_score = _coerce_float(candidate.get("market_fit_score")) or 0.0
        market_strength = float(market_profile.get("reliability_multiplier") or 1.0)
        sport_strength = float(sport_profile.get("reliability_multiplier") or 1.0)
        edge_bonus = float(edge or 0.0) * 100.0
        calibration_error = float(market_profile.get("calibration_error") or sport_profile.get("calibration_error") or 0.0)
        roi = _coerce_float(market_profile.get("metrics", {}).get("roi")) or 0.0
        adjusted_score = (
            base_score * sport_strength * market_strength * (0.85 + policy_spec.confidence_weight * 0.30)
            + market_fit_score * (0.20 + policy_spec.market_fit_weight * 0.60)
            + edge_bonus * (0.50 + policy_spec.edge_weight)
            + confidence * 10.0 * (0.75 + policy_spec.confidence_weight)
            + roi * 20.0 * (0.70 + policy_spec.roi_weight)
            - calibration_error * 12.0 * (0.65 + policy_spec.calibration_weight)
        )
        reasoning = str(candidate.get("rationale") or candidate.get("summary") or candidate.get("writeup") or candidate.get("name") or "Recommendation built from the current board.").strip()
        risk_factors = list(candidate.get("risk_factors") or [])
        for note in candidate.get("risk_flags") or []:
            if note not in risk_factors:
                risk_factors.append(note)
        if candidate.get("is_live"):
            risk_factors.append("Live markets can move quickly and reduce the original edge.")
        confidence_drivers = list(candidate.get("confidence_drivers") or [])
        confidence_drivers.extend(
            [
                f"Fair probability {fair_probability:.3f}",
                f"Historical reliability multiplier {sport_strength * market_strength:.3f}",
                f"Calibration error {calibration_error:.3f}",
            ]
        )
        recommendation = dict(candidate)
        recommendation.update(
            {
                "schema_version": SCHEMA_VERSION,
                "recommendation_id": candidate.get("recommendation_id") or f"reco_{uuid.uuid4().hex[:12]}",
                "event_id": candidate.get("event_id") or _event_id(candidate),
                "market": market,
                "selection": candidate.get("selection") or _selection(candidate),
                "odds": candidate.get("odds"),
                "fair_probability": round(fair_probability, 4),
                "edge": round(float(edge or 0.0), 4),
                "confidence": round(max(0.05, min(0.99, confidence * sport_strength * market_strength)), 2),
                "model_version": str(candidate.get("model_version") or MODEL_VERSION),
                "reasoning": reasoning,
                "risk_factors": risk_factors[:5],
                "confidence_drivers": confidence_drivers[:5],
                "historical_profile": {
                    "sport": sport_profile,
                    "market": market_profile,
                    "policy_comparison": build_policy_optimization_summary(history_rows, sport=sport, experiment_key=experiment_key).get("policy_comparison", []),
                },
                "decision_strategy": selected_policy,
                "adjusted_score": round(adjusted_score, 3),
            }
        )
        scored.append(recommendation)

    scored.sort(
        key=lambda item: (
            float(item.get("adjusted_score") or 0.0),
            float(item.get("edge") or 0.0),
            float(item.get("confidence") or 0.0),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    if limit is not None:
        return scored[: max(0, int(limit))]
    return scored


def build_recommendation_output(
    candidate: Mapping[str, Any],
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    policy: str | None = None,
    experiment_key: str | None = None,
) -> dict[str, Any]:
    return rank_recommendations(
        [candidate],
        sport=sport,
        ledger_path=ledger_path,
        evaluation_records=evaluation_records,
        policy=policy,
        experiment_key=experiment_key,
        limit=1,
    )[0]


__all__ = [
    "MODEL_VERSION",
    "SCHEMA_VERSION",
    "calculate_edge",
    "compare_policies",
    "build_policy_optimization_summary",
    "filter_candidates",
    "rank_recommendations",
    "select_policy",
    "build_recommendation_output",
]