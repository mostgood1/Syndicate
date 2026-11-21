"""Lines matching a regex in the role logs since a UTC time: event-name counts and the last N lines. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/grep_since.py '<regex>' 2026-11-21T18:00 [N]
"""
import collections, re, subprocess, sys

pat, since = sys.argv[1], sys.argv[2][:19]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
for f in ("logs/live-odds-worker.log", "logs/refresh-worker.log", "logs/web.log"):
    out = subprocess.run(["grep", "-a", "-E", pat, f], capture_output=True, text=True, errors="replace").stdout
    keep = [l for l in out.splitlines() if "ALL_PROCESS_MEMORY" not in l and "grep" not in l
            and re.match(r"20\d\d-\d\d-\d\dT", l) and l[:19] >= since]
    c = collections.Counter((re.search(r"\] ([A-Z][A-Z0-9_]{4,})", l) or [None, "?"])[1] for l in keep)
    print("==", f, len(keep), dict(c.most_common(12)))
    for l in keep[-n:]:
        print("   ", l[:300])
