"""Soccer live-odds activity in a UTC window: the live-odds-worker's soccer live autorun launches / failures / finishes
and any line naming MLS, plus the refresh-worker's soccer overlay rows_inplay. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/soccer_live_window.py 2026-11-22T23:15 2026-11-22T23:50
"""
import re, subprocess, sys

lo, hi = sys.argv[1][:16], sys.argv[2][:16]
pat = r"SOCCER_LIVE|soccer-live|soccer_live|poll_soccer_live_state|league=mls|leagues=.*mls|LIVE_ODDS_WORKER_(BOOT|START|RECYCLE)|SELF_RECYCLE|recycl"
for f in ("logs/live-odds-worker.log.1", "logs/live-odds-worker.log"):
    out = subprocess.run(["grep", "-a", "-E", pat, f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if re.match(r"20\d\d-", l) and "ALL_PROCESS_MEMORY" not in l and lo <= l[:16] < hi:
            print("LOW", l[11:19], l[24:330])
