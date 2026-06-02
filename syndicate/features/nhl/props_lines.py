from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.nhl.sources import default_date
from syndicate.features.nhl.sources import default_nhl_data_root


def _lines_root() -> Path:
    return default_nhl_data_root() / "props" / "player_props_lines"


def _date_path(date_str: str) -> Path:
    return _lines_root() / f"date={date_str}" / "oddsapi.csv"


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


def _selected_date(query_string: str) -> str:
    params = parse_qs(query_string or "", keep_blank_values=True)
    return str((params.get("date") or [""])[0]).strip() or default_date()


def _selected_market(query_string: str) -> str | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    value = str((params.get("market") or [""])[0]).strip().upper()
    return value or None


def _selected_player(query_string: str) -> str | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    value = str((params.get("player") or [""])[0]).strip().lower()
    return value or None


def _normalize_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        "date": str(row.get("date") or "").strip(),
        "player": str(row.get("player_name") or row.get("player") or "").strip(),
        "player_id": str(row.get("player_id") or "").strip() or None,
        "team": str(row.get("team") or "").strip(),
        "market": str(row.get("market") or "").strip().upper(),
        "line": _safe_float(row.get("line")),
        "over_price": _safe_float(row.get("over_price")),
        "under_price": _safe_float(row.get("under_price")),
        "book": str(row.get("book") or "").strip(),
        "first_seen_at": str(row.get("first_seen_at") or "").strip() or None,
        "last_seen_at": str(row.get("last_seen_at") or "").strip() or None,
        "is_current": str(row.get("is_current") or "").strip(),
    }


@lru_cache(maxsize=256)
def build_props_lines_payload(query_string: str) -> dict[str, Any] | None:
    date_str = _selected_date(query_string)
    market = _selected_market(query_string)
    player = _selected_player(query_string)
    rows = [_normalize_row(row) for row in _read_rows(_date_path(date_str))]
    if market:
        rows = [row for row in rows if str(row.get("market") or "").upper() == market]
    if player:
        rows = [row for row in rows if str(row.get("player") or "").strip().lower() == player]
    markets = sorted({str(row.get("market") or "") for row in rows if str(row.get("market") or "")})
    players = sorted({str(row.get("player") or "") for row in rows if str(row.get("player") or "")})
    rows.sort(key=lambda row: (str(row.get("market") or ""), str(row.get("player") or ""), float(row.get("line") or 0.0)))
    return {
        "ok": True,
        "version": "props-lines-v1",
        "date": date_str,
        "markets": markets,
        "players": players[:500],
        "data": rows,
        "total_rows": len(rows),
    }