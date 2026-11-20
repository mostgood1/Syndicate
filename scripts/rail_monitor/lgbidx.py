"""NHL (or any sport) live join coverage over time: index_why live_resim vs pregame_only, and full_games.

  cd ~/syndicate-prod && python3 /mnt/c/tmp/railmon/lgbidx.py <sport> <from_utc> <to_utc> [every_n]
"""
import glob, json, re, subprocess, sys

sport, a, b = sys.argv[1], sys.argv[2][:19], sys.argv[3][:19]
every = int(sys.argv[4]) if len(sys.argv) > 4 else 6
rows = []
for f in sorted(glob.glob("logs/refresh-worker.log*")):
    out = subprocess.run(["grep", "-a", f"LIVE_GAMELINE_BUILD sport={sport} ", f], capture_output=True, text=True, errors="replace").stdout
    for l in out.splitlines():
        if "ALL_PROCESS_MEMORY" in l or not (a <= l[:19] < b):
            continue
        m = re.search(r"index_why=(\{.*\})", l)
        try:
            iw = json.loads(m.group(1)) if m else {}
        except Exception:
            iw = {}
        fg = re.search(r"full_games=(\d+)", l)
        rows.append((l[:19], iw.get("games_in_snapshot"), (iw.get("sources_seen") or {}).get("live_resim"),
                     (iw.get("sources_seen") or {}).get("pregame_only"), fg.group(1) if fg else None))
rows = sorted(set(rows))
for r in rows[::every]:
    print(r[0], "snapshot", r[1], "live_resim", r[2], "pregame_only", r[3], "full_games", r[4])
print("builds", len(rows))
