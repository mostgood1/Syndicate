"""Layer 2 board builds by UTC hour over windows: builds, wall p50 / max, publish gap max, memory-guard refusals by stage,
board child exits / recycles; plus one sample BOARD_BUILD_TIMING line (fields). Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/board_evening.py 2026-11-22T00 2026-11-22T05 [more windows as from to pairs]
"""
import collections, datetime as dt, re, statistics as st, subprocess, sys

pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
pat = r"BOARD_BUILD_TIMING|MEMORY_GUARD_ABORT|BOARD_PROCESS_EXITED|RECYCLE_EXIT|BOARD_PROCESS_RECYCLE"
lines = []
for f in ("logs/refresh-worker.log.4", "logs/refresh-worker.log.3", "logs/refresh-worker.log.2", "logs/refresh-worker.log.1", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "-E", pat, f], capture_output=True, text=True, errors="replace").stdout
    lines += [l for l in out.splitlines() if re.match(r"20\d\d-\d\d-\d\dT", l) and "ALL_PROCESS_MEMORY" not in l]
lines.sort(key=lambda l: l[:24])
sample = None
for lo, hi in pairs:
    print("== window %s -> %s (UTC)" % (lo, hi))
    by = collections.defaultdict(lambda: {"walls": [], "ts": [], "guard": collections.Counter(), "exits": 0, "recycles": 0})
    for l in lines:
        if not (lo <= l[:13] < hi):
            continue
        h = l[:13]
        b = by[h]
        if "BOARD_BUILD_TIMING" in l:
            m = re.search(r"wall_s=([0-9.]+)", l)
            if m:
                b["walls"].append(float(m.group(1)))
                b["ts"].append(dt.datetime.fromisoformat(l[:19]))
                if sample is None and float(m.group(1)) > 400:
                    sample = l
        elif "MEMORY_GUARD_ABORT" in l:
            m = re.search(r"stage=([a-z_]+)", l)
            b["guard"][m.group(1) if m else "?"] += 1
        elif "BOARD_PROCESS_EXITED" in l:
            b["exits"] += 1
        elif "RECYCLE_EXIT" in l or "BOARD_PROCESS_RECYCLE" in l:
            b["recycles"] += 1
    prev = None
    for h in sorted(by):
        b = by[h]
        ts = b["ts"]
        gaps = [(y - x).total_seconds() for x, y in zip(([prev] if prev else []) + ts, ts)] if ts else []
        if ts:
            prev = ts[-1]
        w = b["walls"]
        print("  %sZ builds %2d wall p50 %5s max %5s | pub gap max %5s | guard %s | exits %d recycles %d" % (
            h[11:13], len(w), round(st.median(w)) if w else "-", round(max(w)) if w else "-",
            round(max(gaps)) if gaps else "-", dict(b["guard"]) or "{}", b["exits"], b["recycles"]))
if sample:
    print("sample:", sample[:1500])
