"""Read-only, nice 19: the Understat outage marker, and the age of every soccer file a failing step would refresh
(history/matches_2026.csv, players/players_2026.csv, teams_2026.csv) per league, plus the newest recommendations file
per league and the bundesliga 2026-12-04 unit the fleet-watcher quoted. WSL:
  nice -n 19 python3 /mnt/c/tmp/railmon/soccer_stale_files_1127.py"""
import glob, json, os, time

root = os.path.expanduser("~/syndicate-prod/data/soccer_source")
now = time.time()
st = os.path.join(root, "_understat_status.json")
print("_understat_status.json:", (open(st).read()[:1500] if os.path.exists(st) else "ABSENT"))
fmt = lambda p: (f"{(now - os.path.getmtime(p)) / 3600:7.1f} h  {time.strftime('%m-%d %H:%MZ', time.gmtime(os.path.getmtime(p)))}"
                 if os.path.exists(p) else "   absent")
for lg in sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))):
    rows = []
    for rel in ("history/matches_2026.csv", "players/players_2026.csv", "teams/teams_2026.csv", "history/teams_2026.csv"):
        p = os.path.join(root, lg, rel)
        if os.path.exists(p):
            rows.append(f"{rel}: {fmt(p)}")
    recs = sorted(glob.glob(os.path.join(root, lg, "api", "recommendations", "recommendations_2026-1*.json")))
    newest = max(recs, key=os.path.getmtime) if recs else None
    if rows or newest:
        print(f"{lg}:")
        for r in rows:
            print("   ", r)
        if newest:
            print("    newest recommendations:", os.path.basename(newest), fmt(newest), f"({len(recs)} files)")
p = os.path.join(root, "bundesliga", "api", "recommendations", "recommendations_2026-12-04.json")
print("bundesliga recommendations_2026-12-04.json:", fmt(p))
