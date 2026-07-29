"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Scores candidates and records recommendation snapshots.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import logging
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.intelligence_evaluation import _iter_record_payloads
from syndicate.features.shared.intelligence_evaluation import build_feature_coverage_profile
from syndicate.features.shared.intelligence_evaluation import build_reliability_profile
from syndicate.features.shared.odds_lifecycle import build_market_features
from syndicate.features.shared.source_roots import repo_root_from


SCHEMA_VERSION = 1
MODEL_VERSION = "recommendation-engine-v1"
DEFAULT_EVALUATION_LEDGER = repo_root_from(__file__) / "reports" / "intelligence" / "evaluation_ledger.jsonl"
DEFAULT_PERFORMANCE_SUMMARY = repo_root_from(__file__) / "reports" / "intelligence" / "performance_summary.json"
logger = logging.getLogger(__name__)


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


def _parse_iso_timestamp_to_epoch(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _candidate_age_seconds(candidate: Mapping[str, Any], *, now: float | None = None) -> float | None:
    now = now if now is not None else time.time()
    # last_updated is the freshest known signal on a candidate -- it's what
    # #117 traced the "21H AGO" board symptom to (intelligence.html's
    # formatRelativeTime reads this exact field), and it gets overwritten by
    # odds-history enrichment (pipeline/intelligence_state.py) when that
    # runs, so it reflects real market-data freshness, not just when the
    # candidate object was first built. updated_epoch (stamped at candidate
    # build time, home.py's _append_game_bet_candidate) is the fallback for
    # candidates enrichment never touched.
    epoch = _parse_iso_timestamp_to_epoch(candidate.get("last_updated"))
    if epoch is None:
        updated_epoch = candidate.get("updated_epoch")
        if isinstance(updated_epoch, (int, float)) and updated_epoch > 0:
            epoch = float(updated_epoch)
    if epoch is None:
        return None
    return max(0.0, now - epoch)


def _candidate_freshness_ceiling_seconds(sport_slug: str, *, is_live: bool) -> int:
    # #117 follow-up (Layer 2 board redesign, Phase 2a). Derived from the
    # pipeline's own already-tuned refresh cadence rather than an invented
    # constant, per explicit user direction: pregame candidates get 3x each
    # sport's configured pregame-sweep interval (_pregame_sweep_interval_seconds,
    # live_refresh_loop.py -- 2h default, 8h soccer, per #82's design) as
    # slack against normal scheduling jitter while still catching genuine
    # multi-cycle staleness (the doubleheader candidate #117 found was stale
    # by ~21.7h against a 2h cadence -- multiple ceilings past). Live
    # candidates use the slate-wide live-tick interval
    # (_live_refresh_loop_interval_seconds, 60s default) x 30 (30 minutes) --
    # no per-sport live cadence config exists to derive from the same way,
    # so this is a deliberately conservative starting ceiling (loose enough
    # to tolerate a quiet inning/quarter with no real price movement, tight
    # enough to catch the actual failure mode: a live-flagged candidate
    # whose data genuinely stopped updating). Revisit once live-tick
    # telemetry across sports gives a real basis to tighten this per sport,
    # the same way the pregame side already has one.
    from syndicate.features.shared.live_refresh_loop import _live_refresh_loop_interval_seconds
    from syndicate.features.shared.live_refresh_loop import _pregame_sweep_interval_seconds

    if is_live:
        return _live_refresh_loop_interval_seconds() * 30
    return _pregame_sweep_interval_seconds(sport_slug) * 3


def _line_odds_movement_summary(market_features: Mapping[str, Any] | None) -> dict[str, Any] | None:
    # Board display needs the line move (e.g. 3.5 -> 4.5) and the odds/price
    # move (e.g. -110 -> -120) reported as two separate, explicit
    # direction+amount pairs -- market_features already tracks both
    # dimensions (opening/latest line, opening/latest price) but only ever
    # computed a delta for the line side, and nothing surfaced either one to
    # the board in a stable, sport-agnostic shape. Kept as its own small
    # summary rather than exposing all of market_features to the frontend,
    # since that dict's schema is meant for internal scoring, not display.
    if not isinstance(market_features, Mapping):
        return None
    return {
        "opening_line": market_features.get("opening_line"),
        "latest_line": market_features.get("latest_line"),
        "line_delta": market_features.get("movement_delta"),
        "line_direction": market_features.get("movement_direction") or "flat",
        "opening_price": market_features.get("opening_price"),
        "latest_price": market_features.get("latest_price"),
        "price_delta": market_features.get("price_delta"),
        "price_direction": market_features.get("price_direction") or "flat",
    }


def _coerce_probability(value: Any) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    if 0.0 <= numeric <= 1.0:
        return numeric
    if 1.0 < numeric <= 100.0:
        return numeric / 100.0
    return None


def _probability_from_simulation_payload(payload: Mapping[str, Any]) -> float | None:
    for source_key in ("simulation", "sim", "sim_results", "sim_summary", "market_context"):
        source = _copy_mapping(payload.get(source_key))
        if not source:
            continue
        for key in (
            "model_probability",
            "win_probability",
            "hit_rate",
            "win_rate",
            "success_rate",
            "probability",
        ):
            probability = _coerce_probability(source.get(key))
            if probability is not None:
                return probability
        distributions = source.get("probability_distributions") or source.get("distribution")
        if isinstance(distributions, Mapping):
            for key in ("win", "over", "success", "hit"):
                probability = _coerce_probability(distributions.get(key))
                if probability is not None:
                    return probability
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


def _current_odds_value(candidate: Mapping[str, Any]) -> Any | None:
    live_markers = (
        candidate.get("is_live"),
        candidate.get("live_refresh"),
        candidate.get("live"),
        str(candidate.get("refresh_mode") or "").strip().lower() == "live",
    )
    has_live_marker = any(bool(marker) for marker in live_markers)
    for key in ("current_odds", "live_odds", "odds_current", "current_price", "current_market_odds"):
        value = candidate.get(key)
        if value not in {None, ""}:
            return value
    market_context = _copy_mapping(candidate.get("market_context"))
    for key in ("current_odds", "live_odds", "odds_current", "current_price", "current_market_odds"):
        value = market_context.get(key)
        if value not in {None, ""}:
            return value
    if has_live_marker:
        return candidate.get("odds")
    return None


def _repriced_probabilities(candidate: Mapping[str, Any], *, model_probability: float | None = None) -> dict[str, Any]:
    current_odds = _current_odds_value(candidate)
    if current_odds is None:
        return {
            "odds": None,
            "market_probability": None,
            "implied_probability": None,
            "edge": None,
            "edge_pct": None,
            "expected_value": None,
        }
    implied_probability = _parse_american_odds(current_odds)
    if implied_probability is None:
        return {
            "odds": current_odds,
            "market_probability": None,
            "implied_probability": None,
            "edge": None,
            "edge_pct": None,
            "expected_value": None,
        }

    resolved_model_probability = _coerce_probability(model_probability)
    if resolved_model_probability is None:
        resolved_model_probability = _coerce_probability(candidate.get("model_probability"))
    if resolved_model_probability is None:
        resolved_model_probability = _coerce_probability(candidate.get("fair_probability"))
    if resolved_model_probability is None:
        resolved_model_probability = _coerce_probability(candidate.get("confidence"))

    expected_value = _coerce_float(candidate.get("expected_value"))
    edge = _coerce_float(candidate.get("edge"))
    edge_pct = _coerce_float(candidate.get("edge_pct"))
    if implied_probability is not None and resolved_model_probability is not None:
        edge = round(resolved_model_probability - implied_probability, 4)
        edge_pct = round(edge * 100.0, 2)
        if implied_probability > 0.0:
            expected_value = round((resolved_model_probability / implied_probability) - 1.0, 4)
    elif edge is None:
        edge = _coerce_float(candidate.get("edge"))

    return {
        "odds": current_odds,
        "market_probability": implied_probability,
        "implied_probability": implied_probability,
        "edge": edge,
        "edge_pct": edge_pct,
        "expected_value": expected_value,
    }


def _tracking_snapshot(
    candidate: Mapping[str, Any],
    *,
    live_pricing: Mapping[str, Any] | None = None,
    model_probability: float | None = None,
) -> dict[str, Any]:
    open_odds = candidate.get("odds")
    open_ev = _coerce_float(candidate.get("ev_open"))
    if open_ev is None:
        ev_pct = _coerce_float(candidate.get("ev_pct"))
        if ev_pct is not None:
            open_ev = round(float(ev_pct) / 100.0, 4)
    if open_ev is None:
        open_implied_for_ev = _parse_american_odds(open_odds)
        resolved_model_probability = _coerce_probability(model_probability)
        if resolved_model_probability is None:
            resolved_model_probability = _coerce_probability(candidate.get("model_probability"))
        if resolved_model_probability is None:
            resolved_model_probability = _coerce_probability(candidate.get("fair_probability"))
        if resolved_model_probability is None:
            resolved_model_probability = _coerce_probability(candidate.get("confidence"))
        if open_implied_for_ev is not None and resolved_model_probability is not None and open_implied_for_ev > 0.0:
            open_ev = round((float(resolved_model_probability) / float(open_implied_for_ev)) - 1.0, 4)
    if open_ev is None:
        open_ev = _coerce_float(candidate.get("expected_value"))
    if open_ev is None:
        open_ev = _coerce_float(candidate.get("ev"))

    current_odds = None
    current_ev = None
    if isinstance(live_pricing, Mapping):
        current_odds = live_pricing.get("odds")
        current_ev = _coerce_float(live_pricing.get("expected_value"))

    if current_odds is None:
        current_odds = _current_odds_value(candidate)
    if current_odds is None:
        current_odds = open_odds

    if current_ev is None:
        current_ev = open_ev

    open_implied = _parse_american_odds(open_odds)
    current_implied = _parse_american_odds(current_odds)
    line_movement_impact = None
    if open_implied is not None and current_implied is not None:
        line_movement_impact = round(float(open_implied) - float(current_implied), 4)

    ev_delta = None
    if open_ev is not None and current_ev is not None:
        ev_delta = round(float(current_ev) - float(open_ev), 4)

    return {
        "odds_open": open_odds,
        "odds_current": current_odds,
        "ev_open": round(float(open_ev), 4) if open_ev is not None else None,
        "ev_current": round(float(current_ev), 4) if current_ev is not None else None,
        "ev_delta": ev_delta,
        "line_movement_impact": line_movement_impact,
    }


def _market_dynamics_score(candidate: Mapping[str, Any], market_features: Mapping[str, Any] | None) -> dict[str, Any]:
    features = _copy_mapping(market_features)
    if not features:
        return {
            "movement_signal": None,
            "clv_signal": None,
            "volatility": 0.0,
            "is_live": bool(candidate.get("is_live")),
            "market_bonus": 0.0,
        }

    movement_signal = _coerce_float(features.get("movement_signal"))
    clv_signal = _coerce_float(features.get("clv_signal"))
    volatility = _coerce_float(features.get("volatility")) or 0.0
    is_live = bool(candidate.get("is_live") or features.get("is_live"))

    sim_weight = 0.72 if is_live else 1.0
    movement_weight = 1.28 if is_live else 0.82
    clv_weight = 1.10 if is_live else 1.0
    volatility_weight = 0.45 if is_live else 0.18

    movement_component = (movement_signal or 0.0) * 60.0 * movement_weight
    clv_component = (clv_signal or 0.0) * 45.0 * clv_weight
    volatility_component = min(6.0, volatility * volatility_weight)
    market_bonus = movement_component + clv_component + volatility_component

    return {
        "movement_signal": movement_signal,
        "clv_signal": clv_signal,
        "volatility": volatility,
        "is_live": is_live,
        "sim_weight": sim_weight,
        "movement_weight": movement_weight,
        "clv_weight": clv_weight,
        "volatility_weight": volatility_weight,
        "market_bonus": market_bonus,
    }


def _load_records_from_ledger(ledger_path: Path | str | None = None) -> list[dict[str, Any]]:
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_EVALUATION_LEDGER
    return _iter_record_payloads(ledger_path=path)


def _load_performance_summary(ledger_path: Path | str | None = None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if ledger_path is not None:
        ledger_file = Path(ledger_path)
        candidates.extend(
            [
                ledger_file.parent.parent / "performance_summary.json",
                ledger_file.parent / "performance_summary.json",
            ]
        )
    candidates.extend(
        [
            DEFAULT_PERFORMANCE_SUMMARY,
            repo_root_from(__file__) / "reports" / "performance_summary.json",
            repo_root_from(__file__) / "data" / "performance_summary.json",
        ]
    )
    seen: set[str] = set()
    for path in candidates:
        normalized = str(path.resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _summary_context_for_candidate(summary: Mapping[str, Any] | None, *, sport: str | None, market: str | None) -> dict[str, Any] | None:
    if not isinstance(summary, Mapping):
        return None

    sport_key = str(sport or "").strip().lower()
    market_key = str(market or "").strip().lower()
    if not sport_key or not market_key:
        return None

    sport_market_summary = summary.get("by_sport_market")
    if isinstance(sport_market_summary, Mapping):
        sport_bucket = sport_market_summary.get(sport_key)
        if isinstance(sport_bucket, Mapping):
            market_bucket = sport_bucket.get(market_key)
            if isinstance(market_bucket, Mapping):
                roi_segment = _coerce_float(market_bucket.get("roi_segment") or market_bucket.get("roi"))
                sample_size = _coerce_float(market_bucket.get("sample_size") or market_bucket.get("settled_count") or market_bucket.get("total_bets"))
                if roi_segment is not None or sample_size is not None:
                    return {
                        "roi_segment": round(roi_segment, 4) if roi_segment is not None else None,
                        "sample_size": int(sample_size) if sample_size is not None and sample_size > 0 else None,
                    }

    segments = summary.get("segments")
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            segment_sport = str(segment.get("sport") or segment.get("sport_slug") or "").strip().lower()
            segment_market = str(segment.get("market") or segment.get("market_type") or segment.get("market_key") or "").strip().lower()
            if segment_sport != sport_key or segment_market != market_key:
                continue
            roi_segment = _coerce_float(segment.get("roi_segment") or segment.get("roi") or segment.get("roi_pct"))
            sample_size = _coerce_float(segment.get("sample_size") or segment.get("settled_count") or segment.get("total_bets") or segment.get("count"))
            return {
                "roi_segment": round(roi_segment, 4) if roi_segment is not None else None,
                "sample_size": int(sample_size) if sample_size is not None and sample_size > 0 else None,
            }

    return None


def _bounded_multiplier(value: float | None, *, lower: float = 0.9, upper: float = 1.1) -> float:
    if value is None:
        return 1.0
    return max(lower, min(upper, round(float(value), 4)))


def _roi_multiplier(roi: float | None, *, scale: float, cap: float) -> float:
    if roi is None:
        return 1.0
    adjustment = max(-cap, min(cap, float(roi) * scale))
    return 1.0 + adjustment


def _bucket_range(label: str) -> tuple[float, float] | None:
    text = str(label or "").strip()
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    try:
        return float(left), float(right)
    except Exception:
        return None


def _confidence_bucket_row(summary: Mapping[str, Any] | None, probability: float | None) -> Mapping[str, Any] | None:
    if not isinstance(summary, Mapping) or probability is None:
        return None
    buckets = summary.get("by_probability_bucket")
    if not isinstance(buckets, list) or not buckets:
        return None
    nearest: tuple[float, dict[str, Any]] | None = None
    for bucket in buckets:
        if not isinstance(bucket, Mapping):
            continue
        bucket_row = dict(bucket)
        bounds = _bucket_range(str(bucket_row.get("bucket") or bucket_row.get("label") or ""))
        if bounds is None:
            continue
        start, end = bounds
        center = (start + end) / 2.0
        distance = abs(probability - center)
        if nearest is None or distance < nearest[0]:
            nearest = (distance, bucket_row)
        if start <= probability <= end:
            return bucket_row
    return nearest[1] if nearest is not None else None


def _performance_multiplier_for_candidate(
    summary: Mapping[str, Any] | None,
    *,
    sport: str | None,
    market: str | None,
    probability: float | None,
) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        return {"performance_multiplier": 1.0, "performance_context": None}

    sport_key = str(sport or "").strip().lower()
    market_key = str(market or "").strip().lower()
    sport_block = _copy_mapping((summary.get("by_sport") or {}).get(sport_key)) if sport_key else {}
    market_block = _copy_mapping((summary.get("by_market") or {}).get(market_key)) if market_key else {}

    sport_roi = _coerce_float(sport_block.get("roi")) if sport_block else None
    market_roi = _coerce_float(market_block.get("roi")) if market_block else None

    bucket_row = _confidence_bucket_row(summary, probability)
    bucket_label = str(bucket_row.get("bucket") or bucket_row.get("label") or "") if isinstance(bucket_row, Mapping) else ""
    bucket_predicted = _coerce_probability(bucket_row.get("predicted_probability")) if isinstance(bucket_row, Mapping) else None
    bucket_actual = _coerce_probability(bucket_row.get("actual_win_rate")) if isinstance(bucket_row, Mapping) else None
    bucket_calibration = (bucket_actual - bucket_predicted) if (bucket_actual is not None and bucket_predicted is not None) else None

    sport_multiplier = _roi_multiplier(sport_roi, scale=0.25, cap=0.035)
    market_multiplier = _roi_multiplier(market_roi, scale=0.20, cap=0.025)
    calibration_multiplier = 1.0 if bucket_calibration is None else 1.0 + max(-0.03, min(0.03, float(bucket_calibration) * 0.55))
    multiplier = _bounded_multiplier(sport_multiplier * market_multiplier * calibration_multiplier, lower=0.9, upper=1.1)

    return {
        "performance_multiplier": multiplier,
        "performance_context": {
            "sport_roi": round(sport_roi, 4) if sport_roi is not None else None,
            "market_roi": round(market_roi, 4) if market_roi is not None else None,
            "confidence_bucket": bucket_label or None,
            "confidence_bucket_predicted_probability": round(bucket_predicted, 4) if bucket_predicted is not None else None,
            "confidence_bucket_actual_win_rate": round(bucket_actual, 4) if bucket_actual is not None else None,
            "confidence_bucket_calibration": round(bucket_calibration, 4) if bucket_calibration is not None else None,
        },
    }


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

def _standardize_recommendation_fields(
    payload: Mapping[str, Any],
    *,
    edge: float | None = None,
    fair_probability: float | None = None,
    implied_probability: float | None = None,
) -> dict[str, Any]:
    standardized = dict(payload)

    expected_value = _coerce_float(standardized.get("expected_value"))
    if expected_value is None:
        expected_value = _coerce_float(standardized.get("ev"))
    if expected_value is None:
        ev_pct = _coerce_float(standardized.get("ev_pct"))
        if ev_pct is not None:
            expected_value = round(float(ev_pct) / 100.0, 4)

    edge_pct = _coerce_float(standardized.get("edge_pct"))
    if edge_pct is None:
        edge_pct = _coerce_float(standardized.get("adjusted_edge"))
    if edge_pct is None:
        edge_value = _coerce_float(standardized.get("edge"))
        if edge_value is not None:
            edge_pct = round(float(edge_value) * 100.0, 2)
    if edge_pct is None and edge is not None:
        edge_pct = round(float(edge) * 100.0, 2)

    model_probability = _coerce_probability(standardized.get("model_probability"))
    if model_probability is None:
        model_probability = _coerce_probability(standardized.get("model_prob"))
    if model_probability is None:
        model_probability = _probability_from_simulation_payload(standardized)
    if model_probability is None:
        model_probability = fair_probability

    market_probability = _coerce_probability(standardized.get("market_probability"))
    if market_probability is None:
        market_probability = _coerce_probability(standardized.get("implied_probability"))
    if market_probability is None:
        market_probability = _coerce_probability(standardized.get("implied_prob"))
    if market_probability is None:
        market_probability = implied_probability

    standardized.update(
        {
            "expected_value": expected_value,
            "edge_pct": edge_pct,
            "model_probability": model_probability,
            "market_probability": market_probability,
        }
    )
    return standardized


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
    rejected: list[dict[str, Any]] = []
    # _market_profile rescans history_rows and recomputes build_reliability_profile
    # from scratch -- with dozens of candidates sharing a handful of distinct
    # markets, computing it fresh per-candidate instead of once per market was
    # confirmed in production as the dominant cost of a 48.5s ranking pass over
    # only 161 candidates. Same bug shape as the odds-history O(candidates x
    # markets) regression fixed in 29649d18, just in this sibling code path.
    market_profile_cache: dict[str, dict[str, Any]] = {}
    # build_market_features re-reads and re-parses the sport's whole
    # odds-history shard payload (thousands of entries) from disk on every
    # call with no caching of its own. Confirmed in production 2026-07-24:
    # this was the dominant cost of a 300s+ scoring pass over ~270 MLB
    # candidates -- the same shard gets read from scratch once (or twice,
    # with the 1-day lookback) per candidate instead of once per cycle.
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    freshness_check_started_at = time.time()
    for candidate in candidate_rows:
        # #117 follow-up (Layer 2 Phase 2a). A stale candidate must be
        # rejected before it's even scored, not just annotated after the
        # fact -- the live board symptom this closes (a "LIVE, 7th inning"
        # candidate with 21.7h-old odds attached) was a data-freshness
        # failure, not an edge-quality one, so it needs its own gate rather
        # than hoping a stale price also happens to fail the edge check.
        #
        # Only rejects when the SPORT'S OWN pipeline looks healthy
        # (sport_manifest_last_updated itself is within the same ceiling) --
        # if the whole manifest is old too, that's a pipeline-health problem
        # bigger than any one candidate, and this gate silently emptying the
        # board on top of that would hide the real issue rather than surface
        # it. sport_manifest_last_updated is already attached per-candidate
        # by pipeline/intelligence_state.py's _build_candidate_pool.
        candidate_sport_slug = str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower()
        candidate_is_live = bool(candidate.get("is_live"))
        # #124, per explicit user direction ("market still open should be
        # the SLA"): for LIVE candidates, whether the underlying market is
        # still open is the real freshness signal, not how many seconds
        # since last_updated. A confirmed-live game whose prop price simply
        # hasn't needed to move (a strikeouts line nobody's re-quoted in the
        # last hour) is not stale, it's just quiet -- but the time-based
        # ceiling below can't tell those apart and was rejecting both the
        # same way. "Is the market still open" already has a real, upstream
        # check: _apply_candidate_state_guard (intelligence.py) sets
        # state_invalid=True on a final game, a live claim frozen for >8h
        # with no update at all, or an inactive/DNP player, and every one of
        # those is dropped before a candidate ever reaches this function. A
        # live candidate that survives to here has already passed that
        # check, so the separate, much tighter (30-minute) time-based
        # ceiling was pure redundancy layered on top of a correct signal --
        # confirmed live: 123 of 144 total rejections in one cycle were
        # exactly this, discarding real, currently-open MLB prop markets the
        # moment real live data started flowing through the pipeline.
        # Pregame candidates have no equivalent "is the market still open"
        # state (the game hasn't started), so they keep the time-based gate.
        market_confirmed_open = candidate_is_live and not bool(candidate.get("state_invalid"))
        ceiling_seconds = 0 if market_confirmed_open else _candidate_freshness_ceiling_seconds(candidate_sport_slug, is_live=candidate_is_live)
        candidate_age = _candidate_age_seconds(candidate, now=freshness_check_started_at)
        if ceiling_seconds > 0 and candidate_age is not None and candidate_age > ceiling_seconds:
            manifest_age = _candidate_age_seconds(
                {"last_updated": candidate.get("sport_manifest_last_updated")}, now=freshness_check_started_at
            )
            pipeline_looks_healthy = manifest_age is None or manifest_age <= ceiling_seconds
            if pipeline_looks_healthy:
                rejected.append(
                    {
                        "sport": candidate_sport_slug,
                        "name": _selection(candidate),
                        "market": _market(candidate),
                        "is_live": candidate_is_live,
                        "age_seconds": round(candidate_age, 1),
                        "ceiling_seconds": ceiling_seconds,
                        "reason": "stale_beyond_sla",
                    }
                )
                continue
        market = _market(candidate)
        market_profile = market_profile_cache.get(market)
        if market_profile is None:
            market_profile = _market_profile(history_rows, sport=sport, market=market)
            market_profile_cache[market] = market_profile
        market_features = build_market_features(candidate, sport=sport, payload_cache=odds_payload_cache)
        live_pricing = _repriced_probabilities(candidate)
        edge_data = calculate_edge(candidate, implied_probability=live_pricing["implied_probability"])
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
            rejected.append(
                {
                    "sport": str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower(),
                    "name": _selection(candidate),
                    "market": market,
                    "edge": edge,
                    "threshold": round(threshold, 4),
                    "market_sample": market_sample,
                    "market_roi": market_roi,
                    "calibration_error": round(calibration_error, 4),
                    "reliability_multiplier": round(reliability_multiplier, 4),
                    "reason": "edge_below_threshold",
                }
            )
            continue
        enriched = dict(candidate)
        enriched.update(
            {
                "event_id": _event_id(candidate),
                # `market` here (from _market(), a few lines up) is a
                # lowercased grouping/lookup key (market profile cache,
                # calibration lookups, risk_flags text) -- NOT the
                # human-readable display value, and it is coarser than the
                # canonical per-market "market_key" set elsewhere in the
                # pipeline (e.g. a live game's "Live Total" display label
                # lowercases to "live total" here, not the canonical
                # "total") -- so it must never be written back as
                # "market_key" (tried, confirmed live 2026-07-28 that it
                # clobbers the real one). Confirmed live 2026-07-28: this
                # used to overwrite the candidate's own display "market"
                # ("HR") with this lowercased key ("hr"), corrupting it for
                # every candidate that passed through this filter -- preserve
                # the candidate's original display value instead.
                "market": candidate.get("market") or market,
                "selection": _selection(candidate),
                "fair_probability": fair_probability,
                "implied_probability": implied_probability,
                "edge": edge,
                "expected_value": live_pricing["expected_value"] if live_pricing["expected_value"] is not None else _coerce_float(candidate.get("expected_value")),
                "model_probability": _coerce_probability(candidate.get("model_probability")) or _probability_from_simulation_payload(candidate) or fair_probability,
                "market_probability": live_pricing["market_probability"] if live_pricing["market_probability"] is not None else implied_probability,
                "edge_pct": live_pricing["edge_pct"] if live_pricing["edge_pct"] is not None else (round(float(edge) * 100.0, 2) if edge is not None else None),
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
                "market_features": market_features,
                "line_odds_movement": _line_odds_movement_summary(market_features),
            }
        )
        filtered.append(_standardize_recommendation_fields(enriched, edge=edge, fair_probability=fair_probability, implied_probability=implied_probability))
    if logger.isEnabledFor(logging.INFO):
        before_rows = candidate_rows
        after_rows = filtered

        def _row_sport(row: dict[str, Any]) -> str:
            return str(row.get("sport_slug") or row.get("sport") or "").strip().lower() or "unknown"

        def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
            by_sport: dict[str, int] = {}
            for row in rows:
                sport_key = _row_sport(row)
                by_sport[sport_key] = by_sport.get(sport_key, 0) + 1
            return {"total": len(rows), "by_sport": by_sport}

        rejected_by_sport: dict[str, list[dict[str, Any]]] = {}
        for item in rejected:
            rejected_by_sport.setdefault(_row_sport(item), []).append(item)
        rejected_by_sport = {sport_key: items[:10] for sport_key, items in rejected_by_sport.items()}

        logger.info(
            json.dumps(
                {
                    "event": "recommendation_filter_stage",
                    "stage": "filter_candidates",
                    "before": _summary(before_rows),
                    "after": _summary(after_rows),
                    "rejected_reasons": {
                        reason: sum(1 for item in rejected if item.get("reason") == reason)
                        for reason in sorted({item.get("reason") for item in rejected if item.get("reason")})
                    },
                    "rejected_by_sport": rejected_by_sport,
                },
                sort_keys=True,
                default=str,
            )
        )
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
    performance_summary = _load_performance_summary(ledger_path=ledger_path)
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
    # Same per-market memoization as filter_candidates above -- avoids
    # recomputing build_reliability_profile from scratch for every candidate
    # that shares a market.
    market_profile_cache: dict[str, dict[str, Any]] = {}
    # Same odds-history payload memoization as filter_candidates above --
    # only relevant when a candidate reaches this loop without market_features
    # already attached (filter_candidates normally sets it on every row).
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    for candidate in filtered_candidates:
        market = str(candidate.get("market") or "market").strip().lower() or "market"
        market_profile = market_profile_cache.get(market)
        if market_profile is None:
            market_profile = _market_profile(history_rows, sport=sport, market=market)
            market_profile_cache[market] = market_profile
        market_features = _copy_mapping(candidate.get("market_features"))
        if not market_features:
            market_features = build_market_features(candidate, sport=sport, payload_cache=odds_payload_cache)
        fair_probability = float(candidate.get("fair_probability") or 0.5)
        model_probability = _coerce_probability(candidate.get("model_probability")) or _probability_from_simulation_payload(candidate) or fair_probability
        live_pricing = _repriced_probabilities(candidate, model_probability=model_probability)
        tracking_snapshot = _tracking_snapshot(candidate, live_pricing=live_pricing, model_probability=model_probability)
        edge = live_pricing["edge"] if live_pricing["edge"] is not None else candidate.get("edge")
        confidence = _coerce_probability(candidate.get("confidence")) or fair_probability
        base_score = _coerce_float(candidate.get("score")) or 0.0
        market_fit_score = _coerce_float(candidate.get("market_fit_score")) or 0.0
        market_strength = float(market_profile.get("reliability_multiplier") or 1.0)
        sport_strength = float(sport_profile.get("reliability_multiplier") or 1.0)
        market_dynamics = _market_dynamics_score(candidate, market_features)
        coverage_profile = build_feature_coverage_profile(candidate.get("feature_coverage") or candidate.get("artifact_features", {}).get("feature_coverage") if isinstance(candidate.get("artifact_features"), Mapping) else candidate.get("feature_coverage"))
        coverage_score = _coerce_float(coverage_profile.get("coverage_score")) if coverage_profile else None
        coverage_tier = str(coverage_profile.get("coverage_tier") or "") if coverage_profile else ""
        sim_weight = float(market_dynamics.get("sim_weight") or 1.0)
        movement_weight = float(market_dynamics.get("movement_weight") or 1.0)
        clv_weight = float(market_dynamics.get("clv_weight") or 1.0)
        market_bonus = float(market_dynamics.get("market_bonus") or 0.0)
        edge_bonus = float(edge or 0.0) * 100.0
        calibration_error = float(market_profile.get("calibration_error") or sport_profile.get("calibration_error") or 0.0)
        roi = _coerce_float(market_profile.get("metrics", {}).get("roi")) or 0.0
        core_adjusted_score = (
            base_score * sport_strength * market_strength * sim_weight * (0.85 + policy_spec.confidence_weight * 0.30)
            + market_fit_score * (0.20 + policy_spec.market_fit_weight * 0.60)
            + edge_bonus * (0.50 + policy_spec.edge_weight)
            + confidence * 10.0 * (0.75 + policy_spec.confidence_weight)
            + roi * 20.0 * (0.70 + policy_spec.roi_weight)
            - calibration_error * 12.0 * (0.65 + policy_spec.calibration_weight)
            + market_bonus * (0.70 + policy_spec.edge_weight)
            + (market_dynamics.get("movement_signal") or 0.0) * 24.0 * movement_weight
            + (market_dynamics.get("clv_signal") or 0.0) * 20.0 * clv_weight
        )
        performance_profile = _performance_multiplier_for_candidate(
            performance_summary,
            sport=str(candidate.get("sport") or candidate.get("sport_slug") or sport or "").strip().lower() or None,
            market=market,
            probability=model_probability,
        )
        performance_multiplier = float(performance_profile.get("performance_multiplier") or 1.0)
        adjusted_score = core_adjusted_score * performance_multiplier
        if coverage_score is not None:
            adjusted_score *= 0.92 + (coverage_score * 0.08)
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
        historical_context = _summary_context_for_candidate(
            performance_summary,
            sport=str(candidate.get("sport") or candidate.get("sport_slug") or sport or "").strip().lower() or None,
            market=market,
        )
        market_probability = _coerce_probability(candidate.get("market_probability"))
        if market_probability is None:
            market_probability = _coerce_probability(candidate.get("implied_probability"))
        implied_probability = _coerce_probability(candidate.get("implied_probability"))
        edge_pct = _coerce_float(candidate.get("edge_pct"))
        if edge_pct is None and edge is not None:
            edge_pct = round(float(edge) * 100.0, 2)
        expected_value = _coerce_float(candidate.get("expected_value"))
        reasoning_items: list[str] = []
        if reasoning:
            reasoning_items.append(reasoning)
        if model_probability is not None and market_probability is not None:
            if edge_pct is not None:
                reasoning_items.append(f"Model {model_probability:.3f} vs market {market_probability:.3f} ({edge_pct:+.2f} pts)")
            else:
                reasoning_items.append(f"Model {model_probability:.3f} vs market {market_probability:.3f}")
        if isinstance(historical_context, Mapping):
            if historical_context.get("roi_segment") is not None and historical_context.get("sample_size") is not None:
                reasoning_items.append(f"Historical ROI {historical_context['roi_segment']:+.3f} across {historical_context['sample_size']} settled bets")
            elif historical_context.get("sample_size") is not None:
                reasoning_items.append(f"Historical sample size {historical_context['sample_size']} settled bets")
        recommendation = dict(candidate)
        recommendation.update(
            {
                "schema_version": SCHEMA_VERSION,
                "recommendation_id": candidate.get("recommendation_id") or f"reco_{uuid.uuid4().hex[:12]}",
                "event_id": candidate.get("event_id") or _event_id(candidate),
                "market": market,
                "selection": candidate.get("selection") or _selection(candidate),
                "odds": tracking_snapshot["odds_current"] if tracking_snapshot["odds_current"] is not None else tracking_snapshot["odds_open"],
                "odds_open": tracking_snapshot["odds_open"],
                "odds_current": tracking_snapshot["odds_current"],
                "fair_probability": round(fair_probability, 4),
                "edge": round(float(edge or 0.0), 4),
                "confidence": round(max(0.05, min(0.99, confidence * sport_strength * market_strength)), 2),
                "expected_value": live_pricing["expected_value"] if live_pricing["expected_value"] is not None else expected_value,
                "ev_open": tracking_snapshot["ev_open"],
                "ev_current": tracking_snapshot["ev_current"],
                "ev_delta": tracking_snapshot["ev_delta"],
                "line_movement_impact": tracking_snapshot["line_movement_impact"],
                "edge_pct": edge_pct,
                "model_probability": round(model_probability, 4) if model_probability is not None else None,
                "market_probability": round((live_pricing["market_probability"] if live_pricing["market_probability"] is not None else market_probability), 4) if (live_pricing["market_probability"] is not None or market_probability is not None) else None,
                "model_version": str(candidate.get("model_version") or MODEL_VERSION),
                "reasoning_text": reasoning,
                "reasoning": reasoning_items,
                "risk_factors": risk_factors[:5],
                "confidence_drivers": confidence_drivers[:5],
                "historical_context": historical_context,
                "performance_context": performance_profile.get("performance_context"),
                "performance_multiplier": round(performance_multiplier, 4),
                "core_adjusted_score": round(core_adjusted_score, 3),
                "market_features": market_features,
                "line_odds_movement": _line_odds_movement_summary(market_features),
                "movement_signal": market_dynamics.get("movement_signal"),
                "clv_signal": market_dynamics.get("clv_signal"),
                "volatility": market_dynamics.get("volatility"),
                "market_bonus": round(market_bonus, 3),
                "historical_profile": {
                    "sport": sport_profile,
                    "market": market_profile,
                    "policy_comparison": build_policy_optimization_summary(history_rows, sport=sport, experiment_key=experiment_key).get("policy_comparison", []),
                },
                "decision_strategy": selected_policy,
                "adjusted_score": round(adjusted_score, 3),
                "coverage_score": coverage_score,
                "coverage_tier": coverage_tier or None,
                "coverage_warnings": list(coverage_profile.get("coverage_warnings") or []) if coverage_profile else [],
                "publication_status": coverage_profile.get("publication_status") if coverage_profile else None,
            }
        )
        scored.append(_standardize_recommendation_fields(recommendation, edge=edge, fair_probability=fair_probability, implied_probability=implied_probability))

    scored.sort(
        key=lambda item: (
            float(item.get("adjusted_score") or 0.0),
            float(item.get("coverage_score") or 0.0),
            float(item.get("expected_value") or 0.0),
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