"""Every BOARD_BUILD_TIMING line (wall, cpu) in a UTC window, plus the refresh-worker boot lines in it. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/walls_list.py 2026-11-21T15:00 2026-11-21T19:00
"""
import re, subprocess, sys

lo, hi = sys.argv[1][:16], sys.argv[2][:16]
pat = r"BOARD_BUILD_TIMING|REFRESH_WORKER_BOOT|run_refresh_worker.*(starting|boot)|WORKER_BOOT|refresh_worker\] (start|boot)"
for f in ("logs/refresh-worker.log.2", "logs/refresh-worker.log.1", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "-E", pat, f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if re.match(r"20\d\d-", l) and "ALL_PROCESS_MEMORY" not in l and lo <= l[:16] < hi:
            m = re.search(r"wall_s=([0-9.]+) cpu_s=([0-9.]+)", l)
            print(l[11:19], ("wall %6s cpu %6s" % m.groups()) if m else l[24:200])
