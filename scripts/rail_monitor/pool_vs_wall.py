"""Board build wall against the candidate pool's size: each BOARD_BUILD_TIMING joined to the CANDIDATE_POOL_CACHE line
just before it (pool_json_bytes), summarised per window. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/pool_vs_wall.py 2026-11-21T00 2026-11-21T05 ...
"""
import re, statistics as st, subprocess, sys

pairs = list(zip(sys.argv[1::2], sys.argv[2::2]))
lines = []
for f in ("logs/refresh-worker.log.4", "logs/refresh-worker.log.3", "logs/refresh-worker.log.2", "logs/refresh-worker.log.1",
          "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "-E", "BOARD_BUILD_TIMING|CANDIDATE_POOL_CACHE", f], capture_output=True, text=True,
                         errors="replace").stdout
    lines += [l for l in out.splitlines() if re.match(r"20\d\d-\d\d-\d\dT", l) and "ALL_PROCESS_MEMORY" not in l]
lines.sort(key=lambda l: l[:24])
joined, pool = [], None
for l in lines:
    if "CANDIDATE_POOL_CACHE" in l:
        m = re.search(r"pool_json_bytes=(\d+)", l)
        pool = int(m.group(1)) if m else None
    elif "BOARD_BUILD_TIMING" in l:
        w = re.search(r"wall_s=([0-9.]+)", l)
        c = re.search(r"cpu_s=([0-9.]+)", l)
        if w and pool:
            joined.append((l[:19], float(w.group(1)), float(c.group(1)) if c else None, pool))
        pool = None
print("joined builds", len(joined))
allw = []
for lo, hi in pairs:
    sel = [j for j in joined if lo <= j[0][:13] < hi]
    if not sel:
        print("%s..%s none" % (lo, hi))
        continue
    mb = [j[3] / 1e6 for j in sel]
    w = [j[1] for j in sel]
    cpu_per_mb = [j[2] / (j[3] / 1e6) for j in sel if j[2]]
    print("%s..%s builds %3d | pool MB p50 %5.1f max %5.1f | wall p50 %4.0f max %4.0f | cpu s per pool MB p50 %.1f" % (
        lo, hi, len(sel), st.median(mb), max(mb), st.median(w), max(w), st.median(cpu_per_mb)))
# correlation over every joined build
if len(joined) > 5:
    xs = [j[3] / 1e6 for j in joined]
    ys = [j[1] for j in joined]
    mx, my = st.mean(xs), st.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = cov / ((sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5)
    print("all builds: pearson r(pool MB, wall) = %.2f over n %d" % (r, len(joined)))
