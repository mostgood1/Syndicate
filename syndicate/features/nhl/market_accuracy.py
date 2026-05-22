from __future__ import annotations

import csv
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.nhl.sources import processed_path
from syndicate.features.shared.live_lens_local import build_empty_market_accuracy_payload
from syndicate.features.shared.live_lens_local import build_local_market_accuracy_payload


def _artifact_root():
    return processed_path("predictions_2099-01-01.csv").parent


def _source_window(payload: dict[str, Any]) -> dict[str, str | None]:
    start = payload.get("requested_start") or payload.get("start") or payload.get("effective_date") or payload.get("requested_date") or payload.get("date")
    end = payload.get("requested_end") or payload.get("end") or payload.get("effective_date") or payload.get("requested_date") or payload.get("date")
    return {
        "since": str(start).strip() if start else None,
        "until": str(end).strip() if end else None,
    }


def _normalize_source_bucket(bucket: Any) -> dict[str, Any]:
    if not isinstance(bucket, dict):
        return _finalize_bucket(_init_bucket())
    wins = int(bucket.get("wins") or 0)
    losses = int(bucket.get("losses") or 0)
    pushes = int(bucket.get("pushes") or 0)
    bets = int(bucket.get("bets") or 0)
    resolved = wins + losses + pushes
    accuracy = bucket.get("win_rate")
    roi = bucket.get("roi")
    profit_total = _safe_float(bucket.get("units"))
    return {
        "bets": bets,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "stake_total": None,
        "profit_total": profit_total,
        "accuracy": accuracy,
        "accuracy_pct": (round(float(accuracy) * 100.0, 3) if accuracy is not None else None),
        "roi": roi,
        "roi_pct": (round(float(roi) * 100.0, 3) if roi is not None else None),
    }


