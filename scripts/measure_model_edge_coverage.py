"""Model-edge coverage on the SERVED payload, per sport, with its denominators.

The verification owed by `#601` / lane `layer1-model-edge-join`. It answers one
question -- how much of the board carries a model view Layer 2 can rank and size
on -- and it answers it as a RATE with the denominator beside it, because the
board's composition moves under you.

WHY THE STATE MIX IS PRINTED. A before/after across a deploy is never a
same-instant comparison: games go final between the two reads, and a final
game's rows legitimately carry no edge at all. A coverage number that drops
because the slate finished looks identical to one that dropped because a join
broke. So every count here travels with the pregame/live/final split that
produced it, and the pregame rate is the one to compare.

WHY IT READS TWO SURFACES. `/api/board/layer2-shortlist`'s `per_sport_ingest`
carries the WORKER's own counters (`rows_with_model_edge`, `sides_priced`), which
is what the board was actually built from. `/api/board/layer1` is what a reader
sees. They can disagree -- a worker on an older commit than web is the normal
state of this system -- and that disagreement is a finding, not noise.

    py -3 scripts/measure_model_edge_coverage.py
    py -3 scripts/measure_model_edge_coverage.py --json
"""

from __future__ import annotations

import argparse
import collections
import json
import urllib.request

DEFAULT_BASE = "https://syndicate-an21.onrender.com"

# Measured 2026-08-30 on production, BEFORE the `#601` fixes, from the same two
# endpoints this script reads. Carried here so a later run is a comparison
# rather than a bare number -- and dated, because a baseline expires.
BASELINE = {
    "measured_at": "2026-08-30T22:2xZ",
    "per_sport": {          # sport: (sides_priced, rows_with_model_edge)
        "mlb": (5316, 318),
        "ncaaf": (939, 0),
        "nfl": (2494, 674),
        "soccer": (15682, 339),
        "wnba": (2404, 75),
    },
    "shortlist": {
        "opportunities_considered": 9636,
        "rows_uninformative_ev": 1269,
        "rows_below_value_floor": 801,
        "rows_admitted_by_blend": 55,
    },
    "edge_vs_modelled_fair_pct_rows": 0,
}


def _get(url: str, timeout: float = 300.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


def _pct(n, d):
    return f"{100.0 * n / d:5.1f}%" if d else "    -"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--sports", default="mlb,wnba,ncaaf,nfl,soccer")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    out: dict = {"base_url": args.base_url, "baseline": BASELINE}

    # ---- the worker's own counters -------------------------------------
    shortlist = _get(f"{args.base_url}/api/board/layer2-shortlist")
    out["shortlist_written_at"] = shortlist.get("written_at")
    ingest = shortlist.get("per_sport_ingest") or {}
    worker: dict = {}
    for sport, block in ingest.items():
        enrichment = block.get("enrichment") or {}
        margin = enrichment.get("margin_model") or {}
        worker[sport] = {
            "sides_priced": block.get("sides_priced"),
            "rows_with_model_edge": block.get("rows_with_model_edge"),
            "grid_rows": block.get("grid_rows"),
            # `#601`: present ONLY on a build carrying the fix. Absent here is
            # the reachability signal -- it says the deployed worker predates it,
            # which is a different answer from "it ran and priced nothing".
            "modelled_edge_rows_priced": margin.get("modelled_edge_rows_priced"),
            "modelled_edge_refusals": margin.get("modelled_edge_refusals"),
            "one_sided_rows": margin.get("one_sided_rows"),
        }
    out["worker"] = worker

    rows = shortlist.get("rows") or []
    out["shortlist_rows"] = {
        "returned": len(rows),
        "with_model_edge": sum(1 for r in rows if r.get("model_edge_pct") is not None),
        # `#601` follow-on: which fair the value term came from.
        "ev_basis": dict(collections.Counter(str(r.get("ev_basis")) for r in rows)),
        "with_model_ev": sum(1 for r in rows if r.get("model_ev_pct") is not None),
    }
    for key in (
        "opportunities_considered", "rows_uninformative_ev",
        "rows_below_value_floor", "rows_admitted_by_blend",
    ):
        out.setdefault("shortlist_counters", {})[key] = shortlist.get(key)

    # ---- what a reader sees --------------------------------------------
    board: dict = {}
    for sport in [s.strip() for s in args.sports.split(",") if s.strip()]:
        try:
            payload = _get(f"{args.base_url}/api/board/layer1?sport={sport}&window=slate")
        except Exception as exc:
            board[sport] = {"error": f"{type(exc).__name__}"}
            continue
        states = collections.Counter()
        by_state = collections.defaultdict(lambda: collections.Counter())
        for game in payload.get("games") or []:
            state = str(game.get("state") or "unknown")
            states[state] += 1
            for row in game.get("rows") or []:
                bucket = by_state[state]
                bucket["rows"] += 1
                projection = row.get("projection")
                if not isinstance(projection, dict):
                    continue
                bucket["projected"] += 1
                if projection.get("edge_vs_market_pct") is not None:
                    bucket["edge"] += 1
                if projection.get("edge_vs_modelled_fair_pct") is not None:
                    bucket["modelled_edge"] += 1
        board[sport] = {
            "games_by_state": dict(states),
            "by_state": {k: dict(v) for k, v in by_state.items()},
        }
    out["board"] = board

    if args.json:
        print(json.dumps(out, indent=1))
        return 0

    print(f"model-edge coverage — {args.base_url}")
    print(f"shortlist written_at {out['shortlist_written_at']}\n")
    print(f"{'sport':8s} {'sides_priced':>13s} {'model_edge':>11s} {'rate':>7s}   "
          f"{'baseline':>16s}  {'mfair_priced':>12s}")
    for sport in sorted(worker):
        w = worker[sport]
        sp, me = w.get("sides_priced") or 0, w.get("rows_with_model_edge") or 0
        base = BASELINE["per_sport"].get(sport)
        base_cell = f"{base[1]}/{base[0]} {_pct(base[1], base[0]).strip()}" if base else "-"
        mf = w.get("modelled_edge_rows_priced")
        mf_cell = "ABSENT" if mf is None else str(mf)
        print(f"{sport:8s} {sp:13d} {me:11d} {_pct(me, sp)}   {base_cell:>16s}  {mf_cell:>12s}")
    print()
    print("  `mfair_priced` ABSENT means the deployed worker predates `#601` --")
    print("  a different answer from 'it ran and priced nothing'.\n")

    print("shortlist counters (baseline in brackets):")
    for key, value in (out.get("shortlist_counters") or {}).items():
        base = BASELINE["shortlist"].get(key)
        print(f"   {key:28s} {value}   [{base}]")
    print(f"   returned rows                {out['shortlist_rows']['returned']}, "
          f"with model_edge {out['shortlist_rows']['with_model_edge']}, "
          f"with model_ev {out['shortlist_rows']['with_model_ev']}")
    print(f"   ev_basis                     {out['shortlist_rows']['ev_basis']}")
    print()

    print("served board, BY GAME STATE (compare the pregame row; a final slate")
    print("legitimately carries no edges and must not be read as a regression):")
    for sport, block in board.items():
        if block.get("error"):
            print(f"   {sport:8s} ERROR {block['error']}")
            continue
        print(f"   {sport:8s} games={block['games_by_state']}")
        for state, counts in sorted(block["by_state"].items()):
            n = counts.get("rows", 0)
            print(f"       {state:8s} rows={n:6d} proj={_pct(counts.get('projected', 0), n)} "
                  f"edge={_pct(counts.get('edge', 0), n)} "
                  f"mfair={counts.get('modelled_edge', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
