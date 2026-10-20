"""Daily PRE-REGISTERED evaluation of the PAPER Kalshi maker shadow (lane `kalshi-maker-shadow-paper`).

The stop rule is fixed in `.syndicate/findings_2026-10-20_kalshi_maker_shadow_preregistration.md`,
committed before the shadow recorded anything; the code is `kalshi_maker_shadow.counted_population`,
`cell_stats`, `judge_look` and `take_looks`. Decisions are taken ONLY at looks (200 / 400 / 600 counted
B-filled orders per cell, or the 2027-01-31 calendar stop) and frozen in `looks.json`; every other day's
numbers are descriptive.

Reads and writes only `<data root>/reports/intelligence/kalshi_maker_shadow/`. Places nothing.

Usage:
    python scripts/evaluate_kalshi_maker_shadow.py            # the daily job (takes any due look)
    python scripts/evaluate_kalshi_maker_shadow.py --no-looks # read-only report, never freezes a look
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import kalshi_maker_shadow as ms  # noqa: E402


def data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(override).expanduser().resolve() if override else REPO_ROOT / "data"


def _fmt_pp(stat: dict | None) -> str:
    if not stat:
        return "-"
    lo, hi = stat["ci95"]
    return f"{100 * stat['mean']:+.2f}pp [{100 * lo:+.2f}, {100 * hi:+.2f}] n={stat['n']}/{stat['events']}ev"


def _fmt_pct(stat: dict | None) -> str:
    if not stat:
        return "-"
    lo, hi = stat["ci95"]
    return f"{100 * stat['mean']:+.1f}% [{100 * lo:+.1f}, {100 * hi:+.1f}]"


def evaluate(root: Path, now: float, *, take: bool = True) -> dict[str, Any]:
    records = []
    for path in ms.iter_order_files(root):
        records.extend((ms.load_json(path, {}).get("legs") or {}).values())
    coverage: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for rec in records:
        cov = coverage[str(rec.get("cell"))]
        cov["legs"] += 1
        cov["placed"] += bool(rec.get("order"))
        cov["closed"] += bool(rec.get("order") and rec.get("closed"))
        cov["settled"] += bool((rec.get("settlement") or {}).get("result") in ("yes", "no"))
    rows, population = ms.counted_population(records)
    by_cell: dict[str, list] = collections.defaultdict(list)
    for row in rows:
        by_cell[row["cell"]].append(row)
    per_cell = {cell: {"B": ms.cell_stats(by_cell.get(cell, []), "B"), "A": ms.cell_stats(by_cell.get(cell, []), "A")}
                for cell in ms.CELLS}
    pooled = {"B": ms.cell_stats(rows, "B"), "A": ms.cell_stats(rows, "A")}
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
    looks_path = ms.store_dir(root) / "looks.json"
    looks = ms.load_json(looks_path, {})
    if take:
        before = json.dumps(looks, sort_keys=True)
        looks = ms.take_looks(looks, {c: per_cell[c]["B"] for c in ms.CELLS}, today)
        if json.dumps(looks, sort_keys=True) != before:
            ms.save_json(looks_path, looks)
    report = {
        "at": ms.iso(now), "rule_version": ms.RULE_VERSION,
        "preregistration": ".syndicate/findings_2026-10-20_kalshi_maker_shadow_preregistration.md",
        "coverage": {k: dict(v) for k, v in coverage.items()}, "population": population,
        "counted_orders": len(rows), "per_cell": per_cell, "pooled_descriptive_only": pooled,
        "looks": looks, "note": "Numbers between looks are descriptive. Only looks.json carries a decision.",
    }
    ms.save_json(ms.store_dir(root) / f"evaluation_{today}.json", report)
    return report


def print_report(report: dict[str, Any]) -> None:
    print(f"[maker_shadow_eval] {report['at']} counted orders {report['counted_orders']} "
          f"excluded {json.dumps(report['population']['excluded'], sort_keys=True)} "
          f"mispaired {json.dumps(report['population']['mispaired_series'], sort_keys=True)}", flush=True)
    for cell, cov in sorted(report["coverage"].items()):
        print(f"  coverage {cell}: {json.dumps(cov, sort_keys=True)}", flush=True)
    for cell in ms.CELLS:
        status = (report["looks"].get(cell) or {}).get("status", "CONTINUE")
        for model in ("B", "A"):
            s = report["per_cell"][cell][model]
            rate = "-" if s["fill_rate"] is None else f"{100 * s['fill_rate']:.1f}%"
            print(f"  {cell:22} {model}{' (primary)' if model == 'B' else ' (secondary)'} placed {s['placed']} "
                  f"filled {s['filled']} ({rate}) | filled win-close {_fmt_pp(s['filled_win_minus_close'])} | "
                  f"unfilled win-close {_fmt_pp(s['unfilled_win_minus_close'])} | ROI {_fmt_pct(s['filled_roi'])}"
                  f"{'  STATUS ' + status if model == 'B' else ''}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-looks", action="store_true", help="report only; never take or freeze a look")
    args = ap.parse_args(argv)
    if hasattr(os, "nice"):
        try:
            os.nice(19)
        except OSError:
            pass
    report = evaluate(data_root(), time.time(), take=not args.no_looks)
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
