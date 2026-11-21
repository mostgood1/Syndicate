"""BOOK_GRID_TICK cadence (refresh-worker log) in a UTC window: tick count, gap median / p90 / max, build seconds. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/gridcad.py 2026-11-21T18:00 2026-11-21T21:00
"""
import datetime as dt, re, statistics as st, subprocess, sys

lo, hi = sys.argv[1][:19], sys.argv[2][:19]
ts, secs = [], []
for f in ("logs/refresh-worker.log.1", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "BOOK_GRID_TICK", f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if "ALL_PROCESS_MEMORY" in l or "grep" in l or not re.match(r"20\d\d-\d\d-\d\dT", l) or not (lo <= l[:19] <= hi):
            continue
        ts.append(l[:19])
        m = re.search(r"(?:elapsed|build|wall)[a-z_]*=([0-9.]+)", l)
        if m:
            secs.append(float(m.group(1)))
ts = sorted(set(ts))
pts = [dt.datetime.fromisoformat(t) for t in ts]
gaps = sorted((b - a).total_seconds() for a, b in zip(pts, pts[1:]))
print("BOOK_GRID_TICK", len(ts), "ticks", lo, "->", hi)
if gaps:
    print("gap median", round(st.median(gaps)), "p90", round(gaps[int(0.9 * (len(gaps) - 1))]), "max", round(gaps[-1]),
          "over 240 s", sum(1 for g in gaps if g > 240), "over 300 s", sum(1 for g in gaps if g > 300))
if secs:
    print("build s median", round(st.median(secs), 1), "max", round(max(secs), 1))
sample = subprocess.run(["grep", "-a", "-m", "1", "BOOK_GRID_TICK", "logs/refresh-worker.log"], capture_output=True, text=True, errors="replace").stdout
print("sample", sample[:260])
