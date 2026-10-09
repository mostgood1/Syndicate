#!/usr/bin/env python3
"""Score the CURRENT WNBA linear live lens on the checkpoint corpus -- the bar P5's native re-sim must clear.

Lane `wnba-native-live-cutover`. Input: the JSONL written by `build_wnba_live_checkpoint_corpus.py`. One row per
game per (phase, checkpoint) cell, so a bootstrap over rows IS game-clustered within a cell.

Per cell: total MAE (vs the FINAL incl. OT, as the market settles), and Brier for ML (vs the home win), cover
(margin + the sim's market spread > 0) and over (total > the sim's market total); pushes excluded and counted.
ESPN's live WP is a third-party ML reference, not a Syndicate model.

Usage: py -3 scripts/score_wnba_live_checkpoint_baseline.py <corpus.jsonl> [--anchored] [--json out.json]
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple


def boot(vals: Sequence[float], reps: int = 2000, seed: int = 7) -> Tuple[Optional[float], Optional[float]]:
    r = random.Random(seed)
    n = len(vals)
    if n < 2:
        return (None, None)
    ms = sorted(sum(vals[r.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return (ms[int(.025 * reps)], ms[int(.975 * reps)])


def _mean(v: Sequence[float]) -> Optional[float]:
    return sum(v) / len(v) if v else None


def score_cell(rs: List[Dict]) -> Dict:
    ae = [abs(r["linear_lens"]["total_proj"] - r["outcome"]["total"]) for r in rs if r["linear_lens"]["total_proj"] is not None]
    pre = [abs(r["linear_lens"]["anchor_total_used"] - r["outcome"]["total"]) for r in rs if r["linear_lens"]["anchor_total_used"] is not None]
    ml = [(r["linear_lens"]["home_win_prob"], r["state"].get("espn_home_wp"), 1.0 if r["outcome"]["home_win"] else 0.0)
          for r in rs if r["linear_lens"]["home_win_prob"] is not None and r["state"].get("espn_home_wp") is not None]
    cover, over, pushes = [], [], {"cover": 0, "over": 0}
    for r in rs:
        lens, out = r["linear_lens"], r["outcome"]
        if lens.get("home_cover_prob") is not None and lens.get("home_spread_line") is not None:
            x = out["margin"] + lens["home_spread_line"]
            if x == 0:
                pushes["cover"] += 1
            else:
                cover.append((lens["home_cover_prob"] - (1.0 if x > 0 else 0.0)) ** 2)
        if lens.get("total_over_prob") is not None and lens.get("total_line") is not None:
            x = out["total"] - lens["total_line"]
            if x == 0:
                pushes["over"] += 1
            else:
                over.append((lens["total_over_prob"] - (1.0 if x > 0 else 0.0)) ** 2)
    bl = [(p - y) ** 2 for p, _, y in ml]
    be = [(e - y) ** 2 for _, e, y in ml]
    d = [a - b for a, b in zip(bl, be)]
    return {
        "n": len(rs), "total_mae": _mean(ae), "total_mae_ci": boot(ae), "pregame_anchor_mae": _mean(pre),
        "ml_n": len(ml), "ml_brier": _mean(bl), "ml_brier_ci": boot(bl), "espn_ml_brier": _mean(be),
        "ml_minus_espn": _mean(d), "ml_minus_espn_ci": boot(d),
        "cover_n": len(cover), "cover_brier": _mean(cover), "cover_brier_ci": boot(cover),
        "over_n": len(over), "over_brier": _mean(over), "over_brier_ci": boot(over), "pushes": pushes,
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rows = [json.loads(line) for line in open(argv[0], encoding="utf-8")]
    anchored_only = "--anchored" in argv
    cells: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for r in rows:
        if anchored_only and not r.get("anchors"):
            continue
        cells[(r["phase"], r["checkpoint"])].append(r)
    out = {f"{k[0]}/{k[1]}": score_cell(v) for k, v in sorted(cells.items())}
    f = lambda x: "  -   " if x is None else f"{x:.4f}"
    ci = lambda c: "-" if c[0] is None else f"[{c[0]:.3f},{c[1]:.3f}]"
    print(f"{'cell':18} {'n':>4} | {'tot MAE':>7} {'CI':>15} {'pre':>6} | {'ML':>6} {'ESPN':>6} {'ML-ESPN':>7} {'CI':>16} | "
          f"{'cover':>6} {'CI':>15} | {'over':>6} {'CI':>15}")
    for k, s in out.items():
        print(f"{k:18} {s['n']:>4} | {f(s['total_mae']):>7} {ci(s['total_mae_ci']):>15} {f(s['pregame_anchor_mae']):>6} | "
              f"{f(s['ml_brier']):>6} {f(s['espn_ml_brier']):>6} {f(s['ml_minus_espn']):>7} {ci(s['ml_minus_espn_ci']):>16} | "
              f"{f(s['cover_brier']):>6} {ci(s['cover_brier_ci']):>15} | {f(s['over_brier']):>6} {ci(s['over_brier_ci']):>15}")
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
