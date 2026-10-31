"""The Phase 0 gate reading for IN-PLAY fills: does every settled live in-play fill join a decision record?

Lane in-game-trading item (e), handed over by syndicate-decision-engine (log 2026-10-30 17:50Z; the
pregame reading is deploys.md 2026-10-30 17:10Z). READ-ONLY: reads the ledger, the in-play decision
records and the paper doc, and writes nothing.

Population (as at 17:10Z): live orders, `status=filled`, `fill_stake_dollars > 0`, outcome won/lost/push,
`submitted_at >= --since`. Phase: pregame when `submitted_at <= commence_time`, else in-play (after the
start, or no `commence_time`). For each in-play fill it reports:
  * inplay_record -- its `idempotency_key` is in `<data root>/reports/intelligence/decision_records/<selected_date>.inplay.jsonl`
               (`inplay_entries_live.append_decision_record`);
  * version -- the ledger row carries `staked_probability_version`;
  * paper   -- a paper-doc entry's `live.key` equals it. That is the historical trace only: it holds the fair, ask
               and result, and not the guard verdicts or the sizing rule.

Self-contained on purpose (stdlib + execution_ledger + refresh_state_store), so it runs on a fleet checkout
that predates the record:
    python scripts/inplay_decision_record_join.py --since 2026-10-23 [--env-from-pid <worker pid>] [--repo <checkout>] [--json]
`--env-from-pid` loads that process's environment into this one (Linux /proc). No value is ever printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env_from_pid(pid: int) -> int:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    n = 0
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            os.environ[k.decode()] = v.decode(errors="replace")
            n += 1
    return n


def _ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def phase(order: dict) -> str:
    sub, start = _ts(order.get("submitted_at")), _ts(order.get("commence_time"))
    if start is None:
        return "in_play_no_commence"
    return "pregame" if sub is not None and sub <= start else "in_play"


def read_inplay_records(records_dir: Path, day: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        lines = (records_dir / f"{day}.inplay.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("idempotency_key"):
            out[str(rec["idempotency_key"])] = rec
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2026-10-23")
    ap.add_argument("--env-from-pid", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=str(REPO_ROOT), help="checkout whose code reads the ledger (e.g. the fleet's)")
    args = ap.parse_args(argv)
    if args.env_from_pid:
        _env_from_pid(args.env_from_pid)
    sys.path.insert(0, str(Path(args.repo).resolve()))
    from syndicate.features.shared.execution_ledger import full_history_orders
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file_result, reports_root

    records_dir = Path(data_root()) / "reports" / "intelligence" / "decision_records"
    paper, ok = read_json_file_result(Path(reports_root()) / "intelligence" / "inplay_entries_paper.json")
    paper_keys = {str((e.get("live") or {}).get("key")) for e in ((paper or {}).get("entries") or {}).values()
                  if isinstance(e, dict) and (e.get("live") or {}).get("key")}
    fills = [o for o in full_history_orders()
             if str(o.get("mode") or "").lower() == "live" and o.get("status") == "filled"
             and float(o.get("fill_stake_dollars") or 0) > 0 and o.get("outcome") in ("won", "lost", "push")
             and str(o.get("submitted_at") or "") >= args.since]
    cache: dict[str, dict] = {}
    rows: Counter = Counter()
    by_day: dict[str, Counter] = {}
    for o in fills:
        ph = phase(o)
        key = str(o.get("idempotency_key") or "")
        day = str(o.get("selected_date") or "")
        if day not in cache:
            cache[day] = read_inplay_records(records_dir, day)
        rec = key in cache[day]
        ver = bool(o.get("staked_probability_version"))
        pap = key in paper_keys
        rows[(ph, "n")] += 1
        rows[(ph, "inplay_record")] += rec
        rows[(ph, "version")] += ver
        rows[(ph, "inplay_record_and_version")] += rec and ver
        rows[(ph, "paper_trace")] += pap
        rows[(ph, "ingame_position_key")] += str(o.get("position_key") or "").startswith("ingame:")
        if ph != "pregame":
            d = by_day.setdefault(str(o.get("submitted_at") or "")[:10], Counter())
            d["n"] += 1
            d["inplay_record"] += rec
            d["paper_trace"] += pap
    out = {
        "since": args.since, "fills": len(fills), "paper_doc_readable": bool(ok), "paper_doc_live_keys": len(paper_keys),
        "records_dir_exists": records_dir.is_dir(),
        "inplay_record_files": sorted(p.name for p in records_dir.glob("*.inplay.jsonl")) if records_dir.is_dir() else [],
        "by_phase": {ph: {m: rows[(ph, m)] for m in ("n", "inplay_record", "version", "inplay_record_and_version", "paper_trace",
                                                    "ingame_position_key")}
                     for ph in ("pregame", "in_play", "in_play_no_commence")},
        "in_play_by_submit_day": {d: dict(c) for d, c in sorted(by_day.items())},
    }
    if args.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"fills={out['fills']} since={args.since} paper_doc_readable={out['paper_doc_readable']} "
              f"paper_live_keys={out['paper_doc_live_keys']} inplay_record_files={len(out['inplay_record_files'])}")
        for ph, m in out["by_phase"].items():
            print(f"  {ph:20s} " + " ".join(f"{k}={v}" for k, v in m.items()))
        for d, c in out["in_play_by_submit_day"].items():
            print(f"  in-play {d} " + " ".join(f"{k}={v}" for k, v in c.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
