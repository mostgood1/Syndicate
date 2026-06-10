from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH as DEFAULT_EVALUATION_LEDGER_PATH
from syndicate.features.shared.intelligence_evaluation import compute_metrics


SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "performance_summary.json"
DEFAULT_COMPATIBILITY_OUTPUT_PATH = REPO_ROOT / "reports" / "intelligence" / "performance_summary.json"
DEFAULT_PREDICTION_LEDGER_PATH = REPO_ROOT / "data" / "prediction_ledger.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_text(value, "").replace(",", "")
    if not text:
        return None
    try:
        return float(text.replace("%", ""))
    except Exception:
        return None


def _safe_probability(value: Any) -> float | None:
    probability = _safe_float(value)
    if probability is None:
        return None
    if 0.0 <= probability <= 1.0:
        return probability
    if 1.0 < probability <= 100.0:
        return probability / 100.0
    return None


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
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


def _normalized_prediction_ledger_records(ledger_path: Path | str | None = None) -> list[dict[str, Any]]:
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_PREDICTION_LEDGER_PATH
    normalized: list[dict[str, Any]] = []
    for prediction in load_all_predictions(path):
        if not isinstance(prediction, Mapping):
            continue
        prediction_payload = dict(prediction)
        result = _copy_mapping(prediction_payload.get("result"))
        recommendation = _copy_mapping(prediction_payload.get("recommendation"))
        query = _copy_mapping(prediction_payload.get("query"))
        response = _copy_mapping(prediction_payload.get("response"))
        artifact_metadata = _copy_mapping(prediction_payload.get("artifact_metadata"))
        normalized.append(
            {
                **prediction_payload,
                "result": _safe_text(result.get("outcome") or prediction_payload.get("result") or "pending", "pending"),
                "pnl": _safe_float(result.get("pnl") or prediction_payload.get("pnl")),
                "closing_line": result.get("closing_line") or prediction_payload.get("closing_line"),
                "implied_probability": _safe_probability(
                    result.get("implied_probability")
                    or prediction_payload.get("implied_probability")
                    or recommendation.get("implied_probability")
                    or recommendation.get("model_probability")
                    or recommendation.get("confidence")
                ),
                "stake": _safe_float(result.get("stake") or prediction_payload.get("stake")) or 1.0,
                "query": query,
                "response": response,
                "artifact_metadata": artifact_metadata,
                "recommendation": recommendation,
            }
        )
    return normalized


def _latest_by_recommendation_id(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    fallback: dict[str, dict[str, Any]] = {}
    fallback_order: list[str] = []
    for record in records:
        payload = dict(record)
        recommendation_id = _safe_text(payload.get("recommendation_id"))
        if recommendation_id:
            latest[recommendation_id] = payload
            continue
        prediction_id = _safe_text(payload.get("prediction_id") or payload.get("id"))
        fallback_key = prediction_id or f"fallback_{len(fallback_order)}"
        if fallback_key not in fallback:
            fallback_order.append(fallback_key)
        fallback[fallback_key] = payload
    return [*(fallback[key] for key in fallback_order if key in fallback), *latest.values()]


def _record_sport(record: Mapping[str, Any]) -> str:
    for bucket_name in ("artifact_metadata", "recommendation", "response", "query"):
        bucket = record.get(bucket_name)
        if isinstance(bucket, Mapping):
            sport = _safe_text(bucket.get("sport") or bucket.get("sport_slug"), "").lower()
            if sport:
                return sport
    return _safe_text(record.get("sport") or record.get("sport_slug"), "unknown").lower()


def _record_market(record: Mapping[str, Any]) -> str:
    for bucket_name in ("recommendation", "response", "query"):
        bucket = record.get(bucket_name)
        if isinstance(bucket, Mapping):
            market = _safe_text(bucket.get("market") or bucket.get("market_key") or bucket.get("market_label"), "").lower()
            if market:
                return market
    return _safe_text(record.get("market") or record.get("market_key") or record.get("market_label"), "unknown").lower()


def _record_probability(record: Mapping[str, Any]) -> float | None:
    for bucket_name in ("recommendation", "response", "query"):
        bucket = record.get(bucket_name)
        if isinstance(bucket, Mapping):
            probability = _safe_probability(
                bucket.get("model_probability")
                or bucket.get("market_probability")
                or bucket.get("implied_probability")
                or bucket.get("confidence")
            )
            if probability is not None:
                return probability
    return _safe_probability(record.get("implied_probability") or record.get("model_probability") or record.get("confidence"))


def _record_result(record: Mapping[str, Any]) -> str:
    value = record.get("result")
    if isinstance(value, Mapping):
        value = value.get("outcome") or value.get("result") or value.get("grade")
    text = _safe_text(value, "pending").lower()
    return text if text else "pending"


def _settled_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(record) for record in records if _record_result(record) in {"win", "loss", "push", "void"}]


