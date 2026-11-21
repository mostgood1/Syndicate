"""live_lens_loop TICK_COMPLETE: per sport, True/False counts since a UTC time, and the times soccer came back True. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/lens_loop_soccer.py 2026-11-21T17:00 [sport]
"""
import collections, re, subprocess, sys

since = sys.argv[1][:19]
sport = sys.argv[2] if len(sys.argv) > 2 else "soccer"
out = subprocess.run(["grep", "-a", "live_lens_loop\\] TICK_COMPLETE", "logs/live-odds-worker.log"], capture_output=True, text=True, errors="replace").stdout
c = collections.Counter()
true_at, n = [], 0
for l in out.splitlines():
    if "ALL_PROCESS_MEMORY" in l or not re.match(r"20\d\d-", l) or l[:19] < since:
        continue
    n += 1
    for s, v in re.findall(r"'(\w+)': (True|False)", l):
        c[(s, v)] += 1
        if s == sport and v == "True":
            true_at.append(l[11:19])
print("ticks", n, dict(sorted(c.items())))
print(sport, "True at", true_at)
