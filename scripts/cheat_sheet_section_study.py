"""Re-measure the evidence behind cheat-sheet section rules v2 (lane cheat-sheet-section-optimization, 2026-11-13).

Read-only over `<data root>/cheatsheets`. For every official sheet (`play_cards.OFFICIAL_START` onward) that has a
reconciled file, it takes each graded row and measures, per sport:

  sim_edge   the main line of each player + stat, on the side SmartSim projects >= cs.SIM_EDGE_MIN beyond it,
             featurable (price in the band) and two-sided -- the rule "Sim vs the line" publishes. These are the
             numbers in `cheat_sheets.SIM_EDGE_MEASURED` (ROI at the sheet's best price, 1 u a bet).
  fair_lean  every two-sided graded row's excess over its fair (hit minus `p_market`), split over / under.

Each reading carries a 95% interval from a bootstrap over games (`review_cheat_sheets._boot_ci`). Section-level
readings (each section vs its fair and vs matched non-members) are the daily review's own "against the price".

The MAIN LINE here is the line `primary_lines` keeps under rules 1 -- most books quoting, then nearest the group's
median. Line choice never depended on the rules version; only the side does.

    python scripts/cheat_sheet_section_study.py --data-root ~/syndicate-prod/data [--to 2026-11-12] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from syndicate.features.shared import cheat_sheets as cs  # noqa: E402
from syndicate.features.shared import play_cards as pc  # noqa: E402
import review_cheat_sheets as rv  # noqa: E402


def graded_rows(sheet: Mapping[str, Any], reconciled: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every graded row of one sheet, with what the measurements need."""
    rows = list(sheet.get("rows") or [])
    props = reconciled.get("props") or {}
    main = {cs._stat_key(rows[i]): rows[i].get("line") for i in cs.primary_lines(rows, rules=1)}
    out = []
    for r in rows:
        check = r.get("check") or {}
        res = cs.result_for(check.get("price"), props.get(cs.prop_result_key(r)))
        p = check.get("p_market")
        if res is None or res.get("y") not in (0.0, 1.0) or not isinstance(p, (int, float)):
            continue
        out.append({"sport": sheet.get("sport"), "date": sheet.get("date"), "event_id": r.get("event_id"),
                    "side": "over" if str(r.get("side") or "").lower() in ("over", "yes") else "under",
                    "y": res["y"], "units": res["units"] or 0.0, "ex": res["y"] - float(p),
                    "two_sided": check.get("verdict") != "one_sided_fair", "featurable": cs.featurable(r),
                    "main_line": main.get(cs._stat_key(r)) == r.get("line") and cs._stat_key(r) in main,
                    "sim_backs": cs.sim_backs(r)})
    return out


def reading(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, Any] | None:
    rows = list(rows)
    if not rows:
        return None
    games: dict[Any, list[float]] = defaultdict(list)
    for r in rows:
        games[r["event_id"]].append(r[key])
    mean = sum(r[key] for r in rows) / len(rows)
    ci = rv._boot_ci(list(games.values()))
    return {"n": len(rows), "games": len(games), "mean_pct": round(100 * mean, 1),
            "ci_pct": [round(100 * ci[0], 1), round(100 * ci[1], 1)] if ci else None}


def study(days: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]], *, start: str, end: str | None) -> dict[str, Any]:
    rows = [r for s, rec in days if start <= str(s.get("date")) and (end is None or str(s.get("date")) <= end)
            for r in graded_rows(s, rec)]
    out: dict[str, Any] = {"window": [start, end], "rows": len(rows), "sim_edge": {}, "fair_lean": {}}
    for sport in sorted({r["sport"] for r in rows}):
        mine = [r for r in rows if r["sport"] == sport]
        sim = [r for r in mine if r["main_line"] and r["featurable"] and r["two_sided"] and r["sim_backs"]]
        if sim:
            out["sim_edge"][sport] = {"roi": reading(sim, "units"), "excess": reading(sim, "ex")}
        two = [r for r in mine if r["two_sided"]]
        out["fair_lean"][sport] = {side: reading([r for r in two if r["side"] == side], "ex") for side in ("over", "under")}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT"))
    ap.add_argument("--from", dest="start", default=pc.OFFICIAL_START)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    days = rv.load_days(Path(os.path.expanduser(args.data_root)) / "cheatsheets")
    result = study(days, start=args.start, end=args.end)
    print(f"STUDY window {args.start}..{args.end or 'latest'} graded rows {result['rows']}")
    for sport, r in result["sim_edge"].items():
        roi, ex = r["roi"], r["excess"]
        print(f"  sim_edge {sport:6} {roi['n']:5} bets / {roi['games']:4} games  ROI {roi['mean_pct']:+.1f}% {roi['ci_pct']}"
              f"  excess {ex['mean_pct']:+.1f} pts {ex['ci_pct']}")
    for sport, sides in result["fair_lean"].items():
        print("  fair_lean " + f"{sport:6} " + "  ".join(f"{side} {v['mean_pct']:+.1f} pts {v['ci_pct']} (n{v['n']})"
                                                       for side, v in sides.items() if v))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
