"""Read-only: a sport/date book grid's rows grouped by matchup and game state (live/final only by default).

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/grid_game_states.py soccer 2026-11-23
"""
import collections, json, os, sys
sport, date = sys.argv[1], sys.argv[2]
p = f"data/{sport}_source/data/book_grid/book_grid_{date}.json"
d = json.load(open(p, encoding="utf-8"))
print(p, "mtime", os.path.getmtime(p), "generated_at", d.get("generated_at"))
rows = d.get("rows") or d.get("grid") or []
c = collections.Counter()
info = {}
for r in rows:
    g = r.get("game") or {}
    st = str(g.get("state") or "")
    if st not in ("live", "in_progress", "final") and "--all" not in sys.argv:
        continue
    k = (r.get("matchup"), r.get("commence_time"), st)
    c[k] += 1
    info[k] = (g.get("status_token"), g.get("home_score"), g.get("away_score"), r.get("live_lane") or (r.get("projection") or {}).get("basis"))
for k, v in c.most_common(12):
    print(v, k, info[k])
