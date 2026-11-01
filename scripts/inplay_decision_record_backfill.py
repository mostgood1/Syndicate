"""Backfill in-play decision records for live in-game orders placed BEFORE the record existed (lane in-game-trading item (e)).

User decision 2026-11-01 (session 6a4afb): "Backfill them". The live placer has written one record per decision since
the 9a41c6f66 restart (16:22Z 11-01); every earlier placed order left only its paper-doc entry, whose `live.key` IS the
ledger `idempotency_key`. This turns each such entry into a record line in the same file the placer appends to,
`<data root>/reports/intelligence/decision_records/<selected_date>.inplay.jsonl`, so the gate reading
(`scripts/inplay_decision_record_join.py`) joins it.

What a backfilled record can and cannot say:
  * fair, ask, edge, fee, n_books, the score/mid-move filters and the leg come from the paper entry, as booked;
  * every guard verdict is `pass_inferred` -- the order was placed, so each guard passed, but none was recorded;
  * sizing carries the ledger row's requested stake only; the rule version in force is not known (`backfill_unknown`);
  * `backfill` names the source, and the ledger row itself is NOT edited (its `staked_probability_version` stays absent).

Only placed entries (a `live.key` matching a ledger row) are written: a refusal has no order to join. Idempotent: a key
already in its day's file is skipped. DRY RUN unless `--write`.
    python scripts/inplay_decision_record_backfill.py [--env-from-pid <worker pid>] [--repo <checkout>] [--write]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARDS = ("band", "cell_gate", "ledger", "axis", "day_budget", "check_order")
BACKFILL_SOURCE = "inplay_entries_paper.json live.key"
FAIR_VERSION_BEFORE_TAG = "inplay_book_median_novig/1"  # the only in-play fair the live placer has ever used


def _env_from_pid(pid: int) -> None:
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            os.environ[k.decode()] = v.decode(errors="replace")


def backfill_record(entry: Mapping[str, Any], order: Mapping[str, Any], *, record_version: str,
                    backfilled_at: str) -> dict[str, Any]:
    """One record line for a placed paper entry and its ledger row. PURE."""
    ticker, leg = str(entry["ticker"]), str(entry["leg"])
    fair_version = entry.get("fair_version") or FAIR_VERSION_BEFORE_TAG
    return {
        "version": record_version,
        "decided_at": entry.get("at"),
        "selected_date": order.get("selected_date") or entry.get("day"),
        "decision_id": f"{entry.get('day')}:{ticker}:{leg}",
        "idempotency_key": str(order["idempotency_key"]),
        "position_key": order.get("position_key"),
        "venue": "kalshi", "venue_ticker": ticker, "leg": leg, "sport": entry.get("sport"), "kind": entry.get("kind"),
        "line": entry.get("line"), "team": entry.get("team"),
        "game": {k: entry.get(k) for k in ("event_id", "home_team", "away_team", "commence_time")},
        "fair": {"p": entry.get("fair"), "version": fair_version, "n_books": entry.get("n_books"),
                 "edge": entry.get("edge"), "fee": entry.get("fee"), "since_score_s": entry.get("since_score_s"),
                 "mid_move_60s": entry.get("mid_move_60s"), "rule": None, "booked_at": entry.get("at")},
        "ask": entry.get("ask"),
        "guards": {g: {"verdict": "pass_inferred"} for g in GUARDS},
        "sizing": {"version": "backfill_unknown", "basis": None,
                   "stake": order.get("requested_stake_dollars"), "contracts": None},
        "staked_probability_version": f"inplay:{fair_version}",
        "result": {"placed": True, "status": (entry.get("live") or {}).get("status"), "key": order["idempotency_key"]},
        "backfill": {"at": backfilled_at, "source": BACKFILL_SOURCE, "guards": "inferred_from_placement",
                     "ledger_row_edited": False},
    }


def plan(entries: Mapping[str, Any], orders: Mapping[str, Mapping[str, Any]],
         existing: Mapping[str, set], *, record_version: str, backfilled_at: str):
    """({day: [record, ...]}, Counter of why each placed entry was or was not written). PURE."""
    out: dict[str, list] = {}
    why: Counter = Counter()
    for e in entries.values():
        live = (e or {}).get("live") if isinstance(e, dict) else None
        key = str((live or {}).get("key") or "")
        if not key:
            continue
        order = orders.get(key)
        if order is None:
            why["no_ledger_row"] += 1
            continue
        day = str(order.get("selected_date") or e.get("day"))
        if key in existing.get(day, set()):
            why["already_recorded"] += 1
            continue
        why["write"] += 1
        why["day_mismatch"] += day != str(e.get("day"))
        out.setdefault(day, []).append(backfill_record(e, order, record_version=record_version,
                                                       backfilled_at=backfilled_at))
    return out, why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env-from-pid", type=int, default=None)
    ap.add_argument("--repo", default=str(REPO_ROOT))
    ap.add_argument("--write", action="store_true", help="append the records (default: dry run)")
    args = ap.parse_args(argv)
    if args.env_from_pid:
        _env_from_pid(args.env_from_pid)
    sys.path.insert(0, str(Path(args.repo).resolve()))
    from syndicate.features.shared import inplay_entries_live as live_mod
    from syndicate.features.shared.execution_ledger import full_history_orders
    from syndicate.features.shared.refresh_state_store import read_json_file_result, reports_root

    paper, ok = read_json_file_result(Path(reports_root()) / "intelligence" / "inplay_entries_paper.json")
    if not ok:
        print("paper doc unreadable; nothing done")
        return 2
    entries = (paper or {}).get("entries") or {}
    orders = {str(o.get("idempotency_key")): o for o in full_history_orders() if o.get("idempotency_key")}
    days = {str(o.get("selected_date") or "") for o in orders.values()} | {str(e.get("day")) for e in entries.values()
                                                                          if isinstance(e, dict)}
    existing = {d: {str(r.get("idempotency_key")) for r in live_mod.read_decision_records(d)} for d in days if d}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    todo, why = plan(entries, orders, existing, record_version=live_mod.RECORD_VERSION, backfilled_at=stamp)
    print(f"{'WRITE' if args.write else 'DRY RUN'} at {stamp}: " + " ".join(f"{k}={v}" for k, v in sorted(why.items())))
    for day, recs in sorted(todo.items()):
        print(f"  {day}: {len(recs)} -> {live_mod.records_path(day).name}")
        if args.write:
            for rec in recs:
                live_mod.append_decision_record(day, rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
