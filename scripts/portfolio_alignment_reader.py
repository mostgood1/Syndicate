"""Fleet-side, READ-ONLY reader for the portfolio monitor's ALIGNMENT section (lane portfolio-monitor).

What the purchaser can buy is decided by two documents web does not serve whole: the Layer 2 shortlist (about 4,500
rows; `/api/board/layer2-shortlist` caps a reply at 2,000, and per-sport reads cost web ~14 MB a reading) and the
per-venue LIVE plans (`portfolio_live_plan_<venue>_<date>`, store only). This reads both from the fleet's own store,
under refresh-worker's environ, and prints ONE compact JSON document on stdout: key fields and flags only.

Never prints the environ, a stake, a price or a balance. Writes nothing.

Run by `portfolio_monitor_probe.py` through WSL, with the fleet's own interpreter and its checkout as cwd:
    cd /home/amyn/Syndicate && <refresh-worker's python> portfolio_alignment_reader.py <refresh-worker pid> <YYYY-MM-DD>
"""
from __future__ import annotations

import json
import os
import sys
import time

VENUES = ("kalshi", "polymarket")
ROW_FIELDS = ("sport", "event_id", "market", "line", "player_name", "segment", "side")


def _num(value, nd=2):
    try:
        return round(float(value), nd)
    except (TypeError, ValueError):
        return None


def compact(row: dict, rank: int | None = None) -> dict:
    out = {k: row.get(k) for k in ROW_FIELDS}
    out["suggested"] = bool(row.get("suggested"))
    out["ev"] = _num(row.get("ev_pct"))
    out["me"] = _num(row.get("model_edge_pct"))
    out["live"] = bool(row.get("is_live")) or str(row.get("market_state") or "").lower() == "live"
    if rank is not None:
        out["rank"] = rank
    if "live_ev_floor" in row:
        out["live_ev_floor"] = row.get("live_ev_floor")
    if "price_source" in row:
        out["price_source"] = row.get("price_source")
    return out


def with_placeable(out: dict, position: dict, refusal_fn) -> dict:
    """Stamp the fleet's OWN `placeable_refusal` verdict on a plan position: the same predicate the live plan runs on
    paper2's scoped rows and its LIVE_PLAN_WRITTEN self-check counts as `paper2_placeable`. Copying the ticker and
    re-deriving the test here could disagree with it; calling it cannot. Absent when the predicate is unavailable.

    11-24 (findings_2026-11-24_portfolio_monitor.md, H-S2): Polymarket's paper2 held 2 Suggested positions for 3.5 h,
    none placeable (aggregator-priced), and the panel's "N positions at its price" could not tell them from buyable."""
    if refusal_fn is None:
        return out
    reason = refusal_fn(position)
    out["placeable"] = reason is None
    if reason is not None:
        out["placeable_refusal"] = reason
    return out


def main() -> int:
    t0 = time.monotonic()
    pid, date = sys.argv[1], sys.argv[2]
    env = {}
    for item in open(f"/proc/{pid}/environ", "rb").read().split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode()] = v.decode(errors="replace")
    os.environ.update(env)  # the store backend and its address; never printed
    sys.path.insert(0, os.getcwd())
    from pipeline.intelligence_state import read_layer2_shortlist
    from pipeline.portfolio_commit import live_portfolio_plan_path_for_venue, portfolio_plan_path_for_venue
    try:
        from pipeline.portfolio_commit import placeable_refusal
    except ImportError:  # a fleet checkout older than the live plan's own predicate: report unknown, not placeable
        placeable_refusal = None
    from syndicate.features.shared.refresh_state_store import read_json_file

    out: dict = {"date": date}
    board = read_layer2_shortlist(date)
    if isinstance(board, dict):
        rows = [r for r in (board.get("rows") or []) if isinstance(r, dict)]
        out["board"] = {
            "written_at": board.get("written_at") or board.get("generated_at") or board.get("index_written_at"),
            "rows": [compact(r, i) for i, r in enumerate(rows)],
        }
    else:
        out["board"] = {"error": f"no shortlist for {date}"}
    plans: dict = {}
    for venue in VENUES:
        for kind, fn in (("live", live_portfolio_plan_path_for_venue), ("paper2", portfolio_plan_path_for_venue)):
            doc = read_json_file(fn(date, venue))
            if not isinstance(doc, dict):
                plans[f"{kind}_{venue}"] = {"absent": True}
                continue
            positions = [p for p in (doc.get("positions") or []) if isinstance(p, dict)]
            plans[f"{kind}_{venue}"] = {
                "generated_at": doc.get("generated_at"),
                "rows_in": doc.get("rows_in"),
                "refusals": doc.get("refusals") or {},
                "scope_refusals": doc.get("venue_scope_refusals") or {},
                "positions": [with_placeable(compact(p), p, placeable_refusal) for p in positions],
            }
    out["plans"] = plans
    out["seconds"] = round(time.monotonic() - t0, 2)
    sys.stdout.write(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
