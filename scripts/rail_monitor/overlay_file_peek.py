"""Read-only: one sport/date in-play overlay file's written_at, rows and cards (matchup, commence, markets).

  wsl: cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/overlay_file_peek.py soccer 2026-11-23
"""
import glob, json, os, sys, collections
sport, date = sys.argv[1], sys.argv[2]
hits = [p for p in glob.glob(f"data/**/book_grid_inplay_{date}.json", recursive=True) if sport in p]
for p in hits:
    d = json.load(open(p, encoding="utf-8"))
    print(p, "mtime", os.path.getmtime(p), "written_at", d.get("written_at"), "keys", list(d.keys())[:12])
    rows = d.get("rows") or []
    c = collections.Counter((r.get("matchup"), r.get("commence_time"), r.get("game_date")) for r in rows if isinstance(r, dict))
    for k, v in c.most_common(10):
        print(" rows", v, k)
    for card in (d.get("cards") or [])[:6]:
        print(" card", card.get("matchup"), card.get("commence_time"), card.get("market"), card.get("line"), card.get("side"))
