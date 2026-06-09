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
DEFAULT_LEDGER_PATH = repo_root_from(__file__) / "data" / "prediction_ledger.json


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
    closing_line: Any = None
    clv: float | None = None
    pnl: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "outcome": self.outcome,
            "closing_line": self.closing_line,
            "clv": self.clv,
            "pnl": self.pnl,
        }


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
    closing_line: Any = None,
    clv: Any = None,
    pnl: Any = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    record = _result_from_payload(
        {
            "prediction_id": prediction_id,
            "outcome": outcome,
            "closing_line": closing_line,
            "clv": clv,
            "pnl": pnl,
        }
    )
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    payload = _read_payload(path)
    results = [dict(item) for item in payload.get("results", []) if isinstance(item, Mapping)]
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

    payload["updated_at"] = _utc_now()
    _write_payload(path, payload)
    return result_dict


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


def get_performance_summary(ledger_path: Path | str | None = None) -> dict[str, Any]:
    predictions = load_all_predictions(ledger_path=ledger_path)
    results = [dict(item.get("result")) for item in predictions if isinstance(item.get("result"), Mapping)]
    settled = [item for item in results if _normalize_text(item.get("outcome")).lower() in {"win", "loss", "push", "void"}]
    decisive = [item for item in settled if _normalize_text(item.get("outcome")).lower() in {"win", "loss"}]

    win_rate = None
    if decisive:
        wins = sum(1 for item in decisive if _normalize_text(item.get("outcome")).lower() == "win")
        win_rate = wins / float(len(decisive))

    total_pnl = sum(_coerce_float(item.get("pnl")) or 0.0 for item in settled)
    settled_pnl = [(_coerce_float(item.get("pnl")) or 0.0) for item in settled]
    average_pnl = mean(settled_pnl) if settled_pnl else None

    closing_lines = [item.get("closing_line") for item in settled if item.get("closing_line") is not None]
    clv_values = [(_coerce_float(item.get("clv")) or 0.0) for item in settled if _coerce_float(item.get("clv")) is not None]
    average_clv = mean(clv_values) if clv_values else None

    by_sport: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        sport = _normalize_text(prediction.get("sport")).lower() or "unknown"
        bucket = by_sport.setdefault(sport, {"predictions": 0, "settled": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        bucket["predictions"] += 1
        result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
        if not isinstance(result, Mapping):
            continue
        outcome = _normalize_text(result.get("outcome")).lower()
        if outcome in {"win", "loss", "push", "void"}:
            bucket["settled"] += 1
        if outcome == "win":
            bucket["wins"] += 1
        if outcome == "loss":
            bucket["losses"] += 1
        bucket["pnl"] += _coerce_float(result.get("pnl")) or 0.0

    for bucket in by_sport.values():
        if bucket["wins"] + bucket["losses"]:
            bucket["win_rate"] = bucket["wins"] / float(bucket["wins"] + bucket["losses"])
        else:
            bucket["win_rate"] = None

    return {
        "schema_version": SCHEMA_VERSION,
        "sample_size": len(predictions),
        "settled_count": len(settled),
        "decisive_count": len(decisive),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "average_pnl": average_pnl,
        "average_clv": average_clv,
        "closing_lines": closing_lines,
        "by_sport": by_sport,
    }


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_LEDGER_PATH",
    "PredictionRecord",
    "PredictionResult",
    "record_prediction",
    "record_result",
    "load_all_predictions",
    "get_performance_summary",
]