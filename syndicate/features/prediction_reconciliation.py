from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.prediction_ledger import record_result


logger = logging.getLogger(__name__)


RECONCILIATION_PATTERNS = (
    "recon_props_{date}.csv",
    "recon_games_{date}.csv",
    "props_actuals_{date}.csv",
    "game_results_{date}.csv",
    "game_results_{date}.json",
    "closing_lines_{date}.csv",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _prediction_date(prediction: Mapping[str, Any]) -> str | None:
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("selected_date", "date", "game_date"):
        value = str(features.get(key) or "").strip()
        if len(value) >= 10:
            return value[:10]
    timestamp = str(prediction.get("timestamp") or "").strip()
    if len(timestamp) >= 10:
        return timestamp[:10]
    return None


def _prediction_keys(prediction: Mapping[str, Any]) -> set[str]:
    keys = {
        _normalize_text(prediction.get("sport")),
        _normalize_text(prediction.get("market")),
        _normalize_text(prediction.get("selection")),
    }
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("event_id", "game_id", "player_name", "player", "team", "name", "market_key", "line"):
        keys.add(_normalize_text(features.get(key)))
    return {item for item in keys if item}


def _row_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {
        _normalize_text(row.get("sport")),
        _normalize_text(row.get("market")),
        _normalize_text(row.get("selection")),
        _normalize_text(row.get("player")),
        _normalize_text(row.get("name")),
        _normalize_text(row.get("team")),
    }
    return {item for item in keys if item}


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _candidate_result_paths(date_value: str, roots: Sequence[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in RECONCILIATION_PATTERNS:
            for candidate in root.rglob(pattern.format(date=date_value)):
                if candidate.is_file():
                    paths.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _result_rows_for_date(date_value: str, roots: Sequence[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _candidate_result_paths(date_value, roots):
        if path.suffix.lower() == ".csv":
            rows.extend(_load_csv_rows(path))
        elif path.suffix.lower() == ".json":
            rows.extend(_load_json_rows(path))
    return rows


def _row_outcome(row: Mapping[str, Any], prediction: Mapping[str, Any]) -> str | None:
    explicit = _normalize_text(row.get("result") or row.get("outcome") or row.get("grade"))
    if explicit in {"win", "loss", "push", "void"}:
        return explicit

    actual_value = row.get("actual")
    line_value = row.get("closing_line") or row.get("line") or row.get("market_line")
    if actual_value is None or line_value is None:
        return None

    try:
        actual = float(str(actual_value).replace(",", ""))
        line = float(str(line_value).replace(",", ""))
    except Exception:
        return None

    selection_text = _normalize_text(prediction.get("selection"))
    if "under" in selection_text:
        if actual < line:
            return "win"
        if actual > line:
            return "loss"
        return "push"
    if "over" in selection_text or selection_text.endswith("+"):
        if actual > line:
            return "win"
        if actual < line:
            return "loss"
        return "push"
    return None


def _row_original_line(prediction: Mapping[str, Any], row: Mapping[str, Any]) -> Any:
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("original_line", "line", "market_line", "prop_line"):
        value = features.get(key)
        if value is not None and str(value).strip() != "":
            return value
    for key in ("original_line", "line", "market_line", "prop_line"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _row_closing_line(row: Mapping[str, Any]) -> Any:
    for key in ("closing_line", "closing", "close_line", "line"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _american_profit(odds: Any, stake: float = 1.0) -> float | None:
    try:
        value = float(str(odds).replace(",", ""))
    except Exception:
        return None
    if value == 0:
        return None
    if value > 0:
        return round(stake * (value / 100.0), 4)
    return round(stake * (100.0 / abs(value)), 4)


def _row_pnl(row: Mapping[str, Any], outcome: str | None, prediction: Mapping[str, Any]) -> float | None:
    for key in ("pnl", "profit", "profit_u", "payout"):
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            try:
                return round(float(str(value).replace(",", "")), 4)
            except Exception:
                continue

    if outcome not in {"win", "loss", "push", "void"}:
        return None

    stake = 1.0
    stake_value = row.get("stake") or row.get("risk") or row.get("wager")
    if stake_value is not None and str(stake_value).strip() != "":
        try:
            stake = float(str(stake_value).replace(",", ""))
        except Exception:
            stake = 1.0

    if outcome in {"push", "void"}:
        return 0.0

    odds = prediction.get("odds")
    if odds is None:
        odds = row.get("odds") or row.get("price")
    if odds is None:
        return -round(stake, 4) if outcome == "loss" else round(stake, 4)

    profit = _american_profit(odds, stake=stake)
    if profit is None:
        return -round(stake, 4) if outcome == "loss" else round(stake, 4)
    return profit if outcome == "win" else -round(stake, 4)


def _match_result_row(prediction: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    prediction_keys = _prediction_keys(prediction)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_keys = _row_keys(row)
        if prediction_keys and row_keys and prediction_keys.isdisjoint(row_keys):
            continue
        if _normalize_text(row.get("market")) and _normalize_text(prediction.get("market")) and _normalize_text(row.get("market")) != _normalize_text(prediction.get("market")):
            continue
        return row
    return None


def _candidate_result_debug_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        candidates.append(
            {
                "prediction_id": str(row.get("prediction_id") or row.get("id") or "").strip() or None,
                "sport": row.get("sport"),
                "market": row.get("market"),
                "selection": row.get("selection") or row.get("player") or row.get("name"),
                "result": row.get("result") or row.get("outcome") or row.get("grade"),
                "actual": row.get("actual"),
                "line": row.get("line") or row.get("market_line") or row.get("closing_line"),
                "closing_line": row.get("closing_line"),
            }
        )
    return candidates


def reconcile_prediction_results_for_date(
    date_value: str,
    *,
    ledger_path: Path | str | None = None,
    result_roots: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    date_token = str(date_value or "").strip()
    if len(date_token) < 10:
        raise ValueError("date_value must be an ISO date like YYYY-MM-DD")
    date_token = date_token[:10]

    ledger_root = Path(ledger_path) if ledger_path is not None else None
    roots = [Path(root) for root in result_roots] if result_roots is not None else [_repo_root() / "data"]

    predictions = load_all_predictions(ledger_path=ledger_root)
    scoped_predictions = [prediction for prediction in predictions if _prediction_date(prediction) == date_token]
    result_rows = _result_rows_for_date(date_token, roots)

    resolved = 0
    skipped = 0
    result_files = [str(path) for path in _candidate_result_paths(date_token, roots)]
    reconciled_predictions: list[dict[str, Any]] = []

    for prediction in scoped_predictions:
        result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
        if result and _normalize_text(result.get("outcome")) in {"win", "loss", "push", "void"}:
            skipped += 1
            reconciled_predictions.append(dict(prediction))
            continue

        matched_row = _match_result_row(prediction, result_rows)
        if matched_row is None:
            logger.info(
                json.dumps(
                    {
                        "prediction_id": prediction.get("id"),
                        "sport": prediction.get("sport"),
                        "selection": prediction.get("selection"),
                        "market": prediction.get("market"),
                        "reason": "no match found",
                        "candidate_results_checked": _candidate_result_debug_rows(result_rows),
                    },
                    sort_keys=True,
                    default=str,
                )
            )
            skipped += 1
            reconciled_predictions.append(dict(prediction))
            continue

        outcome = _row_outcome(matched_row, prediction)
        if outcome is None:
            skipped += 1
            reconciled_predictions.append(dict(prediction))
            continue

        original_line = _row_original_line(prediction, matched_row)
        closing_line = _row_closing_line(matched_row)
        pnl = _row_pnl(matched_row, outcome, prediction)
        result_payload = record_result(
            prediction_id=prediction.get("id"),
            outcome=outcome,
            original_line=original_line,
            closing_line=closing_line,
            pnl=pnl,
            ledger_path=ledger_root,
        )
        resolved += 1
        reconciled_predictions.append({**dict(prediction), "result": result_payload})

    summary = {
        "date": date_token,
        "predictions": len(scoped_predictions),
        "resolved": resolved,
        "skipped": skipped,
        "result_files": result_files,
    }
    return {
        "ok": True,
        "summary": summary,
        "predictions": reconciled_predictions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile prediction results for a date")
    parser.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--ledger-path", default="", help="Optional ledger path")
    parser.add_argument("--result-root", action="append", default=[], help="Optional result root; repeat to add more")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger_path) if str(args.ledger_path or "").strip() else None
    result_roots = [Path(value) for value in args.result_root] if args.result_root else None
    payload = reconcile_prediction_results_for_date(args.date, ledger_path=ledger_path, result_roots=result_roots)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
