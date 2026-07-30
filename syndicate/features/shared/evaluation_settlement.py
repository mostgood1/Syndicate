"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Settles pending syndicate.features.shared.intelligence_evaluation ledger
  records (recommendations shown by intelligence queries) against each
  sport's own already-graded market-accuracy rows, so downstream calibration
  (adjust_confidence/build_reliability_profile) and policy promotion
  (recommendation_engine.compare_policies) receive real settled data instead
  of a permanently-empty ledger.

Constraints:
- State-driven execution
- Avoid redundant computation
- Read-only against each sport's own market-accuracy artifacts; this module
  never recomputes a settlement join that a sport's own module already does.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path
from syndicate.features.shared.intelligence_evaluation import _record_sport
from syndicate.features.shared.intelligence_evaluation import settle_result


_SUPPORTED_SPORTS = ("mlb", "wnba")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _market_family(value: Any) -> str | None:
    """Bucket a raw market label into a coarse family, mirroring
    intelligence_evaluation._record_market_family's keyword rules, so
    naming variance between the ledger's free-form `market` field and each
    sport's own market-accuracy labels ("totals" vs "total", "ml" vs
    "moneyline") doesn't block an otherwise-correct match.
    """
    market = str(value or "").strip().lower()
    if not market:
        return None
    if any(token in market for token in ("prop", "player", "point", "rebound", "assist", "steal", "block", "shot", "hitter", "pitcher")):
        return "props"
    if any(token in market for token in ("moneyline", "ml", "money line")):
        return "moneyline"
    if any(token in market for token in ("spread", "ats", "spreads")):
        return "spread"
    if any(token in market for token in ("total", "over", "under", "o/u")):
        return "totals"
    return market


def _read_chunk_records(chunk_path: Path) -> list[dict[str, Any]]:
    if not chunk_path.exists():
        return []
    try:
        content = chunk_path.read_text(encoding="utf-8")
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _mlb_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.mlb.market_accuracy import build_market_accuracy_payload

    try:
        payload = build_market_accuracy_payload(f"date={date_str}")
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for day in payload.get("days") or []:
        if not isinstance(day, dict) or str(day.get("date") or "") != date_str:
            continue
        by_kind = day.get("rows") if isinstance(day.get("rows"), dict) else {}
        kind_rows = by_kind.get("official") or by_kind.get("playable") or by_kind.get("all") or []
        for row in kind_rows:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": "mlb",
                    "market": row.get("market"),
                    "selection": row.get("selection"),
                    "player": row.get("player_name"),
                    "team": row.get("team"),
                    "title": row.get("title"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("odds"),
                    "result": result,
                    "pnl": row.get("profit_u"),
                }
            )
    return rows


def _wnba_graded_rows_for_date(date_str: str) -> list[dict[str, Any]]:
    from syndicate.features.shared.live_lens_local import build_local_market_accuracy_payload
    from syndicate.features.wnba.sources import processed_root

    try:
        payload = build_local_market_accuracy_payload(f"date={date_str}", processed_root())
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for day in payload.get("days") or []:
        if not isinstance(day, dict) or str(day.get("date") or "") != date_str:
            continue
        games = day.get("games") if isinstance(day.get("games"), dict) else {}
        for row in games.get("rows") or []:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": "wnba",
                    "market": row.get("market"),
                    "selection": row.get("side"),
                    "home": row.get("home"),
                    "away": row.get("away"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("price"),
                    "result": result,
                }
            )
        props = day.get("props") if isinstance(day.get("props"), dict) else {}
        for row in props.get("rows") or []:
            if not isinstance(row, dict):
                continue
            result = str(row.get("result") or "").strip().lower()
            if result not in {"win", "loss", "push", "void"}:
                continue
            rows.append(
                {
                    "sport": "wnba",
                    "market": row.get("market"),
                    "selection": row.get("side"),
                    "player": row.get("player"),
                    "team": row.get("team"),
                    "line": row.get("line"),
                    "actual": row.get("actual"),
                    "odds": row.get("price"),
                    "result": result,
                }
            )
    return rows


def _graded_rows_for_date(sport: str, date_str: str) -> list[dict[str, Any]]:
    sport_slug = str(sport or "").strip().lower()
    if sport_slug == "mlb":
        return _mlb_graded_rows_for_date(date_str)
    if sport_slug == "wnba":
        return _wnba_graded_rows_for_date(date_str)
    return []


