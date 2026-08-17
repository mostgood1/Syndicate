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
import math
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
    # Phase 5 (2026-07-30): promotion_margin/min_sample_size used to default
    # to 0.015/8. Empirically demonstrated (synthetic script, not guessed)
    # that this was broken: 12 settled bets per policy, one policy winning
    # just 1 more bet than the other out of 12 (ordinary binomial noise for
    # a ~55% strategy), triggered an immediate promotion. Root cause:
    # promotion_margin was scaled for a 0-1 metric, but compare_policies()
    # compares it against promotion_score, a weighted sum that realistically
    # ranges roughly +/-20 to +80 -- the margin was negligible at that scale,
    # so min_sample_size=8 was the only real gate, and 8-12 settled bets is
    # nowhere near enough to distinguish skill from variance. Same class of
    # bug as #124 (a threshold copied from/scaled for the wrong context),
    # different subsystem. These new values are a principled-but-unbacktested
    # starting point -- there's no real settled promotion history to
    # calibrate against yet (Phase 1 only just made settlement possible) --
    # revisit once enough real promotion history exists.
    name: str
    edge_weight: float
    confidence_weight: float
    roi_weight: float
    calibration_weight: float
    market_fit_weight: float
    min_edge_bias: float = 0.0
    promotion_margin: float = 3.0
    min_sample_size: int = 50


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
        promotion_margin=4.0,
    ),
    "aggressive": DecisionPolicy(
        name="aggressive",
        edge_weight=0.45,
        confidence_weight=0.15,
        roi_weight=0.20,
        calibration_weight=0.10,
        market_fit_weight=0.10,
        min_edge_bias=-0.005,
        promotion_margin=2.0,
    ),
}
DEFAULT_POLICY = "balanced"


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


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
            "market_fair_probability": None,
            "edge_priced_against": None,
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
            "market_fair_probability": None,
            "edge_priced_against": None,
            "edge": None,
            "edge_pct": None,
            "expected_value": None,
        }

    # `confidence` is NOT a probability -- see `_model_probability_only`. It was
    # the last rung here too, so a scoring artefact could stand in for the model
    # on this path even after `_fair_probability` was fixed. `fair_probability`
    # is dropped for the same reason: it is the MARKET's de-vigged fair, copied
    # to the candidate's top level by `quote_enrichment`, so using it here made
    # `edge` a restatement of the hold rather than a model-vs-market gap.
    resolved_model_probability = _coerce_probability(model_probability)
    if resolved_model_probability is None:
        resolved_model_probability = _model_probability_only(candidate)

    # `#238` applied to this lane. The raw price still carries the book's
    # margin; comparing a model probability to it is wrong by roughly half the
    # hold, systematically and in one direction. Use the no-vig fair when the
    # market has one and say so, exactly as `quote_enrichment` does.
    market_fair, market_fair_method = _market_fair_probability(candidate)
    if market_fair is not None:
        priced_against_probability = market_fair
        priced_against = "modelled_no_vig_fair" if market_fair_method == "book_margin_model" else "no_vig_fair"
    else:
        priced_against_probability = implied_probability
        priced_against = "vigged_current_price"

    expected_value = _coerce_float(candidate.get("expected_value"))
    edge = _coerce_float(candidate.get("edge"))
    edge_pct = _coerce_float(candidate.get("edge_pct"))
    if priced_against_probability is not None and resolved_model_probability is not None:
        edge = round(resolved_model_probability - priced_against_probability, 4)
        edge_pct = round(edge * 100.0, 2)
        if priced_against_probability > 0.0:
            expected_value = round((resolved_model_probability / priced_against_probability) - 1.0, 4)
    elif edge is None:
        edge = _coerce_float(candidate.get("edge"))

    return {
        "odds": current_odds,
        "market_probability": implied_probability,
        "implied_probability": implied_probability,
        "market_fair_probability": market_fair,
        "edge_priced_against": priced_against,
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
        # Third site of the same substitution -- `confidence` and the market's
        # own `fair_probability` both dropped here for the reasons in
        # `_model_probability_only`. This one feeds the OPENING EV that CLV is
        # later measured from, so a fabricated number here would contaminate
        # the very measurement the audit's Lane B exists to produce.
        resolved_model_probability = _coerce_probability(model_probability)
        if resolved_model_probability is None:
            resolved_model_probability = _model_probability_only(candidate)
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


_LEDGER_LOAD_TRACE_MAX = 12
_LEDGER_LOAD_TRACE: dict[str, int] = {"count": 0}


def _load_records_from_ledger(ledger_path: Path | str | None = None) -> list[dict[str, Any]]:
    # THE JOIN THIS EXISTS FOR: does this load run DURING the excursion?
    #
    # Measured 2026-08-17 01:46:04-09Z on refresh-worker, three peak-SMAPS
    # samples: ONE anonymous VMA grew 1096.5 -> 1586.4 MB in 5.5s while regions
    # #2/#3/#4 sat unchanged at 268.7/201.8/194.0, and the process was oomKilled
    # 50s later. That located the growth to one mapping; it cannot say who
    # allocated it, because the kernel coalesces adjacent anon mappings (see
    # `_SMAPS_MAX_PER_PROCESS`'s comment) so a 1.5GB "region" may be tens of
    # thousands of pymalloc arenas rather than one buffer.
    #
    # This function is the candidate because production reports
    # `LEDGER_CHUNKS_ACCEPTED count=8 bytes=830,832,574 records=22,078
    # streamed=1`: the FILE is streamed, but the RESULT is a materialised list.
    # ~37.6KB of JSON per record, and parsed dicts typically run 2-5x their
    # source text, puts the resident cost at 1.7-4GB -- which brackets the
    # measured +2.1 to +2.9GB excursions. Mass dict allocation filling
    # contiguous arenas is ALSO what a single coalesced growing VMA looks like,
    # so the SMAPS reading and this hypothesis are the same observation rather
    # than competing ones.
    #
    # WHAT IS STILL MISSING, AND WHY THIS IS TIMING AND NOT COUNTING: the
    # magnitude fits and the shape fits, but nothing has shown this load running
    # inside the excursion window. Three attributions were already overturned on
    # this bug -- `board_contract_end` (a process-global field read as
    # thread-scoped), the artifact-pull path (refuted by a control arm), and
    # "the floors are irrelevant" (n=1, and the wrong 1). A coherent story is
    # exactly what each of those looked like. So this measures the ANON DELTA
    # ACROSS THE CALL, which is falsifiable: if the delta is small, this load is
    # not the allocator no matter how well the arithmetic fits.
    #
    # Cost: two cgroup reads per load, against a load that parses ~830MB of
    # JSON. Not periodic -- `learnings.md`'s "worker periodic work is never
    # free" (#241) is about background timers, and this is per-call on a path
    # that is already the expensive one. Capped, and the cap ANNOUNCES itself:
    # a silent cap is how the peak-SMAPS trigger nearly shipped as an instrument
    # that looked installed and emitted nothing.
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_EVALUATION_LEDGER
    _n = _LEDGER_LOAD_TRACE["count"] + 1
    _LEDGER_LOAD_TRACE["count"] = _n
    _traced = _n <= _LEDGER_LOAD_TRACE_MAX
    _before = None
    _t0 = None
    if _traced:
        try:
            import time as _time

            from syndicate.features.shared.memory_observability import container_memory_payload

            _t0 = _time.monotonic()
            _p = container_memory_payload("ledger_load_before")
            _before = _p.get("memory_unreclaimable_mb")
            if _before is None:
                _before = _p.get("memory_anon_mb")
        except Exception:
            _before = None
    records = _iter_record_payloads(ledger_path=path)
    if _traced:
        try:
            import time as _time

            from syndicate.features.shared.memory_observability import container_memory_payload

            _p = container_memory_payload("ledger_load_after")
            _after = _p.get("memory_unreclaimable_mb")
            if _after is None:
                _after = _p.get("memory_anon_mb")
            _delta = (
                round(float(_after) - float(_before), 1)
                if isinstance(_after, (int, float)) and isinstance(_before, (int, float))
                else None
            )
            _elapsed = round(_time.monotonic() - _t0, 2) if _t0 is not None else None
            print(
                f"[recommendation_engine] LEDGER_LOAD n={_n} records={len(records)} "
                f"elapsed_s={_elapsed} anon_before_mb={_before} anon_after_mb={_after} "
                f"anon_delta_mb={_delta} path={path.name}",
                flush=True,
            )
        except Exception:  # pragma: no cover - an instrument must never break the load
            pass
    elif _n == _LEDGER_LOAD_TRACE_MAX + 1:
        try:
            print(
                f"[recommendation_engine] LEDGER_LOAD_TRACE_CAPPED max={_LEDGER_LOAD_TRACE_MAX} "
                "-- further loads run untraced",
                flush=True,
            )
        except Exception:  # pragma: no cover
            pass
    return records


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


def _market_fair_probability(candidate: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """The MARKET's no-vig fair probability, and how it was derived.

    Kept separate from the model's probability because they are different
    quantities that this module used to read out of the same key. `#238`'s
    de-vig writes `fair_probability` onto the quote, and `quote_enrichment`'s
    `_FLAT_QUOTE_FIELDS` copies it up to the candidate's TOP LEVEL under that
    same name -- so `candidate["fair_probability"]` on any quote-enriched
    candidate is the market's fair value, not a model output. Reading it as
    "the model's fair probability" (which `_fair_probability` did, first in its
    chain) makes the edge a pure line-shopping signal wearing a model's label.

    The method travels with the number, because `book_margin_model`'s own
    docstring is explicit that a modelled fair value must never be silently
    mixed with a measured two-sided one.

    READS THE NESTED QUOTE ONLY, never the flattened top-level
    `fair_probability`. That key is genuinely ambiguous: `quote_enrichment`
    flattens the MARKET's fair value into it, and `rank_recommendations` writes
    the MODEL's probability into the same key on its own output. Reading it
    here made a recommendation compare a model against itself -- caught by
    `test_rank_recommendations_reprices_live_current_odds`, which went to
    `expected_value 0.0` because `0.6 / 0.6 - 1 == 0`. Nothing is lost by
    ignoring it: `quote_enrichment` sets `row["quote"]` before it flattens, so
    the nested dict is present wherever the flat keys are.
    """
    quote = _copy_mapping(candidate.get("quote"))
    probability = _coerce_probability(quote.get("fair_probability"))
    if probability is None:
        return (None, None)
    method = str(quote.get("fair_method") or "").strip() or None
    return (probability, method)


def _model_probability_only(candidate: Mapping[str, Any]) -> float | None:
    """P(outcome) as a MODEL stated it, or None. No substitutes.

    `#428`/audit 2026-08-14 fix 4. The chain this replaces was
    `fair_probability -> model_probability -> confidence -> score/100 -> 0.5`,
    and every rung after the second was wrong in a different way:

    - `fair_probability` is the MARKET's de-vigged fair (see above), not a
      model. It sat FIRST, so on every quote-enriched candidate the "model"
      probability was the market's own number and the resulting edge measured
      only whether this book beat consensus.
    - `confidence` is a scoring artefact. `score_candidate` derives it from
      `source_strength` plus readiness/movement bonuses; it is a measure of how
      much we trust the INPUT, not of how often the bet wins. Consumed here it
      manufactured a large positive edge: 0.85 confidence against a +150 price
      reads as +45 points of edge, against a threshold of 0.0.
    - `score/100` is not a probability at all. `score_candidate` computes
      `edge x confidence - tier_penalty`, which is unbounded and routinely
      negative. Measured this session with the real function: a typical
      score of 4.05 yields fair_prob 0.0405 and an edge of -0.36; a negative
      score clamps to 0.01. So model-free candidates were not "treated as a
      coin flip" -- they were silently rejected by a meaningless negative
      edge, with no reason ever recorded.
    - `0.5` was UNREACHABLE in the real pipeline. Every call site of
      `filter_candidates` is fed `_score_candidates` output, and
      `score_candidate` always assigns `score` (intelligence.py, end of the
      function), so the `score/100` rung always fired first. The audit's
      headline claim that a 0.5 coin-flip default clears a 0.0 threshold does
      not survive contact with the pipeline; removing only the 0.5 would have
      been an inert fix.

    A candidate with no model probability now returns None and is EXCLUDED by
    name in `filter_candidates`, rather than being priced off a scoring
    artefact. `_probability_from_simulation_payload` stays in the chain because
    a sim payload IS a model output.
    """
    probability = _coerce_probability(candidate.get("model_probability"))
    if probability is not None:
        return probability
    return _probability_from_simulation_payload(candidate)


def _fair_probability(candidate: Mapping[str, Any]) -> float | None:
    """Back-compat alias. Returns None where it used to invent a number."""
    return _model_probability_only(candidate)


def calculate_edge(candidate: Mapping[str, Any], *, fair_probability: float | None = None, implied_probability: float | None = None) -> dict[str, Any]:
    """Model edge, priced against the no-vig fair when one exists.

    `#238`: comparing a model probability to a raw book price overstates or
    understates edge by roughly half the hold (measured median hold 6.25%, so
    ~3.1 points) -- the difference between clearing a threshold and being
    dropped. That was fixed in `prop_projections`, `nfl_game_projections`,
    `soccer_projections` and `quote_enrichment` and left live here.

    `quote_enrichment._model_edge_pct(model_prob, fair_prob)` is the repo's
    already-correct formula for this; this function now computes the same
    comparison. When no opposing side exists there is no fair value, so the
    vigged price is used and LABELLED rather than silently mixed in -- the same
    keep-but-label choice `quote_enrichment` makes at its `vigged_best_price`
    branch.
    """
    base_candidate = _copy_mapping(candidate)
    fair_probability_value = fair_probability if fair_probability is not None else _model_probability_only(base_candidate)

    market_fair, market_fair_method = _market_fair_probability(base_candidate)

    if implied_probability is None:
        implied_probability = _coerce_probability(base_candidate.get("implied_probability"))
    if implied_probability is None:
        market_context = _copy_mapping(base_candidate.get("market_context"))
        implied_probability = _coerce_probability(market_context.get("implied_probability"))
    if implied_probability is None:
        implied_probability = _parse_american_odds(base_candidate.get("odds"))

    # Price the model against the no-vig fair where one exists; fall back to the
    # vigged price only when it does not, and say which happened.
    if market_fair is not None:
        priced_against_probability = market_fair
        priced_against = "modelled_no_vig_fair" if market_fair_method == "book_margin_model" else "no_vig_fair"
    else:
        priced_against_probability = implied_probability
        priced_against = "vigged_current_price" if implied_probability is not None else None

    edge = None
    if fair_probability_value is not None and priced_against_probability is not None:
        edge = round(float(fair_probability_value) - float(priced_against_probability), 4)
    elif fair_probability_value is None and _coerce_float(base_candidate.get("edge")) is not None:
        edge = round(float(_coerce_float(base_candidate.get("edge")) or 0.0) / 100.0, 4)
    return {
        "fair_probability": round(float(fair_probability_value), 4) if fair_probability_value is not None else None,
        "implied_probability": round(float(implied_probability), 4) if implied_probability is not None else None,
        "market_fair_probability": round(float(market_fair), 4) if market_fair is not None else None,
        "edge_priced_against": priced_against,
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


def _policy_record_clv(record: Mapping[str, Any], source: Mapping[str, Any]) -> float | None:
    # Same math as intelligence_evaluation._price_clv, computed per-record
    # here so compare_policies can weight it the same way it already
    # weights edge/confidence/roi -- CLV is the fast-converging signal the
    # plan doc (P5/P6) says should lead promotion instead of trailing it.
    entry_price = _first_present(source.get("odds"), source.get("price"), record.get("odds"), record.get("price"))
    closing_price = _first_present(record.get("closing_price"), source.get("closing_price"))
    entry_implied = _parse_american_odds(entry_price)
    closing_implied = _parse_american_odds(closing_price)
    if entry_implied is None or closing_implied is None:
        return None
    return closing_implied - entry_implied


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
    clv_price = _policy_record_clv(record, source)
    return {
        "edge": edge,
        "confidence": max(0.0, min(1.0, confidence)),
        "calibration_error": max(0.0, min(1.0, calibration_error)),
        "market_fit": max(0.0, market_fit),
        "roi": roi,
        "clv_price": clv_price if clv_price is not None else 0.0,
        "has_clv": 1.0 if clv_price is not None else 0.0,
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
                    "average_clv_price": 0.0,
                    "clv_sample_size": 0,
                    "promotion_score": 0.0,
                    "win_rate_standard_error": None,
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
        weighted_clv_total = 0.0
        weighted_clv_weight_total = 0.0
        weight_total = 0.0
        clv_sample_size = 0
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
            # CLV is only meaningful over records that actually captured a
            # closing price -- averaging in a 0.0 for every record missing
            # one (like the other features above do) would dilute the
            # signal toward zero as coverage grows, exactly backwards from
            # what "CLV should lead promotion" is supposed to buy.
            if features.get("has_clv"):
                weighted_clv_total += float(features.get("clv_price") or 0.0) * weight
                weighted_clv_weight_total += weight
                clv_sample_size += 1
            weight_total += weight
        weighted_roi = weighted_return_total / weight_total if weight_total else 0.0
        weighted_win_rate = weighted_win_total / weight_total if weight_total else 0.0
        average_alignment = weighted_alignment_total / weight_total if weight_total else 0.0
        average_edge = weighted_edge_total / weight_total if weight_total else 0.0
        average_confidence = weighted_confidence_total / weight_total if weight_total else 0.0
        average_calibration_error = weighted_calibration_total / weight_total if weight_total else 0.0
        average_clv_price = (weighted_clv_total / weighted_clv_weight_total) if weighted_clv_weight_total else 0.0
        # promotion_score is deliberately built ONLY from realized outcomes
        # (roi, win rate, CLV, calibration error) -- average_edge/
        # average_confidence/average_alignment describe what the policy
        # WOULD pick, not evidence it performed well, and mixing them in
        # let a policy get promoted for being confident rather than
        # profitable (plan doc finding, 2026-08-03). They stay on the row
        # below for visibility only. CLV is weighted at 200x (vs. ROI's
        # 100x) because it is the fast-converging signal (plan doc P5) --
        # it should be able to move promotion_score meaningfully even
        # while win/loss sample sizes are still too thin to trust alone.
        promotion_score = (
            weighted_roi * 100.0
            + weighted_win_rate * 40.0
            + average_clv_price * 200.0
            - average_calibration_error * 20.0
        )
        # Binomial standard error of weighted_win_rate, treating settled_count
        # as the effective sample size -- an approximation (the alignment
        # weighting above means observations aren't literally iid-equal-
        # weight), but good enough to stop a promotion_score gap that's
        # really just noise at a handful of settled bets (DecisionPolicy's
        # own comment documents getting burned by exactly this at n=12).
        sample_size = len(settled_rows)
        win_rate_standard_error = math.sqrt(max(0.0, weighted_win_rate * (1.0 - weighted_win_rate)) / sample_size) if sample_size else None
        comparisons.append(
            {
                "policy": policy.name,
                "sample_size": sample_size,
                "settled_count": sample_size,
                "weighted_roi": round(weighted_roi, 4),
                "weighted_win_rate": round(weighted_win_rate, 4),
                "average_alignment": round(average_alignment, 4),
                "average_edge": round(average_edge, 4),
                "average_confidence": round(average_confidence, 4),
                "average_calibration_error": round(average_calibration_error, 4),
                "average_clv_price": round(average_clv_price, 4),
                "clv_sample_size": clv_sample_size,
                "promotion_score": round(promotion_score, 4),
                "win_rate_standard_error": round(win_rate_standard_error, 4) if win_rate_standard_error is not None else None,
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
    exploration_rate: float = 0.10,
) -> dict[str, Any]:
    """Picks the policy for this experiment_key: promote a challenger with
    a real, variance-aware edge; otherwise, on a deterministic fraction of
    experiment_keys (``exploration_rate``), explore a challenger anyway so
    it can accrue the settled samples needed to ever prove itself; else
    fall back to the incumbent (``DEFAULT_POLICY``).

    Before this, a challenger tied with (or losing to) the incumbent NEVER
    received traffic: `leader_policy == DEFAULT_POLICY` short-circuited to
    the incumbent immediately, and with no settled history at all every
    policy scores promotion_score=0.0 -- a permanent tie the incumbent won
    by construction (plan doc finding, 2026-08-03). The exploration slice
    below is unconditional on current standings specifically to break that
    deadlock.
    """
    comparison = compare_policies(records, sport=sport, policies=policies)
    incumbent = next((item for item in comparison if item.get("policy") == DEFAULT_POLICY), {"policy": DEFAULT_POLICY})
    ranked_challengers = [item for item in comparison if item.get("policy") != DEFAULT_POLICY]
    leader = ranked_challengers[0] if ranked_challengers else None
    selected_policy = DEFAULT_POLICY
    promoted = False
    explored = False

    if leader is not None:
        lead_score = float(leader.get("promotion_score") or 0.0)
        incumbent_score = float(incumbent.get("promotion_score") or 0.0)
        lead_delta = lead_score - incumbent_score
        leader_policy = str(leader.get("policy") or DEFAULT_POLICY)
        # Variance-aware margin: the fixed promotion_margin alone treats a
        # 1-bet swing at n=12 the same as a real edge at n=500 (the exact
        # failure DecisionPolicy's own comment documents). Scale a required
        # margin off the combined standard error of the two win rates, on
        # the same *40 scale the win-rate term itself uses inside
        # promotion_score, and take whichever requirement is stricter.
        incumbent_se = float(incumbent.get("win_rate_standard_error") or 0.0)
        leader_se = float(leader.get("win_rate_standard_error") or 0.0)
        variance_margin = math.sqrt(incumbent_se ** 2 + leader_se ** 2) * 40.0 * 2.0
        required_margin = max(float(leader.get("promotion_margin") or POLICY_REGISTRY[leader_policy].promotion_margin), variance_margin)
        min_sample_size = int(leader.get("min_sample_size") or POLICY_REGISTRY[DEFAULT_POLICY].min_sample_size)
        if int(leader.get("sample_size") or 0) >= min_sample_size and lead_delta >= required_margin:
            selected_policy = leader_policy
            promoted = True

    if not promoted and experiment_key and ranked_challengers:
        exploration_bucket = _policy_bucket(experiment_key)
        if exploration_bucket < int(round(max(0.0, min(1.0, exploration_rate)) * 100)):
            # Deterministic per-experiment_key pick among challengers (not
            # always the current "leader") so a losing/untested challenger
            # still gets a turn -- otherwise this exploration slice would
            # just keep re-confirming whichever policy already looks best.
            challenger_index = int(hashlib.sha1(f"{experiment_key}|policy_explore".encode("utf-8")).hexdigest(), 16) % len(ranked_challengers)
            selected_policy = str(ranked_challengers[challenger_index].get("policy") or DEFAULT_POLICY)
            explored = True

    return {
        "selected_policy": selected_policy,
        "incumbent_policy": DEFAULT_POLICY,
        "leader_policy": leader.get("policy") if leader else DEFAULT_POLICY,
        "promoted": promoted,
        "explored": explored,
        "exploration_rate": exploration_rate,
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
    rejected_sink: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    # rejected_sink (2026-08-04, learning-loop Stage 2's deferred other
    # half): this function already builds a real `rejected` list with a
    # reason per entry, every call -- it was just never returned. Backward
    # compatible by construction: existing callers pass nothing, get
    # nothing extra, identical behavior. A caller that wants the rejects
    # (shadow_candidate_ledger.py) passes a list and this appends the FULL
    # candidate (not the lean summary `rejected` below carries) tagged
    # with `_shadow_rejection_reason`, so the sink has enough fields to
    # identify and later grade what was turned away.
    candidate_rows = [_copy_mapping(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    # LOAD ONCE, and do not re-copy what we already own.
    #
    # This was `[dict(record) for record in (evaluation_records or
    # _load_records_from_ledger(ledger_path))]` -- a full ledger load followed
    # by a SECOND full copy. Measured in production 2026-08-16:
    # `LEDGER_CHUNKS_ACCEPTED count=8 bytes=833550415` per load, so the copy
    # alone is the same order as the load.
    #
    # `dict(record)` is a DEFENSIVE copy and it is only meaningful when the
    # caller handed us their records. Records we load ourselves come straight
    # out of `json.loads` on this call's own read -- nothing else references
    # them and there is no cache behind them -- so copying them protects
    # nobody. Truthiness is preserved exactly: an EMPTY `evaluation_records`
    # still falls through to the ledger, as before.
    if evaluation_records:
        history_rows = [dict(record) for record in evaluation_records if isinstance(record, Mapping)]
    else:
        history_rows = [record for record in _load_records_from_ledger(ledger_path) if isinstance(record, Mapping)]
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
                if rejected_sink is not None:
                    rejected_sink.append({**candidate, "_shadow_rejection_reason": "stale_beyond_sla"})
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
        # Exclude by NAME, not by arithmetic. Before this, a candidate with no
        # model probability still got one -- `score/100`, an unbounded scoring
        # artefact -- which produced a large negative edge and dropped the row
        # at the threshold below with `reason: "edge_below_threshold"`. That
        # reason was false: the edge was never measured. A rejection that
        # misreports its own cause is worse than a missing one, because it
        # makes the shortlist's own diagnostics argue that the model
        # disagreed when no model ever ran.
        if fair_probability is None:
            rejected.append(
                {
                    "sport": candidate_sport_slug,
                    "name": _selection(candidate),
                    "market": market,
                    "is_live": candidate_is_live,
                    "reason": "no_model_probability",
                }
            )
            if rejected_sink is not None:
                rejected_sink.append({**candidate, "_shadow_rejection_reason": "no_model_probability"})
            continue
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
        # #137 follow-up, confirmed live: a steam move's signal IS the
        # market's own recent movement, not a model-vs-price gap -- its
        # model_probability is deliberately sourced from the market's own
        # implied_prob (intelligence.py's _steam_candidates_for_sport has no
        # independent model to compare against), so edge here is always
        # ~0 by construction and every steam candidate failed this gate
        # unconditionally. Confirmed in production: candidate_generation
        # showed real steam candidates surviving scoring with 0 filtered at
        # that stage, but the background-loop's board-publication path
        # (which, unlike run_intelligence_query, calls this filter with
        # apply_edge_filter=True) still served zero of them -- traced to
        # exactly this line before the fix.
        is_steam_move = str(candidate.get("candidate_type") or "").strip().lower() == "steam"
        if edge is not None and edge < threshold and not is_steam_move:
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
            if rejected_sink is not None:
                rejected_sink.append({**candidate, "edge": edge, "_shadow_rejection_reason": "edge_below_threshold"})
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
    # ONE line, unconditional, via print -- `logger.info` does not reach
    # Render's log collector (CLAUDE.md states this outright), so the
    # `rejected_reasons` block below is invisible in production, which is where
    # the `no_model_probability` exclusion has to be measured before it can be
    # trusted. Bounded on purpose: a summary per CALL, never per candidate.
    #
    # UNCONDITIONAL, and that word is load-bearing. This was written as
    # `if rejected:` and it cost a measurement the same session: after the
    # A1/A2 deploy the line did not appear, and "rejected nothing" was
    # indistinguishable from "the cycle never ran" -- so the deploy sat
    # unverifiable until an unrelated timestamp settled it. A zero has to be
    # PRINTABLE for a zero to mean anything, which is the same lesson `#373`,
    # `#381`, `#397` and `#400` each learned on a counter rather than a log
    # line. `rejected={}` is the single most informative thing this line can
    # say, because it is the only output that distinguishes a rule that ran and
    # passed everything from a rule that never executed.
    reason_counts: dict[str, int] = {}
    for item in rejected:
        reason_key = str(item.get("reason") or "unknown")
        reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
    print(
        f"[recommendation_engine] FILTER_CANDIDATES sport={sport or 'all'} "
        f"in={len(candidate_rows)} out={len(filtered)} "
        f"rejected={json.dumps(reason_counts, sort_keys=True)}",
        flush=True,
    )
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
    rejected_sink: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidate_rows = [_copy_mapping(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    # THREE FULL LEDGER LOADS IN ONE CALL, measured 2026-08-16. With
    # `evaluation_records` absent -- which is the worker's case -- this
    # function loaded the whole chunked ledger three separate times:
    # `select_policy` below, `filter_candidates` internally, and `history_rows`
    # further down; then copied it a fourth time. Production says each load is
    # `LEDGER_CHUNKS_ACCEPTED count=8 bytes=833550415` of accepted chunks.
    #
    # Load once here and thread the SAME list through all three, including
    # into `filter_candidates` via its `evaluation_records=` parameter, which
    # already existed for exactly this purpose and was being passed the empty
    # value. `_owned_records` records that we loaded them ourselves, so the
    # defensive `dict()` copy below can be skipped for records nothing else
    # references. Truthiness preserved: empty still means "load".
    _owned_records = False
    if not evaluation_records:
        evaluation_records = _load_records_from_ledger(ledger_path)
        _owned_records = True
    if experiment_key is None:
        experiment_key = _candidate_policy_key(candidate_rows, sport=sport)
    selected_policy = _normalize_policy_name(policy or select_policy(evaluation_records, sport=sport, experiment_key=experiment_key))
    policy_spec = _policy_spec(selected_policy)
    performance_summary = _load_performance_summary(ledger_path=ledger_path)
    filtered_candidates = filter_candidates(
        candidate_rows,
        sport=sport,
        ledger_path=ledger_path,
        evaluation_records=evaluation_records,
        policy=selected_policy,
        rejected_sink=rejected_sink,
    )
    # Reuses the single load above. `_owned_records` means we read them on this
    # call, so nothing else holds a reference and the defensive copy is waste.
    if _owned_records:
        history_rows = [record for record in evaluation_records if isinstance(record, Mapping)]
    else:
        history_rows = [dict(record) for record in evaluation_records if isinstance(record, Mapping)]
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