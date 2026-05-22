from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_source_adapter(source_root: Path):
    src_root = (source_root / "src").resolve()
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    from ncaab_model.data.adapters.odds_theoddsapi import TheOddsAPIAdapter

    return TheOddsAPIAdapter


def _target_timezone() -> ZoneInfo | dt.tzinfo:
    try:
        return ZoneInfo("America/Chicago")
    except Exception:
        return dt.timezone.utc


def _event_on_target_date(ct_raw: object, *, target_date: dt.date, tz: ZoneInfo) -> bool:
    if not ct_raw:
        return False
    try:
        if isinstance(ct_raw, str):
            dt_utc = dt.datetime.fromisoformat(ct_raw.replace("Z", "+00:00"))
        elif isinstance(ct_raw, dt.datetime):
            dt_utc = ct_raw
        else:
            return False
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=dt.timezone.utc)
        return dt_utc.astimezone(tz).date() == target_date
    except Exception:
        return False


def _fetch_current_rows(*, adapter, date_iso: str, markets: str, bookmakers: str | None) -> list[dict]:
    mk_l = (markets or "").lower()
    wants_period = any(tok in mk_l for tok in ("_h1", "_h2", "1st_half", "2nd_half", "first_half", "second_half"))
    if not wants_period:
        return [row.model_dump() for row in adapter.iter_current_odds_expanded(markets=markets, date_iso=date_iso, bookmakers=bookmakers)]

    tz = _target_timezone()
    target_date = dt.date.fromisoformat(date_iso)
    event_ids: set[str] = set()

    try:
        for event in adapter.list_events_by_date(date_iso) or []:
            event_id = str((event or {}).get("id") or "").strip()
            commence_time = (event or {}).get("commence_time")
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    try:
        for row in adapter.iter_current_odds_expanded(markets="h2h", date_iso=date_iso, bookmakers=bookmakers):
            event_id = str(getattr(row, "event_id", "") or "").strip()
            commence_time = getattr(row, "commence_time", None)
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    if event_ids:
        rows: list[dict] = []
        for event_id in sorted(event_ids):
            rows.extend(row.model_dump() for row in adapter.iter_event_odds(event_id, markets=markets, bookmakers=bookmakers))
        if rows:
            return rows

    return [row.model_dump() for row in adapter.iter_current_odds_expanded(markets=markets, date_iso=date_iso, bookmakers=bookmakers)]


def _discover_event_ids(*, adapter, date_iso: str) -> list[str]:
    tz = _target_timezone()
    target_date = dt.date.fromisoformat(date_iso)
    event_ids: set[str] = set()

    try:
        for event in adapter.list_events_by_date(date_iso) or []:
            event_id = str((event or {}).get("id") or "").strip()
            commence_time = (event or {}).get("commence_time")
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    try:
        for row in adapter.iter_current_odds_expanded(markets="h2h", date_iso=date_iso, bookmakers=None):
            event_id = str(getattr(row, "event_id", "") or "").strip()
            commence_time = getattr(row, "commence_time", None)
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    return sorted(event_ids)


def _fetch_history_rows(*, adapter, date_iso: str, markets: str, bookmakers: str | None) -> list[dict]:
    event_ids = _discover_event_ids(adapter=adapter, date_iso=date_iso)
    return [
        row.model_dump()
        for row in adapter.iter_odds_history_for_events(event_ids, markets=markets, bookmakers=bookmakers)
    ]


def _write_rows(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError(f"No odds rows returned for {out_path.stem}.")
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(str(key))
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NCAAB odds history through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--region", default="us")
    parser.add_argument("--bookmakers")
    parser.add_argument("--markets", default="h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", default="current", choices=("current", "history"))
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    date_iso = str(args.date).strip()
    TheOddsAPIAdapter = _load_source_adapter(source_root)
    adapter = TheOddsAPIAdapter(region=str(args.region or "us"))

    if args.mode == "history":
        rows = _fetch_history_rows(adapter=adapter, date_iso=date_iso, markets=str(args.markets or ""), bookmakers=args.bookmakers)
    else:
        rows = _fetch_current_rows(adapter=adapter, date_iso=date_iso, markets=str(args.markets or ""), bookmakers=args.bookmakers)

    out_path = out_dir / f"odds_{date_iso}.csv"
    _write_rows(out_path, rows)
    print(f"Wrote {len(rows)} odds rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())