def _decisive_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(record) for record in records if _record_result(record) in {"win", "loss"}]


def _metric_block(records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = compute_metrics(records=records)
    return {
        "total_bets": int(metrics.get("settled_count") or 0),
        "settled_count": int(metrics.get("settled_count") or 0),
        "decisive_count": int(metrics.get("decisive_count") or 0),
        "win_rate": metrics.get("win_rate"),
        "roi": metrics.get("roi"),
        "total_pnl": metrics.get("pnl"),
    }


def _group_summary(records: Iterable[Mapping[str, Any]], *, key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = _safe_text(key_fn(record), "unknown").lower() or "unknown"
        grouped.setdefault(key, []).append(dict(record))
    return {key: _metric_block(rows) for key, rows in sorted(grouped.items(), key=lambda item: item[0])}


def _nested_group_summary(records: Iterable[Mapping[str, Any]], *, outer_key_fn, inner_key_fn) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        outer_key = _safe_text(outer_key_fn(record), "unknown").lower() or "unknown"
        inner_key = _safe_text(inner_key_fn(record), "unknown").lower() or "unknown"
        grouped.setdefault(outer_key, {}).setdefault(inner_key, []).append(dict(record))
    nested: dict[str, dict[str, dict[str, Any]]] = {}
    for outer_key, inner_groups in sorted(grouped.items(), key=lambda item: item[0]):
        nested[outer_key] = {inner_key: _metric_block(rows) for inner_key, rows in sorted(inner_groups.items(), key=lambda item: item[0])}
    return nested


def _calibration_bucket(probability: float, *, bucket_size: float) -> str:
    clamped = max(0.0, min(0.999999, probability))
    bucket_index = int(clamped / bucket_size)
    start = round(bucket_index * bucket_size, 2)
    end = round(min(1.0, start + bucket_size), 2)
    return f"{start:.2f}-{end:.2f}"


def _bucket_summary(records: Iterable[Mapping[str, Any]], *, bucket_size: float) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in _decisive_records(records):
        probability = _record_probability(record)
        if probability is None:
            continue
        bucket_key = _calibration_bucket(probability, bucket_size=bucket_size)
        bucket = buckets.setdefault(
            bucket_key,
            {
                "bucket": bucket_key,
                "probabilities": [],
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
            },
        )
        bucket["probabilities"].append(probability)
        bucket["pnl"] += _safe_float(record.get("pnl")) or 0.0
        if _record_result(record) == "win":
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1

    rows: list[dict[str, Any]] = []
    for bucket_key in sorted(buckets.keys(), key=lambda label: float(label.split("-", 1)[0])):
        bucket = buckets[bucket_key]
        decisive_count = bucket["wins"] + bucket["losses"]
        average_probability = mean(bucket["probabilities"]) if bucket["probabilities"] else None
        actual_win_rate = bucket["wins"] / float(decisive_count) if decisive_count else None
        rows.append(
            {
                "bucket": bucket_key,
                "predicted_probability": round(average_probability, 4) if average_probability is not None else None,
                "actual_win_rate": round(actual_win_rate, 4) if actual_win_rate is not None else None,
                "count": len(bucket["probabilities"]),
                "settled_count": decisive_count,
                "wins": bucket["wins"],
                "losses": bucket["losses"],
                "total_pnl": round(float(bucket["pnl"]), 4),
                "roi": round(float(bucket["pnl"]) / float(decisive_count), 4) if decisive_count else None,
                "calibration_error": round(abs((average_probability or 0.0) - actual_win_rate), 4) if average_probability is not None and actual_win_rate is not None else None,
            }
        )
    return rows


def _load_records(*, ledger_path: Path | str | None = None, prediction_ledger_path: Path | str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evaluation_path = Path(ledger_path) if ledger_path is not None else DEFAULT_EVALUATION_LEDGER_PATH
    evaluation_records = _load_jsonl_records(evaluation_path)
    source = {
        "evaluation_ledger_path": str(evaluation_path),
        "evaluation_ledger_count": len(evaluation_records),
        "prediction_ledger_path": None,
        "prediction_ledger_count": 0,
        "used_prediction_ledger_fallback": False,
    }
    if evaluation_records:
        return evaluation_records, source

    prediction_path = Path(prediction_ledger_path) if prediction_ledger_path is not None else DEFAULT_PREDICTION_LEDGER_PATH
    prediction_records = _normalized_prediction_ledger_records(prediction_path)
    source.update(
        {
            "prediction_ledger_path": str(prediction_path),
            "prediction_ledger_count": len(prediction_records),
            "used_prediction_ledger_fallback": True,
        }
    )
    return prediction_records, source


def write_performance_summary(
    summary: Mapping[str, Any],
    *,
    output_path: Path | str | None = None,
    compatibility_output_path: Path | str | None = None,
) -> Path:
    target = Path(output_path) if output_path is not None else DEFAULT_OUTPUT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary), indent=2, sort_keys=True, ensure_ascii=False, default=str), encoding="utf-8")

    compat_target = Path(compatibility_output_path) if compatibility_output_path is not None else DEFAULT_COMPATIBILITY_OUTPUT_PATH
    if compat_target != target:
        compat_target.parent.mkdir(parents=True, exist_ok=True)
        compat_target.write_text(json.dumps(dict(summary), indent=2, sort_keys=True, ensure_ascii=False, default=str), encoding="utf-8")
    return target