def _by_date_index(section: Any) -> dict[str, dict[str, Any]]:
    rows = section.get("by_date") if isinstance(section, dict) and isinstance(section.get("by_date"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("date") or "").strip()
        if key:
            out[key] = row
    return out


def _normalize_source_market_accuracy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("version") == "accuracy-market-v1" and isinstance(payload.get("days"), list):
        return payload

    games_section = payload.get("games") if isinstance(payload.get("games"), dict) else {}
    props_section = payload.get("props") if isinstance(payload.get("props"), dict) else {}
    combined_section = payload.get("combined") if isinstance(payload.get("combined"), dict) else {}
    games_by_date = _by_date_index(games_section)
    props_by_date = _by_date_index(props_section)
    combined_by_date = _by_date_index(combined_section)
    ordered_dates = sorted(set(games_by_date) | set(props_by_date) | set(combined_by_date))

    days: list[dict[str, Any]] = []
    for date_str in ordered_dates:
        game_row = games_by_date.get(date_str)
        props_row = props_by_date.get(date_str)
        combined_row = combined_by_date.get(date_str)
        days.append(
            {
                "date": date_str,
                "games": {
                    "available": isinstance(game_row, dict),
                    "overall": _normalize_source_bucket(game_row),
                    "by_market": {},
                },
                "props": {
                    "available": isinstance(props_row, dict),
                    "overall": _normalize_source_bucket(props_row),
                    "by_market": {},
                },
                "combined": {
                    "available": isinstance(combined_row, dict),
                    "overall": _normalize_source_bucket(combined_row),
                },
            }
        )

    normalized = dict(payload)
    normalized["version"] = "accuracy-market-v1"
    normalized["window"] = _source_window(payload)
    normalized["days"] = days
    normalized["summary"] = {
        "games": {
            "available": bool(games_section.get("rows") or games_section.get("rows_total") or games_section.get("summary")),
            "overall": _normalize_source_bucket(games_section.get("summary")),
        },
        "props": {
            "available": bool(props_section.get("rows") or props_section.get("rows_total") or props_section.get("summary")),
            "overall": _normalize_source_bucket(props_section.get("summary")),
        },
        "combined": {
            "available": bool(combined_section.get("rows") or combined_section.get("rows_total") or combined_section.get("summary")),
            "overall": _normalize_source_bucket(combined_section.get("summary")),
        },
    }
    normalized.setdefault(
        "generated_at",
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    return normalized


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _parse_ymd(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except Exception:
        return None


def _date_window(query_string: str, *, default_days: int = 30) -> list[str]:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_value = str((params.get("date") or [""])[0]).strip()
    if date_value:
        return [date_value]
    start_value = str((params.get("since") or params.get("start") or [""])[0]).strip()
    end_value = str((params.get("until") or params.get("end") or [""])[0]).strip()
    if start_value and end_value:
        start_dt = _parse_ymd(start_value)
        end_dt = _parse_ymd(end_value)
        if start_dt is None or end_dt is None:
            return []
    else:
        try:
            days = max(1, min(120, int(float(str((params.get("days") or [str(default_days)])[0]).strip()))))
        except Exception:
            days = default_days
        end_dt = datetime.utcnow() - timedelta(days=1)
        start_dt = end_dt - timedelta(days=days - 1)
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    dates: list[str] = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def _init_bucket() -> dict[str, Any]:
    return {
        "bets": 0,
        "resolved": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "stake_total": 0.0,
        "profit_total": 0.0,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    resolved = int(bucket.get("resolved") or 0)
    wins = int(bucket.get("wins") or 0)
    stake_total = float(bucket.get("stake_total") or 0.0)
    profit_total = float(bucket.get("profit_total") or 0.0)
    accuracy = (float(wins) / float(resolved)) if resolved > 0 else None
    roi = (profit_total / stake_total) if stake_total > 0 else None
    payload = dict(bucket)
    payload["accuracy"] = accuracy
    payload["accuracy_pct"] = (round(100.0 * accuracy, 3) if accuracy is not None else None)
    payload["roi"] = roi
    payload["roi_pct"] = (round(100.0 * roi, 3) if roi is not None else None)
    return payload


def _apply_row(bucket: dict[str, Any], row: dict[str, str]) -> None:
    bucket["bets"] += 1
    result = str(row.get("result") or "").strip().lower()
    if result not in {"win", "loss", "push"}:
        return
    bucket["resolved"] += 1
    if result == "win":
        bucket["wins"] += 1
    elif result == "loss":
        bucket["losses"] += 1
    else:
        bucket["pushes"] += 1
    stake = _safe_float(row.get("stake"))
    profit = _safe_float(row.get("payout"))
    if stake is not None:
        bucket["stake_total"] += float(stake)
    if profit is not None:
        bucket["profit_total"] += float(profit)


def _section_from_logs(rows: list[dict[str, str]], date_str: str) -> dict[str, Any]:
    selected_rows = [row for row in rows if str(row.get("date") or "")[:10] == date_str]
    if not selected_rows:
        return {"available": False}
    overall = _init_bucket()
    by_market: dict[str, dict[str, Any]] = {}
    for row in selected_rows:
        market = str(row.get("market") or "").strip().upper() or "UNKNOWN"
        by_market.setdefault(market, _init_bucket())
        _apply_row(overall, row)
        _apply_row(by_market[market], row)
    return {
        "available": True,
        "overall": _finalize_bucket(overall),
        "by_market": {key: _finalize_bucket(bucket) for key, bucket in by_market.items()},
    }


def _build_local_log_accuracy_payload(query_string: str, artifact_root: Path) -> dict[str, Any] | None:
    date_list = _date_window(query_string, default_days=30)
    if not date_list:
        return None
    games_rows = _read_csv_rows(artifact_root / "reconciliations_log.csv")
    props_rows = _read_csv_rows(artifact_root / "props_reconciliations_log.csv")
    if not games_rows and not props_rows:
        return None

    any_available = False
    days: list[dict[str, Any]] = []
    games_total = _init_bucket()
    props_total = _init_bucket()
    for date_str in date_list:
        games = _section_from_logs(games_rows, date_str)
        props = _section_from_logs(props_rows, date_str)
        for source_section, total_bucket in ((games, games_total), (props, props_total)):
            overall = source_section.get("overall") if isinstance(source_section, dict) else None
            if isinstance(overall, dict):
                any_available = True
                for key in total_bucket.keys():
                    total_bucket[key] += float(overall.get(key) or 0.0) if key in {"stake_total", "profit_total"} else int(overall.get(key) or 0)
        combined = _init_bucket()
        for source_section in (games, props):
            overall = source_section.get("overall") if isinstance(source_section, dict) else None
            if not isinstance(overall, dict):
                continue
            for key in combined.keys():
                combined[key] += float(overall.get(key) or 0.0) if key in {"stake_total", "profit_total"} else int(overall.get(key) or 0)
        days.append(
            {
                "date": date_str,
                "games": games,
                "props": props,
                "combined": {
                    "available": bool((games.get("available") if isinstance(games, dict) else False) or (props.get("available") if isinstance(props, dict) else False)),
                    "overall": _finalize_bucket(combined),
                },
            }
        )

    if not any_available:
        return None

    combined_total = _init_bucket()
    for key in combined_total.keys():
        combined_total[key] = games_total[key] + props_total[key]

    return {
        "ok": True,
        "version": "accuracy-market-v1",
        "window": {"since": date_list[0], "until": date_list[-1]},
        "days": days,
        "summary": {
            "games": {"available": True, "overall": _finalize_bucket(games_total)},
            "props": {"available": True, "overall": _finalize_bucket(props_total)},
            "combined": {"available": True, "overall": _finalize_bucket(combined_total)},
        },
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


@lru_cache(maxsize=256)
def build_market_accuracy_payload(query_string: str) -> dict[str, Any] | None:
    local_payload = build_local_market_accuracy_payload(query_string, _artifact_root())
    if isinstance(local_payload, dict):
        return local_payload
    log_payload = _build_local_log_accuracy_payload(query_string, _artifact_root())
    if isinstance(log_payload, dict):
        return log_payload
    return build_empty_market_accuracy_payload(query_string)