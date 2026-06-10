from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from syndicate.features.shared.source_roots import repo_root_from


SCHEMA_VERSION = 1
DEFAULT_LEDGER_PATH = repo_root_from(__file__) / "data" / "prediction_ledger.json"
DEFAULT_SIGNAL_WEIGHTS_PATH = repo_root_from(__file__) / "data" / "signal_weights.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    return str(uuid.uuid4())


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
    try:
        return float(text.replace("%", ""))
    except Exception:
        return None


def _coerce_probability(value: Any) -> float | None:
    probability = _coerce_float(value)
    if probability is None:
        return None
    if 0.0 <= probability <= 1.0:
        return probability
    if 1.0 < probability <= 100.0:
        return probability / 100.0
    return None


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "predictions": [], "results": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "predictions": [], "results": []}
    if not isinstance(payload, dict):
        return {"schema_version": SCHEMA_VERSION, "predictions": [], "results": []}
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("predictions", [])
    payload.setdefault("results", [])
    if not isinstance(payload.get("predictions"), list):
        payload["predictions"] = []
    if not isinstance(payload.get("results"), list):
        payload["results"] = []
    return payload


def _write_payload(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str), encoding="utf-8")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_signal_map(value: Any) -> dict[str, Any]:
    return _copy_mapping(value)


def _latest_prediction_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        prediction_id = _normalize_text(record.get("prediction_id"))
        if prediction_id:
            latest[prediction_id] = record
    return latest


def _latest_result_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        prediction_id = _normalize_text(record.get("prediction_id"))
        if prediction_id:
            latest[prediction_id] = record
    return latest


def _read_signal_weights(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "default_weight": 1.0, "weights": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "default_weight": 1.0, "weights": {}}
    if not isinstance(payload, dict):
        return {"schema_version": SCHEMA_VERSION, "default_weight": 1.0, "weights": {}}
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("default_weight", 1.0)
    payload.setdefault("weights", {})
    if not isinstance(payload.get("weights"), dict):
        payload["weights"] = {}
    return payload


def _write_signal_weights(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str), encoding="utf-8")


def _signal_weight(signal_name: Any, *, weights_payload: Mapping[str, Any] | None = None) -> float:
    payload = weights_payload if isinstance(weights_payload, Mapping) else _read_signal_weights(DEFAULT_SIGNAL_WEIGHTS_PATH)
    default_weight = _coerce_float(payload.get("default_weight")) or 1.0
    weights = payload.get("weights") if isinstance(payload.get("weights"), Mapping) else {}
    key = _normalize_text(signal_name)
    if not key:
        return default_weight
    weight = _coerce_float(weights.get(key))
    return weight if weight is not None else default_weight


def _update_signal_weights_from_prediction(record: Mapping[str, Any], *, weights_path: Path | None = None) -> dict[str, Any]:
    path = Path(weights_path) if weights_path is not None else DEFAULT_SIGNAL_WEIGHTS_PATH
    payload = _read_signal_weights(path)
    weights = dict(payload.get("weights") or {})
    signals = record.get("signals") if isinstance(record.get("signals"), Mapping) else {}
    contributions = signals.get("signal_contributions") if isinstance(signals.get("signal_contributions"), Mapping) else {}
    if not contributions:
        return payload

    result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
    outcome = _normalize_text((result.get("outcome") if isinstance(result, Mapping) else record.get("outcome"))).lower()
    if outcome not in {"win", "loss"}:
        return payload

    outcome_sign = 1.0 if outcome == "win" else -1.0
    for signal_name, contribution in contributions.items():
        contribution_value = _coerce_float(contribution)
        if contribution_value is None:
            continue
        current_weight = _signal_weight(signal_name, weights_payload=payload)
        updated_weight = max(0.5, min(1.5, current_weight + (contribution_value * outcome_sign * 0.03)))
        weights[str(signal_name)] = round(updated_weight, 4)

    payload["weights"] = weights
    payload["updated_at"] = _utc_now()
    _write_signal_weights(path, payload)
    return payload


