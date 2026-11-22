"""Every GET /api/board/live-rail in web.log within a UTC window: time, status, user agent, duration. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/web_liverail_reqs.py 2026-11-22T22:40 2026-11-22T23:00
"""
import re, subprocess, sys

lo, hi = sys.argv[1][:16], sys.argv[2][:16]
out = subprocess.run(["grep", "-a", "GET /api/board/live-rail", "logs/web.log"], capture_output=True, text=True,
                     errors="replace").stdout
for l in out.splitlines():
    if not (lo <= l[:16] < hi):
        continue
    m = re.search(r'" (\d{3}) (\S+) "[^"]*" "([^"]*)" (\S+)$', l)
    print(l[11:23], *(m.groups() if m else (l[-120:],)))