def _evaluation_record_keys(record: Mapping[str, Any]) -> set[str]:
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    keys = {
        _normalize_text(recommendation.get("market") or recommendation.get("market_family")),
        _normalize_text(recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name")),
    }
    for key in ("event_id", "game_id", "player", "player_name", "team", "name", "home", "away"):
        keys.add(_normalize_text(recommendation.get(key)))
    return {item for item in keys if item}


def _graded_row_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {
        _normalize_text(row.get("selection")),
        _normalize_text(row.get("player")),
        _normalize_text(row.get("team")),
        _normalize_text(row.get("home")),
        _normalize_text(row.get("away")),
        _normalize_text(row.get("title")),
    }
    return {item for item in keys if item}


def _record_line(record: Mapping[str, Any]) -> float | None:
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    value = recommendation.get("line") or recommendation.get("projected")
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def match_graded_row(record: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Loose "shared normalized token" match, mirroring
    prediction_reconciliation._match_result_row: first row whose key-set
    overlaps the record's and whose market agrees (when both sides have one)
    wins. Not a scored/best-match search -- same known limitation as the
    reconciliation module this mirrors.
    """
    record_keys = _evaluation_record_keys(record)
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    record_market_family = _market_family(recommendation.get("market") or recommendation.get("market_family"))
    record_line = _record_line(record)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_keys = _graded_row_keys(row)
        if record_keys and row_keys and record_keys.isdisjoint(row_keys):
            continue
        row_market_family = _market_family(row.get("market"))
        if row_market_family and record_market_family and row_market_family != record_market_family:
            continue
        if record_line is not None and row.get("line") is not None:
            try:
                if abs(record_line - float(row.get("line"))) > 1e-6:
                    continue
            except Exception:
                pass
        return row
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


def _pnl_for_settlement(row: Mapping[str, Any], result: str) -> float:
    if row.get("pnl") is not None:
        try:
            return round(float(row.get("pnl")), 4)
        except Exception:
            pass
    if result in {"push", "void"}:
        return 0.0
    profit = _american_profit(row.get("odds"))
    if profit is None:
        return 1.0 if result == "win" else -1.0
    return profit if result == "win" else -1.0


def settle_ledger_for_date(
    date_value: str,
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    date_token = str(date_value or "").strip()[:10]
    if len(date_token) != 10 or date_token[4] != "-" or date_token[7] != "-":
        raise ValueError("date_value must be an ISO date like YYYY-MM-DD")

    sport_slug = str(sport or "").strip().lower() or None
    if sport_slug and sport_slug not in _SUPPORTED_SPORTS:
        return {
            "ok": True,
            "date": date_token,
            "sport": sport_slug,
            "pending": 0,
            "matched": 0,
            "settled": 0,
            "unmatched": 0,
            "note": f"sport '{sport_slug}' is not yet supported by evaluation_settlement",
        }

    target_ledger_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    chunk_path = _ledger_chunk_path(target_ledger_path, date_token)
    records = _read_chunk_records(chunk_path)

    pending_records = [
        record
        for record in records
        if str(record.get("record_type") or "").strip().lower() == "recommendation"
        and str(record.get("result") or "pending").strip().lower() == "pending"
        and (sport_slug is None or _record_sport(record) == sport_slug)
    ]

    graded_rows_by_sport: dict[str, list[dict[str, Any]]] = {}
    matched = 0
    settled = 0
    unmatched = 0

    for record in pending_records:
        record_sport = _record_sport(record) or sport_slug
        if not record_sport or record_sport not in _SUPPORTED_SPORTS:
            unmatched += 1
            continue
        if record_sport not in graded_rows_by_sport:
            graded_rows_by_sport[record_sport] = _graded_rows_for_date(record_sport, date_token)
        candidate_rows = graded_rows_by_sport[record_sport]
        if not candidate_rows:
            unmatched += 1
            continue
        row = match_graded_row(record, candidate_rows)
        if row is None:
            unmatched += 1
            continue
        matched += 1
        result = str(row.get("result") or "").strip().lower()
        if result not in {"win", "loss", "push", "void"}:
            unmatched += 1
            matched -= 1
            continue
        if dry_run:
            settled += 1
            continue
        recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
        settle_result(
            record=record,
            result=result,
            pnl=_pnl_for_settlement(row, result),
            closing_line=row.get("line"),
            implied_probability=recommendation.get("model_probability") or record.get("implied_probability"),
            persist=True,
            ledger_path=target_ledger_path,
        )
        settled += 1

    return {
        "ok": True,
        "date": date_token,
        "sport": sport_slug,
        "pending": len(pending_records),
        "matched": matched,
        "settled": settled if not dry_run else 0,
        "would_settle": settled if dry_run else None,
        "unmatched": unmatched,
        "dry_run": dry_run,
    }


def settle_ledger_for_dates(
    dates: Sequence[str],
    *,
    sports: Sequence[str] | None = None,
    ledger_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    sport_list = list(sports) if sports else [None]
    results: list[dict[str, Any]] = []
    for date_value in dates:
        for sport in sport_list:
            results.append(
                settle_ledger_for_date(date_value, sport=sport, ledger_path=ledger_path, dry_run=dry_run)
            )
    return {
        "ok": True,
        "results": results,
        "totals": {
            "pending": sum(int(r.get("pending") or 0) for r in results),
            "matched": sum(int(r.get("matched") or 0) for r in results),
            "settled": sum(int(r.get("settled") or 0) for r in results),
            "unmatched": sum(int(r.get("unmatched") or 0) for r in results),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Settle pending evaluation-ledger records for a date")
    parser.add_argument("--date", required=True, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--sport", action="append", default=[], help="Sport slug to scope settlement to (repeat for multiple); default: all supported sports")
    parser.add_argument("--ledger-path", default="", help="Optional ledger path override")
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing settled results")
    args = parser.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger_path) if str(args.ledger_path or "").strip() else None
    sports = list(args.sport) if args.sport else None
    payload = settle_ledger_for_dates([args.date], sports=sports, ledger_path=ledger_path, dry_run=bool(args.dry_run))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
