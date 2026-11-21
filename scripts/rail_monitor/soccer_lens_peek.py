"""Soccer live lens: which leagues it checks and which live games it holds. Read-only.

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/soccer_lens_peek.py
"""
import json, subprocess

K = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/soccer_live_lens.json"
d = json.loads(subprocess.run(["redis-cli", "--raw", "GET", K], capture_output=True, text=True, errors="replace").stdout)
for k in ("date", "generated_at", "leagues_checked", "leagues_with_games", "count", "errors"):
    print(k, json.dumps(d.get(k), default=str)[:700])
for g in d.get("games") or []:
    print("game", g.get("league"), g.get("away_team"), "@", g.get("home_team"), g.get("status_detail"), "projection" in g)
print("finals", len(d.get("finals") or []))