@dataclass(frozen=True)
class PredictionRecord:
    id: str = field(default_factory=_new_id)
    timestamp: str = field(default_factory=_utc_now)
    sport: str = ""
    market: str = ""
    selection: str = ""
    odds: float | None = None
    implied_probability: float | None = None
    model_probability: float | None = None
    edge: float | None = None
    confidence: float | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    features_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "sport": self.sport,
            "market": self.market,
            "selection": self.selection,
            "odds": self.odds,
            "implied_probability": self.implied_probability,
            "model_probability": self.model_probability,
            "edge": self.edge,
            "confidence": self.confidence,
            "signals": dict(self.signals),
            "features_snapshot": dict(self.features_snapshot),
        }


@dataclass(frozen=True)
class PredictionResult:
    prediction_id: str
    outcome: str = "pending"
    original_line: Any = None
    closing_line: Any = None
    clv: float | None = None
    pnl: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "outcome": self.outcome,
            "original_line": self.original_line,
            "closing_line": self.closing_line,
            "clv": self.clv,
            "pnl": self.pnl,
        }


def _clv_from_lines(original_line: Any, closing_line: Any) -> float | None:
    original_value = _coerce_float(original_line)
    closing_value = _coerce_float(closing_line)
    if original_value is None or closing_value is None:
        return None
    return round(closing_value - original_value, 4)


def _prediction_from_payload(payload: Mapping[str, Any]) -> PredictionRecord:
    return PredictionRecord(
        id=_normalize_text(payload.get("id")) or _new_id(),
        timestamp=_normalize_text(payload.get("timestamp")) or _utc_now(),
        sport=_normalize_text(payload.get("sport")),
        market=_normalize_text(payload.get("market")),
        selection=_normalize_text(payload.get("selection")),
        odds=_coerce_float(payload.get("odds")),
        implied_probability=_coerce_probability(payload.get("implied_probability")),
        model_probability=_coerce_probability(payload.get("model_probability")),
        edge=_coerce_float(payload.get("edge")),
        confidence=_coerce_float(payload.get("confidence")),
        signals=_normalize_signal_map(payload.get("signals")),
        features_snapshot=_normalize_signal_map(payload.get("features_snapshot")),
    )


def _result_from_payload(payload: Mapping[str, Any]) -> PredictionResult:
    return PredictionResult(
        prediction_id=_normalize_text(payload.get("prediction_id")),
        outcome=_normalize_text(payload.get("outcome")) or "pending",
        original_line=payload.get("original_line"),
        closing_line=payload.get("closing_line"),
        clv=_coerce_float(payload.get("clv")),
        pnl=_coerce_float(payload.get("pnl")),
    )


def _upsert_prediction_record(path: Path, record: PredictionRecord) -> dict[str, Any]:
    payload = _read_payload(path)
    predictions = [dict(item) for item in payload.get("predictions", []) if isinstance(item, Mapping)]
    prediction_dict = record.to_dict()
    predictions.append(prediction_dict)
    payload["predictions"] = predictions
    payload["updated_at"] = _utc_now()
    _write_payload(path, payload)
    return prediction_dict


