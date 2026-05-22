from __future__ import annotations

import csv
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.nhl.sources import processed_path


def _artifact_root() -> Path:
    return processed_path("predictions_2099-01-01.csv").parent


def _read_rows(path: Path) -> list[dict[str, str]]:
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
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
    except Exception:
        return None


def _row_date(row: dict[str, str]) -> str | None:
    raw_value = str(row.get("date") or "").strip()
    parsed = _parse_ymd(raw_value)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else None


def _settled_result(row: dict[str, str]) -> str | None:
    result = str(row.get("result") or "").strip().lower()
    return result if result in {"win", "loss", "push"} else None


def _tier_name(ev_value: float | None) -> str:
    if ev_value is None:
        return "Low"
    if ev_value >= 0.10:
        return "High"
    if ev_value >= 0.05:
        return "Medium"
    return "Low"


def _empty_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "resolved": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "stake_total": 0.0,
        "profit_total": 0.0,
        "accuracy_pct": None,
        "roi_pct": None,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    resolved = int(bucket.get("resolved") or 0)
    wins = int(bucket.get("wins") or 0)
    stake_total = float(bucket.get("stake_total") or 0.0)
    profit_total = float(bucket.get("profit_total") or 0.0)
    accuracy_pct = (100.0 * wins / resolved) if resolved > 0 else None
    roi_pct = (100.0 * profit_total / stake_total) if stake_total > 0 else None
    return {
        **bucket,
        "accuracy_pct": round(accuracy_pct, 3) if accuracy_pct is not None else None,
        "roi_pct": round(roi_pct, 3) if roi_pct is not None else None,
    }


def _date_window(query_string: str, available_dates: list[str]) -> tuple[str, str]:
    params = parse_qs(query_string or "", keep_blank_values=True)
    selected_date = str((params.get("date") or [""])[0]).strip()
    if selected_date:
        return selected_date, selected_date

    since = str((params.get("since") or params.get("start") or [""])[0]).strip()
    until = str((params.get("until") or params.get("end") or [""])[0]).strip()
    if since and until:
        return since, until
    if since and not until:
        return since, since
    if until and not since:
        return until, until

    try:
        days = max(1, min(90, int(float(str((params.get("days") or ["14"])[0]).strip()))))
    except Exception:
        days = 14
    anchor = available_dates[-1] if available_dates else datetime.utcnow().strftime("%Y-%m-%d")
    anchor_dt = _parse_ymd(anchor) or datetime.utcnow()
    since_dt = anchor_dt - timedelta(days=days - 1)
    return since_dt.strftime("%Y-%m-%d"), anchor_dt.strftime("%Y-%m-%d")


def _iter_window_dates(since: str, until: str) -> list[str]:
    since_dt = _parse_ymd(since)
    until_dt = _parse_ymd(until)
    if since_dt is None or until_dt is None:
        return []
    if until_dt < since_dt:
        since_dt, until_dt = until_dt, since_dt
    current = since_dt
    out: list[str] = []
    while current <= until_dt:
        out.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return out


def _section_for_date(rows: list[dict[str, str]], date_str: str) -> dict[str, Any]:
    buckets = {name: _empty_bucket() for name in ("Overall", "High", "Medium", "Low")}
    matching_rows = [row for row in rows if _row_date(row) == date_str]
    for row in matching_rows:
        ev_value = _safe_float(row.get("ev"))
        tier = _tier_name(ev_value)
        for bucket_name in ("Overall", tier):
            buckets[bucket_name]["total"] += 1
            settled = _settled_result(row)
            if settled is None:
                continue
            buckets[bucket_name]["resolved"] += 1
            if settled == "win":
                buckets[bucket_name]["wins"] += 1
            elif settled == "loss":
                buckets[bucket_name]["losses"] += 1
            else:
                buckets[bucket_name]["pushes"] += 1
            stake = _safe_float(row.get("stake"))
            payout = _safe_float(row.get("payout"))
            if stake is not None:
                buckets[bucket_name]["stake_total"] += stake
            if payout is not None:
                buckets[bucket_name]["profit_total"] += payout
    return {
        "rows": len(matching_rows),
        "buckets": {name: _finalize_bucket(bucket) for name, bucket in buckets.items()},
    }


def _aggregate_sections(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    buckets = {name: _empty_bucket() for name in ("Overall", "High", "Medium", "Low")}
    for item in items:
        section = item.get(key) if isinstance(item, dict) else None
        section_buckets = section.get("buckets") if isinstance(section, dict) else None
        if not isinstance(section_buckets, dict):
            continue
        for name, bucket in section_buckets.items():
            if name not in buckets or not isinstance(bucket, dict):
                continue
            for field in ("total", "resolved", "wins", "losses", "pushes"):
                buckets[name][field] += int(bucket.get(field) or 0)
            for field in ("stake_total", "profit_total"):
                buckets[name][field] += float(bucket.get(field) or 0.0)
    return {"buckets": {name: _finalize_bucket(bucket) for name, bucket in buckets.items()}}


@lru_cache(maxsize=256)
def build_betting_recap_payload(query_string: str) -> dict[str, Any] | None:
    artifact_root = _artifact_root()
    game_rows = _read_rows(artifact_root / "reconciliations_log.csv")
    prop_rows = _read_rows(artifact_root / "props_reconciliations_log.csv")
    all_dates = sorted(
        {
            *[date_str for date_str in (_row_date(row) for row in game_rows) if date_str],
            *[date_str for date_str in (_row_date(row) for row in prop_rows) if date_str],
        }
    )
    since, until = _date_window(query_string, all_dates)
    window_dates = _iter_window_dates(since, until)
    items = []
    for date_str in window_dates:
        games = _section_for_date(game_rows, date_str)
        props = _section_for_date(prop_rows, date_str)
        if not any((games["rows"], props["rows"])):
            continue
        items.append({
            "date": date_str,
            "games": games,
            "props": props,
        })
    return {
        "ok": True,
        "version": "recaps-v1",
        "window": {"since": since, "until": until},
        "items": sorted(items, key=lambda item: str(item.get("date") or ""), reverse=True),
        "summary": {
            "games": _aggregate_sections(items, "games"),
            "props": _aggregate_sections(items, "props"),
        },
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }