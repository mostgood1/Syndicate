"""One league's soccer live_state file on the fleet disk (and its keyvalue copy if the disk file is absent): the
generated time and, per game, its status / clock / score / kickoff fields. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/soccer_live_state_peek.py mls 2026-11-22
"""
import json, os, sys

league, date = sys.argv[1], sys.argv[2]
p = os.path.expanduser(f"~/syndicate-prod/data/soccer_source/{league}/api/live_state/live_state_{date}.json")
st = os.stat(p)
d = json.load(open(p, encoding="utf-8"))
print("file_mtime_epoch", int(st.st_mtime), "keys", sorted(d)[:20])
for k in ("generatedAt", "generated_at", "updatedAt", "asOf"):
    if k in d:
        print(k, d[k])
games = d.get("games")
print("games_type", type(games).__name__, "n", len(games) if hasattr(games, "__len__") else None)
items = games.items() if isinstance(games, dict) else enumerate(games or [])
for gk, g in items:
    if isinstance(g, dict):
        keep = {k: v for k, v in g.items() if not isinstance(v, (dict, list)) or k in ("status",)}
        print(gk, json.dumps(keep)[:700])
