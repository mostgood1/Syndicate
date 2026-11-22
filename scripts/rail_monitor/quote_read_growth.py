"""BOOK_GRID_QUOTE_READ per sport by UTC hour: rows / kept (last of the hour) and reparse seconds (sum). Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/quote_read_growth.py 2026-11-21T12 2026-11-22T06 [sport,sport]
"""
import collections, re, subprocess, sys

lo, hi = sys.argv[1][:13], sys.argv[2][:13]
want = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
lines = []
for f in ("logs/refresh-worker.log.2", "logs/refresh-worker.log.1", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "BOOK_GRID_QUOTE_READ", f], capture_output=True, text=True, errors="replace").stdout
    lines += [l for l in out.splitlines() if re.match(r"20\d\d-", l) and "ALL_PROCESS_MEMORY" not in l and lo <= l[:13] < hi]
lines.sort(key=lambda l: l[:24])
by = collections.defaultdict(lambda: {"rows": None, "kept": None, "reparse": 0.0, "n": 0})
sports = set()
for l in lines:
    m = re.search(r"sport=(\w+).*? rows=(\d+) kept=(\d+) read_s=([0-9.]+) reparse_s=([0-9.]+)", l)
    if not m:
        continue
    sp = m.group(1)
    if want and sp not in want:
        continue
    sports.add(sp)
    b = by[(l[:13], sp)]
    b["rows"], b["kept"] = int(m.group(2)), int(m.group(3))
    b["reparse"] += float(m.group(5))
    b["n"] += 1
for sp in sorted(sports):
    print("==", sp)
    for (h, s), b in sorted(by.items()):
        if s == sp:
            print("  %sZ reads %3d rows %8d kept %7d reparse_s sum %6.1f" % (h[5:13], b["n"], b["rows"], b["kept"], b["reparse"]))
