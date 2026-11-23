"""Read-only: every refresh-worker / live-odds-worker log line naming `sport=<s> date=<d>` (or `date=<d>` plus the sport)
in a UTC window, overlay lines excluded unless --overlay. Prints role, time and the first 230 chars.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/grid_lines_for.py soccer 2026-11-23 2026-11-23T02:00 2026-11-23T02:20
"""
import re, subprocess, sys
sport, date, lo, hi = sys.argv[1], sys.argv[2], sys.argv[3][:16], sys.argv[4][:16]
keep_overlay = "--overlay" in sys.argv
for role in ("refresh-worker", "live-odds-worker"):
    for f in (f"logs/{role}.log.1", f"logs/{role}.log"):
        out = subprocess.run(["grep", "-a", f"date={date}", f], capture_output=True, text=True, errors="replace").stdout
        for l in out.splitlines():
            if not re.match(r"20\d\d-", l) or not (lo <= l[:16] < hi) or sport not in l:
                continue
            if "INPLAY_OVERLAY" in l and not keep_overlay:
                continue
            print(role[:4], l[11:19], l[24:254])
