"""#851 P6: ODDS_SWEEP_LAUNCHED lines and per-sport sweeps in a UTC window (live-odds-worker log). Read-only.

  cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p851_sweepcount.py 2026-11-20T23:59:48 2026-11-21T05:00:13
"""
import collections, re, subprocess, sys

lo, hi = sys.argv[1], sys.argv[2]
out = subprocess.run(["grep", "-a", "ODDS_SWEEP_LAUNCHED", "logs/live-odds-worker.log"],
                     capture_output=True, text=True, errors="replace").stdout
lines = [l for l in out.splitlines() if "ALL_PROCESS_MEMORY" not in l and lo <= l[:19] <= hi]
print("lines", len(lines))
if lines:
    print("sample", lines[0][:400])
per = collections.Counter()
for l in lines:
    m = re.search(r"sports?=(\S+)", l)
    if m:
        for s in re.split(r"[,|]", m.group(1).strip("[]'\"")):
            if s:
                per[s.strip("'\" ")] += 1
print("per_sport", dict(sorted(per.items())), "sum", sum(per.values()))
print("by_date", dict(collections.Counter((re.search(r"date=(\S+)", l) or [None, None])[1] for l in lines)))
