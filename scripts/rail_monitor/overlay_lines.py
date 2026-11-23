"""Every INPLAY_OVERLAY line for one sport in a UTC window (refresh-worker log + .log.1), with the gap to the previous
one. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/overlay_lines.py soccer 2026-11-22T23:00 2026-11-23T00:00
"""
import datetime as dt, re, subprocess, sys

sport, lo, hi = sys.argv[1], sys.argv[2][:16], sys.argv[3][:16]
out = "".join(subprocess.run(["grep", "-a", f"INPLAY_OVERLAY sport={sport}", f], capture_output=True, text=True,
                             errors="replace").stdout for f in ("logs/refresh-worker.log.1", "logs/refresh-worker.log"))
prev = None
for l in out.splitlines():
    if not re.match(r"20\d\d-", l) or "ALL_PROCESS_MEMORY" in l or not (lo <= l[:16] < hi):
        continue
    t = dt.datetime.strptime(l[:19], "%Y-%m-%dT%H:%M:%S")
    gap = (t - prev).total_seconds() if prev else None
    prev = t
    print(l[11:19], "gap" if gap is None else f"gap {gap:6.0f}", l[24:260])
