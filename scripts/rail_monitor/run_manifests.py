"""Refresh runs of one slate date from the keyvalue store (Redis keys ...reports/refresh_status/<date>/*/refresh_status_manifest.json),
filtered by oddsSports / oddsPhase and optionally lane: run length, how many were alive at once, and each launch that
started while another run of the SAME lane was still alive. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/run_manifests.py 2026-11-21 soccer live [lane|any] [since_utc]
"""
import collections, datetime as dt, json, os, subprocess, sys

date, sports, phase = sys.argv[1], sys.argv[2], sys.argv[3]
want_lane = sys.argv[4] if len(sys.argv) > 4 else "any"
since = sys.argv[5] if len(sys.argv) > 5 else ""
PREFIX = "syndicate:refresh-state:"
pattern = PREFIX + "*/reports/refresh_status/%s/*/refresh_status_manifest.json" % date
paths = sorted(set(subprocess.run(["redis-cli", "--raw", "--scan", "--pattern", pattern], capture_output=True, text=True).stdout.split()))


def ts(v):
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception:
        return None


rows = []
for path in paths:
    try:
        m = json.loads(subprocess.run(["redis-cli", "--raw", "GET", path], capture_output=True, text=True, errors="replace").stdout)
    except Exception:
        continue
    if not isinstance(m, dict):
        continue
    s = m.get("oddsSports")
    if isinstance(s, list):
        s = ",".join(s)
    if str(s) != sports or str(m.get("oddsPhase")) != phase:
        continue
    if want_lane != "any" and m.get("lane") != want_lane:
        continue
    a, b = ts(m.get("generatedAt")), ts(m.get("finishedAt"))
    if a is None or (since and a.strftime("%Y-%m-%dT%H:%M") < since):
        continue
    rows.append({"stamp": os.path.basename(os.path.dirname(path)), "lane": m.get("lane"), "a": a, "b": b, "state": m.get("state"),
                 "exit": m.get("exitCode"), "svc": m.get("launcherServiceId"), "pid": m.get("pid")})
rows.sort(key=lambda r: r["a"])
print("manifest keys scanned", len(paths), "| runs matching", len(rows), "| lane filter", want_lane)
print("by lane", dict(collections.Counter(r["lane"] for r in rows)))
print("by state", dict(collections.Counter((r["lane"], r["state"], r["exit"]) for r in rows)))
print("by launcher service", dict(collections.Counter((r["lane"], r["svc"]) for r in rows)))
done = [r for r in rows if r["b"] is not None]
secs = sorted((r["b"] - r["a"]).total_seconds() for r in done)
if secs:
    print("seconds: median %.0f p90 %.0f max %.0f (n %d)" % (secs[len(secs) // 2], secs[int(0.9 * (len(secs) - 1))], secs[-1], len(secs)))
for lane in sorted(set(r["lane"] for r in rows)):
    lr = [r for r in done if r["lane"] == lane]
    overlaps = []
    for i, r in enumerate(lr):
        alive = [q for q in lr[:i] if q["b"] > r["a"]]
        if alive:
            overlaps.append((r, alive))
    events = sorted([(r["a"], 1) for r in lr] + [(r["b"], -1) for r in lr])
    cur = best = 0
    best_at, over = None, 0.0
    last = None
    for t, d in events:
        if last is not None and cur >= 2:
            over += (t - last).total_seconds()
        cur += d
        last = t
        if cur > best:
            best, best_at = cur, t
    print()
    print("lane %s: runs %d, launched while a same-lane run was alive %d, max alive at once %d at %s, seconds with 2+ alive %.0f" % (
        lane, len(lr), len(overlaps), best, best_at.strftime("%H:%M:%SZ") if best_at else None, over))
    by_hour = collections.Counter(r["a"].strftime("%H") for r, _ in overlaps)
    print("   overlapping launches by UTC hour", dict(sorted(by_hour.items())))
    for r, alive in overlaps[:8]:
        print("   %s launched %s (%.0f s, %s) while alive: %s" % (r["stamp"], r["a"].strftime("%H:%M:%S"), (r["b"] - r["a"]).total_seconds(), r["state"],
              ", ".join("%s %s-%s %s" % (q["stamp"], q["a"].strftime("%H:%M:%S"), q["b"].strftime("%H:%M:%S"), q["state"]) for q in alive)))
