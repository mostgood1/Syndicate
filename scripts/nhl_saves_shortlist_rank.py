"""READ-ONLY: rank NHL SAVES candidates within their game in the pre-publication population ledger
(`reports/intelligence/opportunity_population/<date>__nhl__part*.jsonl`, every candidate a build priced, recorded
once per side per day BEFORE select_shortlist cuts). k = event|market|player|segment|side|line, sc = score,
vp = value %, ev = EV, ss = skill status. The shortlist seats at most 6 rows per game (SHORTLIST_ROWS_PER_GAME)."""
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

date = sys.argv[1]
market = (sys.argv[2] if len(sys.argv) > 2 else "SAVES").upper()
files = sorted(glob.glob(os.path.expanduser(f"~/syndicate-prod/data/reports/intelligence/opportunity_population/{date}__nhl__part*.jsonl")))
rows = [json.loads(line) for f in files for line in open(f, encoding="utf-8")]
for r in rows:
    p = r["k"].split("|") + [""] * 6
    r["_ev"], r["_mk"], r["_pl"], r["_side"], r["_ln"] = p[0], p[1], p[2], p[4], p[5]
by = defaultdict(list)
for r in rows:
    by[r["_ev"]].append(r)
score = lambda r: r.get("sc") if r.get("sc") is not None else -9.0
out, sixth_all = [], []
for ev, rs in by.items():
    rs.sort(key=score, reverse=True)
    sixth = score(rs[5]) if len(rs) > 5 else None
    if sixth is not None:
        sixth_all.append(sixth)
    for i, r in enumerate(rs):
        if r["_mk"].upper() == market:
            out.append((f"{str(r.get('ht'))[:12]}", r["_pl"][:20], r["_ln"], r["_side"], i + 1, len(rs), r.get("sc"),
                        r.get("vp"), r.get("ev"), r.get("ss"), sixth, r.get("t")))
print(f"{date}: NHL candidates {len(rows)} in {len(by)} games; {market} candidates {len(out)}")
for o in sorted(out, key=lambda o: o[4]):
    print("%-12s %-20s %-5s %-5s rank %3d/%-3d sc %-8s vp %-8s ev %-8s skill %-10s game 6th sc %-8s seen %s" % o)
if sixth_all:
    print(f"per-game 6th-best score: median {statistics.median(sixth_all):.4f}, range {min(sixth_all):.4f}..{max(sixth_all):.4f}")
others = [r for r in rows if r["_mk"].upper() not in (market,) and r.get("kind") == "prop"]
if others:
    print(f"other NHL prop candidates: median score {statistics.median(score(r) for r in others):.4f} (n={len(others)})")
