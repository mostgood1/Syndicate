"""Grade the hold-value exit SHADOW against settlement (todo #856, lane hold-value-exits).

Read-only. The rule it applies was PRE-REGISTERED before any shadow row or outcome
was read: `.syndicate/findings_2026-11-20_hold_value_exits.md` s2.3. Its defaults are
that registration (window end 2026-12-06 23:59:59 CST, games on or before 12-06,
>= 60 events and >= 80 positions); change them only for an exploratory read, and
say so.

On the fleet (reads the shadow log, the execution ledger and the exits document +
archive where they live; nice it):

    nice -n 19 ~/.venvs/syndicate/bin/python scripts/exit_hold_value_shadow_grade.py

(System `python3` has no redis: the ledger would read as EMPTY.) Off the fleet, from
dumps:

    python scripts/exit_hold_value_shadow_grade.py --shadow-dir DIR \
        --ledger-json ledger.json --exits-json execution_exits.json

`--ledger-json` takes `{"orders": [...]}` or a bare list; `--exits-json` takes the
exits document (`{"exits": {...}}`) or a list of exit rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_orders(path: str | None) -> list[dict]:
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(payload.get("orders") or []) if isinstance(payload, dict) else list(payload)
    from syndicate.features.shared.execution_ledger import full_history_orders

    return list(full_history_orders())


def _load_exit_rows(path: str | None) -> list[dict]:
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return [r for r in (payload.get("exits") or {}).values() if isinstance(r, dict)]
        return [r for r in payload if isinstance(r, dict)]
    from syndicate.features.shared.execution_exits import archived_exit_rows, load_state

    rows = {str(r.get("exit_key")): r for r in archived_exit_rows() if r.get("exit_key")}
    rows.update({str(k): r for k, r in (load_state().get("exits") or {}).items()})  # the document wins
    return list(rows.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shadow-dir", help="directory of shadow_*.jsonl (default: the reports root's)")
    parser.add_argument("--ledger-json", help="a ledger dump instead of the live store")
    parser.add_argument("--exits-json", help="an exits document / row-list dump instead of the live store")
    parser.add_argument("--end-utc", default="2026-12-07T05:59:59Z", help="last shadow tick (registered: 12-06 23:59:59 CST)")
    parser.add_argument("--last-game-date", default="2026-12-06", help="last game date, Central (registered)")
    parser.add_argument("--min-events", type=int, default=60, help="registered minimum events in P")
    parser.add_argument("--min-positions", type=int, default=80, help="registered minimum positions in P")
    parser.add_argument("--no-positions", action="store_true", help="omit the per-position list")
    args = parser.parse_args(argv)

    from syndicate.features.shared.exit_hold_value import grade_shadow, read_shadow_rows

    rows = read_shadow_rows(Path(args.shadow_dir) if args.shadow_dir else None)
    report = grade_shadow(
        rows,
        _load_orders(args.ledger_json),
        _load_exit_rows(args.exits_json),
        end_utc=args.end_utc,
        last_game_date=args.last_game_date,
        min_events=args.min_events,
        min_positions=args.min_positions,
    )
    registered = (args.end_utc, args.last_game_date, args.min_events, args.min_positions) == (
        "2026-12-07T05:59:59Z", "2026-12-06", 60, 80,
    )
    report["registered_parameters"] = registered
    if not registered:
        report["note"] = "EXPLORATORY: parameters differ from the pre-registration; this is not the verdict"
    if args.no_positions:
        report.pop("positions", None)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
