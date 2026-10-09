#!/usr/bin/env python3
"""Score the CURRENT WNBA linear live lens on the checkpoint corpus -- the bar P5's native re-sim must clear.

Lane `wnba-native-live-cutover`. Input: the JSONL written by `build_wnba_live_checkpoint_corpus.py`. One row per
game per (phase, checkpoint) cell, so a bootstrap over rows IS game-clustered within a cell. ESPN's live WP is a
third-party reference, not a Syndicate model. Usage: py -3 scripts/score_wnba_live_checkpoint_baseline.py <corpus.jsonl> [--anchored]
"""
import json, random, sys, math
from collections import defaultdict

rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
anch_only = "--anchored" in sys.argv


def boot(vals, reps=2000, seed=7):
    r = random.Random(seed); n = len(vals)
    if n < 2: return (None, None)
    ms = sorted(sum(vals[r.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return (ms[int(.025 * reps)], ms[int(.975 * reps)])


cells = defaultdict(list)
for r in rows:
    if anch_only and not r.get("anchors"): continue
    cells[(r["phase"], r["checkpoint"])].append(r)
print(f"{'cell':22} {'n':>4} | {'lin MAE':>8} {'CI':>15} | {'pre MAE':>7} | {'lin Brier':>9} {'CI':>15} | {'espn Brier':>10} | {'lin-espn dBrier':>15} {'CI':>17}")
for k in sorted(cells):
    rs = cells[k]
    ae = [abs(r["linear_lens"]["total_proj"] - r["outcome"]["total"]) for r in rs if r["linear_lens"]["total_proj"] is not None]
    pre = [abs(r["linear_lens"]["anchor_total_used"] - r["outcome"]["total"]) for r in rs if r["linear_lens"]["anchor_total_used"] is not None]
    pairs = [(r["linear_lens"]["home_win_prob"], r["state"]["espn_home_wp"], 1.0 if r["outcome"]["home_win"] else 0.0)
             for r in rs if r["linear_lens"]["home_win_prob"] is not None and r["state"]["espn_home_wp"] is not None]
    bl = [(p - y) ** 2 for p, _, y in pairs]; be = [(e - y) ** 2 for _, e, y in pairs]
    d = [a - b for a, b in zip(bl, be)]
    f = lambda v: f"{sum(v)/len(v):.4f}" if v else "  -  "
    ci = lambda v: "[{:.3f},{:.3f}]".format(*boot(v)) if len(v) > 1 else "-"
    print(f"{k[0]+'/'+k[1]:22} {len(rs):>4} | {f(ae):>8} {ci(ae):>15} | {f(pre):>7} | {f(bl):>9} {ci(bl):>15} | {f(be):>10} | {f(d):>15} {ci(d):>17}  (n_ml={len(pairs)})")
