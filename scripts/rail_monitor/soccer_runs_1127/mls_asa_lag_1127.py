"""Read-only: how current is ASA's 2026 MLS game list (the ratings source) against the fleet's own MLS live_state boxes?
One public GET to ASA /mls/games, then the fleet's finished-match boxes after 2026-10-15 by date.
WSL: nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/mls_asa_lag_1127.py"""
import glob, json, os
from collections import Counter

import requests

r = requests.get("https://app.americansocceranalysis.com/api/v1/mls/games", params={"season_name": "2026"},
                 headers={"User-Agent": "syndicate-readonly-check"}, timeout=60)
games = r.json() if r.headers.get("content-type", "").startswith("application/json") else []
print("ASA games HTTP", r.status_code, "rows", len(games))
if games:
    print("  keys", sorted(games[0].keys())[:20])
    stage = Counter(g.get("stage_name") for g in games)
    print("  by stage", dict(stage))
    played = [g for g in games if g.get("home_score") is not None]
    print("  with a score", len(played))
    late = sorted((str(g.get("date_time_utc") or "")[:10], g.get("stage_name"), g.get("home_score") is not None)
                  for g in games if str(g.get("date_time_utc") or "") >= "2026-10-15")
    print("  games dated >= 10-15 (date, stage, scored):", Counter((d, s, sc) for d, s, sc in late))
root = os.path.expanduser("~/syndicate-prod/data/soccer_source/mls/api/live_state")
fleet = Counter()
for p in sorted(glob.glob(os.path.join(root, "live_state_2026-1*.json"))):
    day = os.path.basename(p)[len("live_state_"):-5]
    if day < "2026-10-15":
        continue
    try:
        n = len(json.load(open(p)).get("match_box") or {})
    except Exception:
        continue
    if n:
        fleet[day] = n
print("fleet live_state finished boxes >= 10-15 by date:", dict(fleet), "total", sum(fleet.values()))
