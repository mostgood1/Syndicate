#!/bin/bash
# Read-only, nice 19: the lane age a soccer lane-age gate WOULD have seen at each soccer live join build with games in
# play = build time minus the last soccer live-lens write (TICK_COMPLETE soccer True) before it. Every retained, rotated
# live-odds-worker / refresh-worker log. A gate skip ([LIVE_LENS_TICK_DIAG] sport=soccer ... low_headroom) between the
# write and the build marks the build as "gated". Writes are TICK_COMPLETE times; the lens is stamped a little earlier
# inside the tick, so these ages run a few seconds to a minute LOW.
cd ~/syndicate-prod/logs || exit 0
for f in live-odds-worker.log.5 live-odds-worker.log.4 live-odds-worker.log.3 live-odds-worker.log.2 live-odds-worker.log.1 live-odds-worker.log; do
  [ -f "$f" ] && grep -a -E "TICK_COMPLETE|LIVE_LENS_TICK_DIAG\] sport=soccer" "$f"
done | awk '/TICK_COMPLETE/ { if ($0 ~ /.soccer.: True/) print $1, "W"; next } { print $1, "S" }' > /tmp/sla_w.txt
for f in refresh-worker.log.3 refresh-worker.log.2 refresh-worker.log.1 refresh-worker.log; do
  [ -f "$f" ] && grep -a "LIVE_GAMELINE_JOIN sport=soccer" "$f"
done | sed -E 's/^([^ ]+) .* index=([0-9]+) .* priceable=([0-9A-Za-z]+) .*/\1 J \2 \3/' > /tmp/sla_j.txt
echo "writes+skips $(wc -l < /tmp/sla_w.txt) ($(head -1 /tmp/sla_w.txt | cut -c1-19) .. $(tail -1 /tmp/sla_w.txt | cut -c1-19)); joins $(wc -l < /tmp/sla_j.txt) ($(head -1 /tmp/sla_j.txt | cut -c1-19) .. $(tail -1 /tmp/sla_j.txt | cut -c1-19))"
python3 - <<'PY'
from datetime import datetime
def t(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
ev = []
for l in open("/tmp/sla_w.txt"):
    p = l.split()
    if len(p) == 2: ev.append((t(p[0]), p[1], 0, 0))
w0 = ev[0][0] if ev else None
for l in open("/tmp/sla_j.txt"):
    p = l.split()
    if len(p) == 4 and p[1] == "J" and p[2].isdigit() and int(p[2]) > 0:
        pr = int(p[3]) if p[3].isdigit() else 0
        ev.append((t(p[0]), "J", int(p[2]), pr))
ev.sort(key=lambda x: x[0])
last_w, skipped, rows = None, False, []
for ts, k, idx, pr in ev:
    if k == "W": last_w, skipped = ts, False
    elif k == "S": skipped = True
    elif last_w is not None and ts >= w0:
        rows.append(((ts - last_w).total_seconds(), skipped, ts, idx, pr))
def dist(name, v):
    v = sorted(v); n = len(v)
    if not n: print(name, "n 0"); return
    q = lambda f: round(v[min(n - 1, int(f * n))])
    print(f"{name}: n {n} p50 {q(.5)} p90 {q(.9)} p95 {q(.95)} p99 {q(.99)} max {round(v[-1])}")
dist("all builds with games in play", [a for a, *_ in rows])
dist("  no gate skip since the write", [a for a, s, *_ in rows if not s])
dist("  gate skipped since the write", [a for a, s, *_ in rows if s])
print("builds over the ceilings, all / no-skip / priceable rows on them:")
for c in (300, 450, 600, 900, 1200, 1800):
    over = [r for r in rows if r[0] > c]
    print(f"  > {c} s: {len(over)} / {sum(1 for r in over if not r[1])} / priceable rows {sum(r[4] for r in over)}"
          f" (of {sum(r[4] for r in rows)} in all {len(rows)} builds)")
print("no-skip builds over 450 s:")
for a, s, ts, idx, pr in rows:
    if not s and a > 450: print("  ", ts.isoformat()[:19], round(a), "s games", idx, "priceable", pr)
PY
