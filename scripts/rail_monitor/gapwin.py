"""Print live-odds-worker log lines in a UTC window (skipping ALL_PROCESS_MEMORY), first 2 per distinct prefix.

  cd ~/syndicate-prod && python3 /mnt/c/tmp/railmon/gapwin.py <from> <to> [logfile] [grep-substring]
"""
import collections, sys

a, b = sys.argv[1], sys.argv[2]
f = sys.argv[3] if len(sys.argv) > 3 else "logs/live-odds-worker.log"
sub = sys.argv[4] if len(sys.argv) > 4 else ""
seen = collections.Counter()
n = 0
for line in open(f, encoding="utf-8", errors="replace"):
    t = line[:24]
    if t < a or t > b or "ALL_PROCESS_MEMORY" in line or (sub and sub not in line):
        continue
    n += 1
    key = line[25:85]
    seen[key] += 1
    if seen[key] <= 2:
        print(line[:240].rstrip())
print("lines in window:", n, "distinct prefixes:", len(seen))
