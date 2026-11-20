"""#850 P7 counter: MEMORY_GUARD_ABORT per UTC hour, board child exits (rc), recycles, and the longest BOARD_BUILD_TIMING gap.

  cd ~/syndicate-prod && python3 /mnt/c/tmp/railmon/p7count.py <from_utc> [to_utc]
"""
import collections, glob, re, subprocess, sys, datetime as dt

a = sys.argv[1][:19]
b = sys.argv[2][:19] if len(sys.argv) > 2 else "9999"
pat = "MEMORY_GUARD_ABORT|BOARD_PROCESS_EXITED|RECYCLE_EXIT|BOARD_PROCESS_RECYCLE|BOARD_BUILD_TIMING|Fatal Python error|BOARD_PROCESS_POST_BUILD_CHECK"
lines = []
for f in sorted(glob.glob("logs/refresh-worker.log*")):
    out = subprocess.run(["grep", "-aE", pat, f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if "ALL_PROCESS_MEMORY" in l or not re.match(r"20\d\d-\d\d-\d\dT", l):
            continue
        if a <= l[:19] < b:
            lines.append(l)
lines = sorted(set(lines))
per_hour = collections.Counter(l[:13] for l in lines if "MEMORY_GUARD_ABORT" in l)
exits = [re.search(r"rc=(-?\d+)", l).group(1) for l in lines if "BOARD_PROCESS_EXITED" in l and re.search(r"rc=(-?\d+)", l)]
recycles = [l[:19] + " " + (re.search(r"reason=(\S+)", l).group(1) if re.search(r"reason=(\S+)", l) else "?") for l in lines if "RECYCLE_EXIT" in l]
fatal = sum(1 for l in lines if "Fatal Python error" in l)
ts = [dt.datetime.fromisoformat(l[:19]) for l in lines if "BOARD_BUILD_TIMING" in l]
gaps = sorted(((y - x).total_seconds(), x.strftime("%H:%M:%SZ")) for x, y in zip(ts, ts[1:]))
print("window", a, "->", b)
print("MEMORY_GUARD_ABORT per UTC hour", dict(sorted(per_hour.items())), "total", sum(per_hour.values()))
print("BOARD_PROCESS_EXITED rc", exits, "| RECYCLE_EXIT", recycles, "| Fatal Python error", fatal)
held = collections.Counter((re.search(r"held=(\S+)", l).group(1) if re.search(r"held=(\S+)", l) else "fired")
                           for l in lines if "BOARD_PROCESS_POST_BUILD_CHECK" in l)
recyc_reason = collections.Counter((re.search(r"reason=(\S+)", l).group(1) if re.search(r"reason=(\S+)", l) else "?")
                                   for l in lines if "BOARD_PROCESS_RECYCLE" in l)
print("POST_BUILD_CHECK by held reason", dict(held), "| BOARD_PROCESS_RECYCLE by reason", dict(recyc_reason))
print("BOARD_BUILD_TIMING builds", len(ts), "| longest gaps", [(int(g), t) for g, t in gaps[-3:]], "| gaps > 900 s", sum(1 for g, _ in gaps if g > 900))
