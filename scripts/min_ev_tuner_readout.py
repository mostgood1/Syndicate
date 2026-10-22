"""Read the min_ev tuner: tonight's shadow state, or a walk-forward replay of a ledger dump.

    # the fleet's persisted state (run inside WSL with the worker's state env):
    python scripts/min_ev_tuner_readout.py state

    # backtest: replay the nightly pass over a JSON list of ledger orders
    python scripts/min_ev_tuner_readout.py replay --ledger-json dump.json

The replay is walk-forward: night D sees only orders whose `graded_at` is before
D 12:00Z (the hook's run hour), carries the previous night's state forward, and
prints every move it would have made. It prints COVERAGE first -- per venue,
mode and sport, the settled rows and the dates they span -- because a result
is only as wide as the narrowest family under it (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import min_ev_tuner as T  # noqa: E402


def _pooled_text(pooled) -> str:
    if not isinstance(pooled, dict):
        return ""
    return (
        f" POOLED[{pooled.get('action')} {pooled.get('reason')} fam_ev={pooled.get('family_events')} "
        f"roi={pooled.get('roi_theta_pct')} z={pooled.get('roi_z')} shrink={pooled.get('roi_shrink')} "
        f"clv={pooled.get('clv_theta')} z={pooled.get('clv_z')}]"
    )


def _cell_lines(cells: dict, limit: int) -> list[str]:
    def size(item):
        return -((item[1].get("evidence") or {}).get("events") or 0)

    out = []
    for key, entry in sorted(cells.items(), key=size)[:limit]:
        ev, mg = entry.get("evidence") or {}, entry.get("marginal") or {}
        out.append(
            f"{key:52s} cut={entry.get('min_ev_pct') if entry.get('min_ev_pct') is not None else 'base':>5} "
            f"{entry.get('action'):5s} {entry.get('reason'):30s} "
            f"cell[ev={ev.get('events')} roi={ev.get('roi_pct')} t={ev.get('roi_t')} clv={ev.get('avg_clv_pct')} t={ev.get('clv_t')}] "
            f"band{mg.get('band')}[ev={mg.get('events')} {mg.get('roi_basis', 'dollars')}_roi={mg.get('roi_pct')} t={mg.get('roi_t')} "
            f"$roi={mg.get('dollar_roi_pct')} ev_only$={mg.get('ev_only_roi_pct')} "
            f"clv_n={mg.get('clv_events')} clv={mg.get('avg_clv_pct')} t={mg.get('clv_t')}]"
            + _pooled_text(entry.get("pooled"))
        )
    return out


def cmd_state(args) -> int:
    state = T.load_state()
    if not state:
        print("NO STATE: the tuner has not run (or the store lost the key)")
        return 1
    print(
        f"mode={state.get('mode')} last_run_at={state.get('last_run_at')} base={state.get('base_min_ev_pct')} "
        f"actions={state.get('actions')} skipped={state.get('skipped')} "
        f"pooling={state.get('pooling')} pooled_actions={state.get('pooled_actions')}"
    )
    print(f"params={state.get('params')} clv_scopes={state.get('clv_scopes')} evidence={state.get('evidence_modes')}")
    for line in _cell_lines(state.get("cells") or {}, args.limit):
        print(line)
    audit = state.get("audit") or []
    print(f"audit: {len(audit)} move(s)")
    for move in audit[-args.limit:]:
        print("  " + json.dumps(move, sort_keys=True))
    return 0


def coverage(orders) -> None:
    rows, dates = Counter(), defaultdict(set)
    for o in orders:
        if o.get("status") == "filled" and o.get("outcome") and T.venue_family(o.get("venue")):
            key = (str(o.get("venue")), T.order_mode(o), str(o.get("sport")), o.get("ev_pct") is not None)
            rows[key] += 1
            dates[key].add(str(o.get("selected_date")))
    print("COVERAGE (settled, tuned venues): venue mode sport has_ev rows dates first..last")
    for key in sorted(rows):
        d = sorted(dates[key])
        print(f"  {key[0]:18s} {key[1]:6s} {key[2]:8s} {str(key[3]):5s} {rows[key]:5d} {len(d):3d} {d[0]}..{d[-1]}")


def cmd_replay(args) -> int:
    orders = json.loads(Path(args.ledger_json).read_text(encoding="utf-8"))
    coverage(orders)
    graded = sorted(str(o.get("graded_at") or "") for o in orders if o.get("graded_at"))
    if not graded:
        print("no graded orders")
        return 1
    first = date.fromisoformat(graded[0][:10]) + timedelta(days=1)
    last = date.fromisoformat(graded[-1][:10]) + timedelta(days=1)
    state: dict = {}
    nights = moves = pooled_moves = 0
    day = first
    while day <= last:
        cutoff = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        seen = [o for o in orders if str(o.get("graded_at") or "9999") < cutoff]
        result = T.compute_proposals(seen, state=state, base_min_ev_pct=args.base)
        nights += 1
        for key, entry in result["cells"].items():
            pooled = entry.get("pooled") or {}
            if pooled.get("action") in (T.ACTION_RAISE, T.ACTION_LOWER):
                pooled_moves += 1
                print(f"{day} POOLED-SHADOW {key} {pooled.get('action')} -> {pooled.get('min_ev_pct')}{_pooled_text(pooled)}")
            if entry.get("action") in (T.ACTION_RAISE, T.ACTION_LOWER):
                moves += 1
                mg = entry.get("marginal") or {}
                print(
                    f"{day} MOVE {key} {entry['previous_min_ev_pct']} -> {entry['min_ev_pct']} "
                    f"band={mg.get('band')} events={mg.get('events')} roi={mg.get('roi_pct')} t={mg.get('roi_t')} "
                    f"clv={mg.get('avg_clv_pct')} t={mg.get('clv_t')}"
                )
        state = {"cells": result["cells"]}
        day += timedelta(days=1)
    print(f"REPLAY nights={nights} moves={moves} final actions={result['actions']} skipped={result['skipped']}")
    print(f"pooling={result.get('pooling')} final pooled_actions={result.get('pooled_actions')} "
          f"pooled moves over the replay={pooled_moves}")
    reasons = Counter(e.get("reason") for e in result["cells"].values())
    print(f"final hold reasons={dict(reasons.most_common())}")
    for line in _cell_lines(result["cells"], args.limit):
        print(line)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_state = sub.add_parser("state")
    p_state.add_argument("--limit", type=int, default=25)
    p_state.set_defaults(func=cmd_state)
    p_replay = sub.add_parser("replay")
    p_replay.add_argument("--ledger-json", required=True)
    p_replay.add_argument("--base", type=float, default=2.0)
    p_replay.add_argument("--limit", type=int, default=25)
    p_replay.set_defaults(func=cmd_replay)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
