"""List event names on NCAAF-mentioning log lines since a UTC time, per role log; optional grep for a team. Read-only.

  cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/ncaaf_events.py 2026-11-21T17:30 [Purdue]
"""
import collections, re, subprocess, sys

since = sys.argv[1][:19]
team = sys.argv[2] if len(sys.argv) > 2 else None
for f in ("logs/live-odds-worker.log", "logs/refresh-worker.log"):
    out = subprocess.run(["grep", "-a", "-i", "ncaaf", f], capture_output=True, text=True, errors="replace").stdout
    c = collections.Counter()
    hits = []
    for l in out.splitlines():
        if "ALL_PROCESS_MEMORY" in l or "grep" in l or not re.match(r"20\d\d-\d\d-\d\dT", l) or l[:19] < since:
            continue
        m = re.search(r"\] ([A-Z][A-Z0-9_]{5,})", l)
        c[m.group(1) if m else "?"] += 1
        if team and team.lower() in l.lower():
            hits.append(l[:400])
    print("==", f)
    for k, v in c.most_common(25):
        print(f"  {v:6d} {k}")
    if team:
        print("  lines naming", team, len(hits))
        for h in hits[-12:]:
            print("   ", h)
