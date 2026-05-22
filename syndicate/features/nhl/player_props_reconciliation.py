from __future__ import annotations

import csv
from datetime import datetime
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


def _row_date(row: dict[str, str]) -> str | None:
    raw_value = str(row.get("date") or "").strip()
    if len(raw_value) >= 10:
        token = raw_value[:10]
        try:
            datetime.strptime(token, "%Y-%m-%d")
            return token
        except Exception:
            return None
    return None


def _row_result(row: dict[str, str]) -> str | None:
    result = str(row.get("result") or "").strip().lower()
    return result if result in {"win", "loss", "push"} else None


def _selected_date(query_string: str, rows: list[dict[str, str]]) -> tuple[str | None, str | None, str | None]:
    params = parse_qs(query_string or "", keep_blank_values=True)
    requested_date = str((params.get("date") or [""])[0]).strip() or None
    latest_available = max((date_str for date_str in (_row_date(row) for row in rows) if date_str), default=None)
    return requested_date or latest_available, requested_date, latest_available


def _selected_market(query_string: str) -> str | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    market = str((params.get("market") or [""])[0]).strip().upper()
    return market or None


@lru_cache(maxsize=256)
def build_player_props_reconciliation_payload(query_string: str) -> dict[str, Any] | None:
    rows = _read_rows(_artifact_root() / "props_reconciliations_log.csv")
    selected_date, requested_date, latest_available = _selected_date(query_string, rows)
    selected_market = _selected_market(query_string)
    if not selected_date:
        return {
            "ok": True,
            "version": "player-props-reconciliation-v1",
            "date": None,
            "requested_date": requested_date,
            "latest_available_date": latest_available,
            "summary": {"total": 0, "settled": 0, "wins": 0, "losses": 0, "pushes": 0, "profit_total": 0.0, "roi_pct": None, "avg_ev": None},
            "markets": [],
            "data": [],
        }

    filtered = [row for row in rows if _row_date(row) == selected_date]
    if selected_market:
        filtered = [row for row in filtered if str(row.get("market") or "").strip().upper() == selected_market]

    normalized_rows: list[dict[str, Any]] = []
    wins = losses = pushes = settled = 0
    profit_total = 0.0
    stake_total = 0.0
    ev_values: list[float] = []
    markets: set[str] = set()
    for row in filtered:
        result = _row_result(row)
        if result is not None:
            settled += 1
            if result == "win":
                wins += 1
            elif result == "loss":
                losses += 1
            else:
                pushes += 1
        payout = _safe_float(row.get("payout"))
        stake = _safe_float(row.get("stake"))
        ev_value = _safe_float(row.get("ev"))
        line = _safe_float(row.get("line"))
        actual = _safe_float(row.get("actual"))
        odds = _safe_float(row.get("odds"))
        if payout is not None:
            profit_total += payout
        if stake is not None:
            stake_total += stake
        if ev_value is not None:
            ev_values.append(ev_value)
        market = str(row.get("market") or "").strip().upper()
        if market:
            markets.add(market)
        normalized_rows.append(
            {
                "date": selected_date,
                "market": market,
                "player": str(row.get("player") or "").strip(),
                "line": line,
                "side": str(row.get("side") or "").strip().upper(),
                "odds": odds,
                "ev": ev_value,
                "actual": actual,
                "result": result,
                "stake": stake,
                "payout": payout,
            }
        )
    normalized_rows.sort(
        key=lambda row: (
            0 if row.get("result") in {"win", "loss", "push"} else 1,
            -float(row.get("ev") or -9999.0),
            str(row.get("player") or ""),
        )
    )
    roi_pct = (100.0 * profit_total / stake_total) if stake_total > 0 else None
    avg_ev = (sum(ev_values) / len(ev_values)) if ev_values else None
    return {
        "ok": True,
        "version": "player-props-reconciliation-v1",
        "date": selected_date,
        "requested_date": requested_date,
        "latest_available_date": latest_available,
        "selected_market": selected_market,
        "summary": {
            "total": len(normalized_rows),
            "settled": settled,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "profit_total": profit_total,
            "roi_pct": round(roi_pct, 3) if roi_pct is not None else None,
            "avg_ev": round(avg_ev, 4) if avg_ev is not None else None,
        },
        "markets": sorted(markets),
        "data": normalized_rows,
    }