def record_prediction(
    *,
    sport: Any,
    market: Any,
    selection: Any,
    odds: Any = None,
    implied_probability: Any = None,
    model_probability: Any = None,
    edge: Any = None,
    confidence: Any = None,
    signals: Any = None,
    features_snapshot: Any = None,
    timestamp: str | None = None,
    prediction_id: str | None = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    payload = _prediction_from_payload(
        {
            "id": prediction_id,
            "timestamp": timestamp,
            "sport": sport,
            "market": market,
            "selection": selection,
            "odds": odds,
            "implied_probability": implied_probability,
            "model_probability": model_probability,
            "edge": edge,
            "confidence": confidence,
            "signals": signals,
            "features_snapshot": features_snapshot,
        }
    )
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    return _upsert_prediction_record(path, payload)


def record_result(
    *,
    prediction_id: Any,
    outcome: Any,
    original_line: Any = None,
    closing_line: Any = None,
    clv: Any = None,
    pnl: Any = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    computed_clv = _clv_from_lines(original_line, closing_line)
    record = _result_from_payload(
        {
            "prediction_id": prediction_id,
            "outcome": outcome,
            "original_line": original_line,
            "closing_line": closing_line,
            "clv": computed_clv if computed_clv is not None else clv,
            "pnl": pnl,
        }
    )
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    payload = _read_payload(path)
    results = [dict(item) for item in payload.get("results", []) if isinstance(item, Mapping)]
    result_index = _latest_result_index(results)
    existing_result = result_index.get(record.prediction_id)
    if existing_result is not None:
        return dict(existing_result)

    result_dict = record.to_dict()
    results.append(result_dict)
    payload["results"] = results

    predictions = [dict(item) for item in payload.get("predictions", []) if isinstance(item, Mapping)]
    index = _latest_prediction_index(predictions)
    prediction = index.get(record.prediction_id)
    if prediction is not None:
        prediction["result"] = result_dict
        prediction["updated_at"] = _utc_now()
        payload["predictions"] = predictions
        _update_signal_weights_from_prediction(prediction)

    payload["updated_at"] = _utc_now()
    _write_payload(path, payload)
    return result_dict


def result_exists(prediction_id: Any, ledger_path: Path | str | None = None) -> bool:
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    payload = _read_payload(path)
    results = [dict(item) for item in payload.get("results", []) if isinstance(item, Mapping)]
    return _normalize_text(prediction_id) in _latest_result_index(results)


def load_all_predictions(ledger_path: Path | str | None = None) -> list[dict[str, Any]]:
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    payload = _read_payload(path)
    predictions = [dict(item) for item in payload.get("predictions", []) if isinstance(item, Mapping)]
    results = [dict(item) for item in payload.get("results", []) if isinstance(item, Mapping)]
    result_index = {str(item.get("prediction_id") or ""): item for item in results if str(item.get("prediction_id") or "").strip()}
    merged: list[dict[str, Any]] = []
    for prediction in predictions:
        prediction_id = str(prediction.get("id") or "").strip()
        if prediction_id and prediction_id in result_index:
            prediction = {**prediction, "result": result_index[prediction_id]}
        merged.append(prediction)
    return merged


def _prediction_result(prediction: Mapping[str, Any]) -> dict[str, Any] | None:
    result = prediction.get("result")
    return dict(result) if isinstance(result, Mapping) else None


def _settled_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settled: list[dict[str, Any]] = []
    for prediction in predictions:
        result = _prediction_result(prediction)
        if result is None:
            continue
        outcome = _normalize_text(result.get("outcome")).lower()
        if outcome in {"win", "loss", "push", "void"}:
            settled.append(prediction)
    return settled


def _breakdown_by_field(predictions: list[dict[str, Any]], field_name: str) -> dict[str, dict[str, Any]]:
    breakdown: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        key = _normalize_text(prediction.get(field_name)).lower() or "unknown"
        bucket = breakdown.setdefault(
            key,
            {
                "predictions": 0,
                "settled": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
                "edges": [],
            },
        )
        bucket["predictions"] += 1
        edge_value = _coerce_float(prediction.get("edge"))
        if edge_value is not None:
            bucket["edges"].append(edge_value)
        result = _prediction_result(prediction)
        if result is None:
            continue
        outcome = _normalize_text(result.get("outcome")).lower()
        if outcome in {"win", "loss", "push", "void"}:
            bucket["settled"] += 1
        if outcome == "win":
            bucket["wins"] += 1
        if outcome == "loss":
            bucket["losses"] += 1
        bucket["pnl"] += _coerce_float(result.get("pnl")) or 0.0

    for bucket in breakdown.values():
        decisive = bucket["wins"] + bucket["losses"]
        bucket["win_rate"] = bucket["wins"] / float(decisive) if decisive else None
        bucket["roi"] = bucket["pnl"] / float(bucket["predictions"] or 1)
        bucket["avg_edge"] = mean(bucket["edges"]) if bucket["edges"] else None
        bucket["edges"] = None
    return breakdown


def _roi(predictions: list[dict[str, Any]]) -> float | None:
    if not predictions:
        return None
    total_pnl = 0.0
    total_stake = 0.0
    for prediction in predictions:
        result = _prediction_result(prediction)
        if result is None:
            continue
        outcome = _normalize_text(result.get("outcome")).lower()
        if outcome not in {"win", "loss", "push", "void"}:
            continue
        total_pnl += _coerce_float(result.get("pnl")) or 0.0
        stake = _coerce_float(prediction.get("stake"))
        total_stake += stake if stake is not None and stake > 0 else 1.0
    if total_stake <= 0.0:
        return None
    return round(total_pnl / total_stake, 4)


def get_performance_summary(ledger_path: Path | str | None = None) -> dict[str, Any]:
    predictions = load_all_predictions(ledger_path=ledger_path)
    settled = _settled_predictions(predictions)
    results = [_prediction_result(item) for item in settled]
    decisive = [item for item in results if item is not None and _normalize_text(item.get("outcome")).lower() in {"win", "loss"}]

    win_rate = None
    if decisive:
        wins = sum(1 for item in decisive if _normalize_text(item.get("outcome")).lower() == "win")
        win_rate = wins / float(len(decisive))

    total_pnl = sum(_coerce_float(item.get("pnl")) or 0.0 for item in settled)
    settled_pnl = [(_coerce_float(item.get("pnl")) or 0.0) for item in settled]
    average_pnl = mean(settled_pnl) if settled_pnl else None
    edge_values = [_coerce_float(item.get("edge")) for item in predictions if _coerce_float(item.get("edge")) is not None]
    average_edge = mean(edge_values) if edge_values else None
    roi = _roi(predictions)

    closing_lines = [item.get("closing_line") for item in settled if item.get("closing_line") is not None]
    clv_values = [(_coerce_float(item.get("clv")) or 0.0) for item in settled if _coerce_float(item.get("clv")) is not None]
    average_clv = mean(clv_values) if clv_values else None

    by_sport = _breakdown_by_field(predictions, "sport")
    by_market = _breakdown_by_field(predictions, "market")

    return {
        "schema_version": SCHEMA_VERSION,
        "total_bets": len(predictions),
        "settled_count": len(settled),
        "decisive_count": len(decisive),
        "win_rate": win_rate,
        "roi": roi,
        "total_pnl": total_pnl,
        "avg_edge": average_edge,
        "avg_clv": average_clv,
        "average_clv": average_clv,
        "closing_lines": closing_lines,
        "by_sport": by_sport,
        "by_market": by_market,
    }


def analyze_prediction_performance(ledger_path: Path | str | None = None) -> dict[str, Any]:
    predictions = load_all_predictions(ledger_path=ledger_path)
    settled = _settled_predictions(predictions)

    signal_rows: dict[str, dict[str, Any]] = {}
    edge_rows: list[dict[str, Any]] = []
    confidence_rows: list[dict[str, Any]] = []

    for prediction in settled:
        result = _prediction_result(prediction)
        if result is None:
            continue

        outcome = _normalize_text(result.get("outcome")).lower()
        pnl = _coerce_float(result.get("pnl")) or 0.0
        edge = _coerce_float(prediction.get("edge"))
        confidence = _coerce_float(prediction.get("confidence"))

        if edge is not None:
            edge_rows.append(
                {
                    "prediction_id": prediction.get("id"),
                    "edge": edge,
                    "outcome": outcome,
                    "pnl": pnl,
                }
            )
        if confidence is not None:
            confidence_rows.append(
                {
                    "prediction_id": prediction.get("id"),
                    "confidence": confidence,
                    "outcome": outcome,
                    "pnl": pnl,
                }
            )

        signals = prediction.get("signals") if isinstance(prediction.get("signals"), Mapping) else {}
        signal_contributions = signals.get("signal_contributions") if isinstance(signals.get("signal_contributions"), Mapping) else {}
        if not signal_contributions:
            continue

        for signal_name, contribution in signal_contributions.items():
            contribution_value = _coerce_float(contribution)
            if contribution_value is None:
                continue
            bucket = signal_rows.setdefault(
                str(signal_name),
                {
                    "signal_name": str(signal_name),
                    "samples": 0,
                    "total_contribution": 0.0,
                    "wins": 0,
                    "losses": 0,
                    "pnl": 0.0,
                },
            )
            bucket["samples"] += 1
            bucket["total_contribution"] += contribution_value
            bucket["pnl"] += pnl
            if outcome == "win":
                bucket["wins"] += 1
            elif outcome == "loss":
                bucket["losses"] += 1

    signal_insights: list[dict[str, Any]] = []
    for bucket in signal_rows.values():
        samples = int(bucket["samples"] or 0)
        decisive = int(bucket["wins"] + bucket["losses"])
        win_rate = (bucket["wins"] / float(decisive)) if decisive else None
        signal_insights.append(
            {
                "signal_name": bucket["signal_name"],
                "samples": samples,
                "avg_contribution": round(bucket["total_contribution"] / float(samples), 4) if samples else None,
                "win_rate": win_rate,
                "pnl": round(bucket["pnl"], 4),
            }
        )

    best_signals = sorted(
        [row for row in signal_insights if row.get("avg_contribution") is not None],
        key=lambda row: (float(row.get("win_rate") or 0.0), float(row.get("avg_contribution") or 0.0), int(row.get("samples") or 0)),
        reverse=True,
    )[:5]
    worst_signals = sorted(
        [row for row in signal_insights if row.get("avg_contribution") is not None],
        key=lambda row: (float(row.get("win_rate") or 0.0), float(row.get("avg_contribution") or 0.0), int(row.get("samples") or 0)),
    )[:5]

    overconfident_zones: list[dict[str, Any]] = []
    if confidence_rows:
        for threshold_low, threshold_high, label in ((0.75, 1.0, "high_confidence"), (0.60, 0.75, "medium_high_confidence")):
            zone = [row for row in confidence_rows if threshold_low <= float(row.get("confidence") or 0.0) < threshold_high]
            if not zone:
                continue
            wins = sum(1 for row in zone if row.get("outcome") == "win")
            losses = sum(1 for row in zone if row.get("outcome") == "loss")
            decisive = wins + losses
            win_rate = wins / float(decisive) if decisive else None
            avg_pnl = mean([float(row.get("pnl") or 0.0) for row in zone]) if zone else None
            if win_rate is not None and win_rate < 0.5:
                overconfident_zones.append(
                    {
                        "zone": label,
                        "confidence_range": [threshold_low, threshold_high],
                        "samples": len(zone),
                        "win_rate": win_rate,
                        "avg_pnl": avg_pnl,
                    }
                )

    underperforming_edges: list[dict[str, Any]] = []
    if edge_rows:
        edge_buckets = {
            "very_positive": [row for row in edge_rows if float(row.get("edge") or 0.0) >= 0.05],
            "slightly_positive": [row for row in edge_rows if 0.0 <= float(row.get("edge") or 0.0) < 0.05],
            "negative": [row for row in edge_rows if float(row.get("edge") or 0.0) < 0.0],
        }
        for bucket_name, rows in edge_buckets.items():
            if not rows:
                continue
            wins = sum(1 for row in rows if row.get("outcome") == "win")
            losses = sum(1 for row in rows if row.get("outcome") == "loss")
            decisive = wins + losses
            win_rate = wins / float(decisive) if decisive else None
            avg_pnl = mean([float(row.get("pnl") or 0.0) for row in rows]) if rows else None
            if win_rate is None or win_rate < 0.5 or avg_pnl is not None and avg_pnl < 0.0:
                underperforming_edges.append(
                    {
                        "bucket": bucket_name,
                        "samples": len(rows),
                        "win_rate": win_rate,
                        "avg_edge": mean([float(row.get("edge") or 0.0) for row in rows]),
                        "avg_pnl": avg_pnl,
                    }
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "sample_size": len(settled),
        "best_performing_signals": best_signals[:3],
        "worst_signals": worst_signals[:3],
        "overconfident_zones": overconfident_zones,
        "underperforming_edges": underperforming_edges,
    }


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_SIGNAL_WEIGHTS_PATH",
    "PredictionRecord",
    "PredictionResult",
    "record_prediction",
    "record_result",
    "result_exists",
    "load_all_predictions",
    "get_performance_summary",
    "_signal_weight",
]