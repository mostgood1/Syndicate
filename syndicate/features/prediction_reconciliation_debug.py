from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH


def _normalize_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        return None


def _load_ledger_rows(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    if ledger_path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, dict):
        return []
    predictions = [dict(item) for item in payload.get("predictions", []) if isinstance(item, Mapping)]
    results = [dict(item) for item in payload.get("results", []) if isinstance(item, Mapping)]
    result_index = {str(item.get("prediction_id") or "").strip(): item for item in results if str(item.get("prediction_id") or "").strip()}
    merged: list[dict[str, Any]] = []
    for prediction in predictions:
        prediction_id = str(prediction.get("id") or prediction.get("prediction_id") or "").strip()
        if prediction_id and prediction_id in result_index:
            prediction = {**prediction, "result": result_index[prediction_id]}
        merged.append(prediction)
    return merged or [payload]


def _record_selected_date(record: Mapping[str, Any]) -> str | None:
    for bucket_name in ("artifact_metadata", "query", "response", "features_snapshot", "recommendation"):
        bucket = record.get(bucket_name)
        if not isinstance(bucket, Mapping):
            continue
        for key in ("selected_date", "date", "game_date"):
            date_value = _normalize_date(bucket.get(key))
            if date_value:
                return date_value
    for key in ("selected_date", "date", "game_date"):
        date_value = _normalize_date(record.get(key))
        if date_value:
            return date_value
    return None


def _prediction_date(prediction: Mapping[str, Any]) -> str | None:
    return _record_selected_date(prediction)


def _row_for_debug(prediction: Mapping[str, Any]) -> dict[str, Any]:
    result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else {}
    query = prediction.get("query") if isinstance(prediction.get("query"), Mapping) else {}
    response = prediction.get("response") if isinstance(prediction.get("response"), Mapping) else {}
    artifact_metadata = prediction.get("artifact_metadata") if isinstance(prediction.get("artifact_metadata"), Mapping) else {}
    return {
        "prediction_id": prediction.get("prediction_id") or prediction.get("id"),
        "sport": artifact_metadata.get("sport") or query.get("sport") or response.get("sport") or prediction.get("sport"),
        "market": prediction.get("market") or response.get("market") or query.get("market"),
        "selection": prediction.get("selection") or prediction.get("pick") or prediction.get("name") or prediction.get("recommendation", {}).get("name"),
        "odds": prediction.get("odds") or prediction.get("recommendation", {}).get("odds"),
        "implied_probability": prediction.get("implied_probability") or prediction.get("recommendation", {}).get("implied_probability"),
        "model_probability": prediction.get("model_probability") or prediction.get("recommendation", {}).get("model_probability"),
        "edge": prediction.get("edge") or prediction.get("recommendation", {}).get("edge"),
        "confidence": prediction.get("confidence") or prediction.get("recommendation", {}).get("confidence"),
        "selected_date": _record_selected_date(prediction),
        "line": prediction.get("line") or prediction.get("recommendation", {}).get("line") or query.get("line") or response.get("line") or artifact_metadata.get("line"),
        "result_outcome": result.get("outcome"),
        "original_line": result.get("original_line"),
        "closing_line": result.get("closing_line"),
        "clv": result.get("clv"),
        "pnl": result.get("pnl"),
    }


def _read_ledger_payload(ledger_path: Path) -> dict[str, Any]:
    if not ledger_path.exists():
        return {"schema_version": 1, "predictions": [], "results": []}
    if ledger_path.suffix.lower() == ".jsonl":
        rows = _load_ledger_rows(ledger_path)
        return {"schema_version": 1, "predictions": rows, "results": [row for row in rows if str(row.get("result") or "").strip().lower() in {"win", "loss", "push", "void"}]}
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "predictions": [], "results": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "predictions": [], "results": []}
    if not isinstance(payload.get("predictions"), list):
        payload["predictions"] = []
    if not isinstance(payload.get("results"), list):
        payload["results"] = []
    return payload


def debug_prediction_reconciliation(
    date_value: str,
    *,
    ledger_path: Path | str | None = None,
    sample_size: int = 2,
) -> dict[str, Any]:
    date_token = _normalize_date(date_value)
    if date_token is None:
        raise ValueError("date_value must be an ISO date like YYYY-MM-DD")

    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    records = _load_ledger_rows(path)
    scoped_predictions = [prediction for prediction in records if _prediction_date(prediction) == date_token]

    results = [dict(item) for item in records if isinstance(item, Mapping) and str(item.get("result") or "").strip().lower() in {"win", "loss", "push", "void"}]
    scoped_prediction_ids = {
        str(prediction.get("prediction_id") or prediction.get("id") or "").strip()
        for prediction in scoped_predictions
        if str(prediction.get("prediction_id") or prediction.get("id") or "").strip()
    }
    scoped_results = [item for item in results if str(item.get("prediction_id") or "").strip() in scoped_prediction_ids]
    result_counts = Counter(str(item.get("prediction_id") or "").strip() for item in scoped_results if str(item.get("prediction_id") or "").strip())
    duplicate_results = [
        {"prediction_id": prediction_id, "count": count}
        for prediction_id, count in sorted(result_counts.items())
        if count > 1
    ]

    result_index = {str(item.get("prediction_id") or "").strip(): item for item in scoped_results if str(item.get("prediction_id") or "").strip()}

    matched_predictions = [prediction for prediction in scoped_predictions if str(prediction.get("prediction_id") or prediction.get("id") or "").strip() in result_index]
    unmatched_predictions = [prediction for prediction in scoped_predictions if str(prediction.get("prediction_id") or prediction.get("id") or "").strip() not in result_index]

    payload_out = {
        "date": date_token,
        "ledger_path": str(path),
        "raw_records_loaded": len(records),
        "total_predictions": len(scoped_predictions),
        "total_results_recorded": len(scoped_results),
        "unmatched_predictions": len(unmatched_predictions),
        "duplicate_results": duplicate_results,
        "sample_matched_rows": [_row_for_debug(prediction) for prediction in matched_predictions[:sample_size]],
        "sample_unmatched_rows": [_row_for_debug(prediction) for prediction in unmatched_predictions[:sample_size]],
    }

    print(json.dumps(payload_out, indent=2, sort_keys=True, default=str))
    return payload_out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect prediction-to-reconciliation integrity for a date")
    parser.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--ledger-path", default="", help="Optional ledger path override")
    parser.add_argument("--sample-size", type=int, default=2, help="Number of matched/unmatched rows to print")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger_path) if str(args.ledger_path or "").strip() else None
    debug_prediction_reconciliation(args.date, ledger_path=ledger_path, sample_size=max(1, int(args.sample_size or 2)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
