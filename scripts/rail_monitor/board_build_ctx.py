"""The refresh-worker lines in the N seconds before one BOARD_BUILD_TIMING line at/after a UTC time (minus memory and
process-enum noise), to see what a board build logs about its size. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/board_build_ctx.py 2026-11-22T02:00 [seconds_before]
"""
import datetime as dt, re, subprocess, sys

at = sys.argv[1][:19]
back = float(sys.argv[2]) if len(sys.argv) > 2 else 420
f = "logs/refresh-worker.log.1" if at < "2026-11-22T06:31" else "logs/refresh-worker.log"
out = subprocess.run(["grep", "-a", "-n", "BOARD_BUILD_TIMING", f], capture_output=True, text=True, errors="replace").stdout
target = None
for l in out.splitlines():
    n, _, rest = l.partition(":")
    if re.match(r"20\d\d-", rest) and rest[:19] >= at:
        target = (int(n), rest[:19])
        break
if not target:
    sys.exit("no build line")
t1 = dt.datetime.fromisoformat(target[1])
t0 = (t1 - dt.timedelta(seconds=back)).isoformat()[:19]
start = max(1, target[0] - 60000)
chunk = subprocess.run(["sed", "-n", "%d,%dp" % (start, target[0]), f], capture_output=True, text=True, errors="replace").stdout
skip = ("ALL_PROCESS_MEMORY", "PROCESS_ENUM_DEBUG", "KEYVALUE_WRITE_LARGE", "MALLOC_TRIM", "MEMORY_WATCHDOG", "PROCESS_MEMORY")
for l in chunk.splitlines():
    if not re.match(r"20\d\d-", l) or l[:19] < t0 or any(s in l for s in skip):
        continue
    if re.search(r"intelligence_state|layer2|board|BUILD_SPAN|candidate|shortlist|rows=|cards=", l, re.I):
        print(l[:260])