def build_performance_summary(
    *,
    ledger_path: Path | str | None = None,
    prediction_ledger_path: Path | str | None = None,
    output_path: Path | str | None = None,
    compatibility_output_path: Path | str | None = None,
    bucket_size: float = 0.1,
    write_output: bool = True,
) -> dict[str, Any]:
    records, source = _load_records(ledger_path=ledger_path, prediction_ledger_path=prediction_ledger_path)
    overall = _metric_block(records)
    settled_records = _settled_records(records)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "source": source,
        "overall": overall,
        "by_sport": _group_summary(settled_records, key_fn=_record_sport),
        "by_market": _group_summary(settled_records, key_fn=_record_market),
        "by_sport_market": _nested_group_summary(settled_records, outer_key_fn=_record_sport, inner_key_fn=_record_market),
        "by_probability_bucket": _bucket_summary(settled_records, bucket_size=bucket_size),
        "prediction_ledger": {
            "used_as_fallback": bool(source.get("used_prediction_ledger_fallback")),
            "prediction_ledger_count": int(source.get("prediction_ledger_count") or 0),
        },
    }

    if write_output:
        write_performance_summary(
            summary,
            output_path=output_path,
            compatibility_output_path=compatibility_output_path,
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate historical betting performance into a summary JSON.")
    parser.add_argument("--ledger-path", default="", help="Optional evaluation ledger override")
    parser.add_argument("--prediction-ledger-path", default="", help="Optional prediction ledger override")
    parser.add_argument("--out", default="", help="Primary summary output path override")
    parser.add_argument("--compat-out", default="", help="Compatibility output path override")
    parser.add_argument("--bucket-size", type=float, default=0.1, help="Probability bucket width for calibration")
    parser.add_argument("--no-write", action="store_true", help="Build the summary but do not write files")
    args = parser.parse_args(argv)

    summary = build_performance_summary(
        ledger_path=Path(args.ledger_path) if str(args.ledger_path).strip() else None,
        prediction_ledger_path=Path(args.prediction_ledger_path) if str(args.prediction_ledger_path).strip() else None,
        output_path=Path(args.out) if str(args.out).strip() else None,
        compatibility_output_path=Path(args.compat_out) if str(args.compat_out).strip() else None,
        bucket_size=max(0.01, float(args.bucket_size or 0.1)),
        write_output=not bool(args.no_write),
    )
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())