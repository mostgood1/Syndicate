#!/bin/bash
# Read-only, nice 19: gaps between successive soccer live-lens writes (TICK_COMPLETE soccer True) on live-odds-worker,
# over the retained log, with the soccer low-headroom skip count in each gap. A gap only matters while a game is in play;
# the reader cannot see that from these lines alone, so it prints the gap distribution and every gap over 300 s.
cd ~/syndicate-prod/logs || exit 0
tail -n 3000000 live-odds-worker.log | grep -a -E "TICK_COMPLETE|LIVE_LENS_TICK_DIAG sport=soccer" \
  | awk '/TICK_COMPLETE/ { if ($0 ~ /.soccer.: True/) print $1, "W"; next } { print $1, "S" }' > /tmp/stg1127.txt
echo "first $(head -1 /tmp/stg1127.txt) last $(tail -1 /tmp/stg1127.txt) lines $(wc -l < /tmp/stg1127.txt)"
python3 - <<'PY'
from datetime import datetime
rows = [l.split() for l in open("/tmp/stg1127.txt")]
def t(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
gaps, prev, skips = [], None, 0
for ts, k in rows:
    if k == "S":
        skips += 1
        continue
    now = t(ts)
    if prev is not None:
        gaps.append(((now - prev).total_seconds(), prev, skips))
    prev, skips = now, 0
v = sorted(g for g, _, _ in gaps)
n = len(v)
print("writes", n + 1, "gaps", n)
q = lambda f: v[min(n - 1, int(f * n))]
print("gap p50", round(q(0.5)), "p90", round(q(0.9)), "p95", round(q(0.95)), "p99", round(q(0.99)), "max", round(v[-1]))
clean = sorted(g for g, _, s in gaps if s == 0)
m = len(clean)
print("gaps with NO gate skip inside:", m, "p50", round(clean[m // 2]), "p95", round(clean[min(m - 1, int(.95 * m))]),
      "p99", round(clean[min(m - 1, int(.99 * m))]), "max", round(clean[-1]))
for lo, hi in ((0, 120), (120, 180), (180, 240), (240, 300), (300, 450), (450, 600), (600, 900), (900, 1e9)):
    print(f"  [{lo}, {hi}) s: all {sum(lo <= g < hi for g, _, _ in gaps)}  no-skip {sum(lo <= g < hi for g, _, s in gaps if s == 0)}")
print("no-skip gaps over 240 s (start, gap):")
for g, p, s in sorted(gaps, key=lambda x: x[1]):
    if s == 0 and g > 240:
        print("  ", p.isoformat()[:19], round(g))
PY
