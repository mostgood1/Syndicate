#!/usr/bin/env python3
"""Rebuild `oddsapi_player_props_<season>_wk<week>.csv` from the book_quotes log.

WHY THIS EXISTS. `backfill_nfl_historical_props.py` buys a pre-kickoff snapshot per
game and writes BOTH a per-week CSV and the shared quote log. The two can diverge: on
2026-10-03 the checkpoint recorded 105 done events for 2025 wk10-18 with 13,679 rows
and `tracking/book_quotes/2025_wk1{0..8}.jsonl` held ~74,800 book rows, while the CSVs
were 6-byte `team\\r\\n` stubs unchanged since the initial import. The snapshots were
PAID FOR and present; only the derived CSVs were missing.

Re-running the backfill does not fix that: `done_events` is keyed on event id, so every
event is skipped as "already done" and the run spends only its phase-A window calls. A
re-fetch would mean buying the same snapshots twice -- ~12,330 credits for nine weeks of
NFL. This rebuilds the CSVs from the log instead, for nothing.

IMPORTANT: THE QUOTE LOG IS GITIGNORED (`.gitignore`: `data/nfl_source/tracking/`), so
it exists only on the machine that fetched it, while the CSVs ARE tracked. The CSVs are
therefore the only persistable form of this data -- rebuild and COMMIT them rather than
leaving the recovery on one disk.

FAITHFULNESS. The row shape is not reimplemented. This reproduces
`backfill_nfl_historical_props.rows_from_event`'s grouping -- one row per
(player, market, line), best price per side via `_better` (max American odds), the first
book that created the row -- and writes through that module's own `write_week_csv`, so
schema, sort order and the atomic write are production's.

SNAPSHOT DISCIPLINE. The backfill takes ONE snapshot per game. If a log holds more than
one snapshot for an event, collapsing all of them would mix capture times, so only the
LAST `snapshot_ts` per event is kept and the count of events where that mattered is
reported.

Usage:
    py -3 scripts/rebuild_nfl_prop_csv_from_quotes.py --season 2025 --weeks 10-18
    py -3 scripts/rebuild_nfl_prop_csv_from_quotes.py --season 2025 --weeks 10,11,12 --dry-run
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OVER_SIDES = {"over", "yes"}


def _parse_weeks(raw: str) -> list[int]:
    out: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def rebuild_week(bf: Any, source_root: Path, season: int, week: int, *, dry_run: bool) -> dict[str, Any]:
    log = source_root / "tracking" / "book_quotes" / f"{season}_wk{week}.jsonl"
    if not log.is_file():
        return {"week": week, "error": "quote log missing"}

    raw: list[dict[str, Any]] = []
    snaps: dict[str, set[str]] = collections.defaultdict(set)
    with log.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("sport") != "nfl" or row.get("kind") != "prop":
                continue
            if str(row.get("segment") or "full") != "full":
                continue
            raw.append(row)
            snaps[str(row.get("event_id") or "")].add(str(row.get("snapshot_ts") or ""))

    multi = sum(1 for values in snaps.values() if len(values) > 1)
    keep = {event: max(values) for event, values in snaps.items()}
    kept = [r for r in raw if str(r.get("snapshot_ts") or "") == keep.get(str(r.get("event_id") or ""))]

    best: dict[tuple[str, str, float | None], dict[str, Any]] = {}
    for row in kept:
        player = str(row.get("player_name") or "").strip()
        market = str(row.get("market") or "").strip()
        if not player or not market:
            continue
        point = row.get("line")
        try:
            line = float(point) if point is not None and str(point) != "" else None
        except Exception:
            line = None
        price = bf._american(row.get("price"))
        key = (player, market, line)
        record = best.get(key)
        if record is None:
            away = str(row.get("away_team") or "")
            home = str(row.get("home_team") or "")
            record = {
                "player": player, "team": "", "market": market, "line": line,
                "over_price": None, "under_price": None,
                "book": str(row.get("bookmaker") or ""),
                "event": f"{away} @ {home}",
                "game_time": str(row.get("commence_time") or ""),
                "home_team": home, "away_team": away, "is_ladder": False,
            }
            best[key] = record
        side = str(row.get("selection") or "").strip().lower()
        if side == "under":
            record["under_price"] = bf._better(record["under_price"], price)
        elif side in OVER_SIDES:
            record["over_price"] = bf._better(record["over_price"], price)

    rows = list(best.values())
    two_sided = sum(1 for r in rows if r["over_price"] is not None and r["under_price"] is not None)
    result = {
        "week": week, "log_rows": len(raw), "kept_rows": len(kept), "csv_rows": len(rows),
        "two_sided": two_sided, "events_multi_snapshot": multi,
    }
    if dry_run:
        result["wrote"] = None
        return result
    path = bf.write_week_csv(season, week, rows, out_dir=source_root)
    result["wrote"] = str(path)
    result["bytes"] = path.stat().st_size
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--weeks", required=True, help="e.g. 10-18 or 10,11,12")
    parser.add_argument("--source-root", default="", help="defaults to the NFL source root")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bf_for_rebuild", REPO_ROOT / "scripts" / "backfill_nfl_historical_props.py")
    bf = importlib.util.module_from_spec(spec)
    sys.modules["_bf_for_rebuild"] = bf
    spec.loader.exec_module(bf)

    if args.source_root:
        source_root = Path(args.source_root)
    else:
        from syndicate.features.nfl.sources import default_nfl_source_root

        source_root = default_nfl_source_root()
    print(f"source root: {source_root}")
    print(f"mode       : {'DRY RUN' if args.dry_run else 'WRITE'}")

    results = [rebuild_week(bf, source_root, args.season, w, dry_run=args.dry_run)
               for w in _parse_weeks(args.weeks)]
    print()
    print(f"{'wk':>3} {'log':>8} {'kept':>8} {'csv':>7} {'2-sided':>8} {'multi':>6}  wrote")
    failed = 0
    for r in results:
        if r.get("error"):
            failed += 1
            print(f"{r['week']:3} {'-':>8} {'-':>8} {'-':>7} {'-':>8} {'-':>6}  {r['error']}")
            continue
        print(f"{r['week']:3} {r['log_rows']:8} {r['kept_rows']:8} {r['csv_rows']:7} "
              f"{r['two_sided']:8} {r['events_multi_snapshot']:6}  {r.get('wrote') or '(dry run)'}")
    ok = [r for r in results if not r.get("error")]
    print(f"\ntotals: csv rows {sum(r['csv_rows'] for r in ok):,}  "
          f"two-sided {sum(r['two_sided'] for r in ok):,}  weeks missing a log: {failed}")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
