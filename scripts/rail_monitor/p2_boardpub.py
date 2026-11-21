"""P2: today-board publication gaps (BOARD_BUILD_TIMING line times, refresh-worker log) in a UTC window. Read-only.

  cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p2_boardpub.py 2026-11-20T23:30 2026-11-21T04:30
"""
import datetime as dt, re, statistics as st, subprocess, sys

lo, hi = sys.argv[1], sys.argv[2]
lines = []
for f in ("logs/refresh-worker.log.1", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "BOARD_BUILD_TIMING", f], capture_output=True, text=True, errors="replace").stdout
    lines += [l for l in out.splitlines() if "ALL_PROCESS_MEMORY" not in l and "grep" not in l]
# one gap either side of the window, so a gap that straddles an edge is seen
ts = sorted({l[:19] for l in lines if re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", l)})
inside = [t for t in ts if lo <= t <= hi]
before = [t for t in ts if t < lo][-1:]
after = [t for t in ts if t > hi][:1]
pts = [dt.datetime.fromisoformat(t) for t in before + inside + after]
gaps = [((b - a).total_seconds(), a.isoformat(), b.isoformat()) for a, b in zip(pts, pts[1:])]
g = [x[0] for x in gaps]
print("publications in window", len(inside), "gaps", len(g))
if g:
    print("median", round(st.median(g)), "max", round(max(g)), "over 1800", sum(1 for x in g if x > 1800), "over 600", sum(1 for x in g if x > 600))
    for x in sorted(gaps, reverse=True)[:5]:
        print("  gap", round(x[0]), x[1], "->", x[2])
for l in lines:
    if "2026-11-21T01:1" <= l[:19] <= "2026-11-21T02:00":
        print(" ", l[:300])
