"""Each BOARD_BUILD_TIMING against the latest BOOK_GRID_QUOTE_READ `kept` per sport at that moment (summed over
sports), in a UTC window: pearson r, and wall by kept-rows bucket. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/kept_vs_wall.py 2026-11-21T06 2026-11-22T06
"""
import collections, re, statistics as st, subprocess, sys

lo, hi = sys.argv[1][:13], sys.argv[2][:13]
lines = []
for f in ("logs/refresh-worker.log.2", "logs/refresh-worker.log.1", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "-E", "BOOK_GRID_QUOTE_READ|BOARD_BUILD_TIMING", f], capture_output=True, text=True,
                         errors="replace").stdout
    lines += [l for l in out.splitlines() if re.match(r"20\d\d-", l) and "ALL_PROCESS_MEMORY" not in l and lo <= l[:13] < hi]
lines.sort(key=lambda l: l[:24])
kept = {}
pts = []
for l in lines:
    if "BOOK_GRID_QUOTE_READ" in l:
        m = re.search(r"sport=(\w+).*? kept=(\d+)", l)
        # incremental reads of a SHARD (a few hundred rows) also print; keep the per-sport running max of the date
        if m:
            sp, k = m.group(1), int(m.group(2))
            if k >= 0.5 * kept.get(sp, 0):
                kept[sp] = k
    else:
        w = re.search(r"wall_s=([0-9.]+)", l)
        if w and kept:
            pts.append((l[:19], float(w.group(1)), sum(kept.values())))
print("builds", len(pts))
xs, ys = [p[2] / 1000 for p in pts], [p[1] for p in pts]
mx, my = st.mean(xs), st.mean(ys)
r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / ((sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5)
print("pearson r(total kept quote rows, wall) = %.2f" % r)
b = collections.defaultdict(list)
for t, w, k in pts:
    b[int(k / 50000) * 50] .append(w)
for k in sorted(b):
    print("  kept %3d-%3dk: builds %3d wall p50 %4.0f max %4.0f" % (k, k + 50, len(b[k]), st.median(b[k]), max(b[k])))
