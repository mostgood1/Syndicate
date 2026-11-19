"""#844 P1/P2 sampler (read-only, fleet): does a college grid row's age now follow its FRESHEST book?

Run inside WSL with the fleet venv, from ~/Syndicate, e.g.
  cd ~/Syndicate && nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/ncal816/p844_grid_sample.py ncaab 2026-11-24
Prints one JSON line per call; call it every ~5 min through the live evening and keep the lines.

Per call, over the published grid's IN-PLAY full-game rows of the sport (book_grid_<date>.json):
  rows                  in-play full-game h2h/spreads/totals rows
  venue_rows            rows with a kalshi or polymarket cell
  p1_sportsbook_newest  venue rows whose row `updated_at` is a SPORTSBOOK-spelled stamp (no 'T')
                        -> P1: > 0 after the #844 load (0 before: a venue's 'T' stamp always won the text max)
  h2h_row_fresh         h2h rows with row age_seconds <= 120
  h2h_cell_fresh        h2h rows whose freshest cell is <= 120 s old (the true clock)
                        -> P2: h2h_row_fresh / h2h rows >= 70% on the evening, and close to h2h_cell_fresh
                           (before the fix: about 25% vs 81% of live minutes, 11-17/18)
  mismatch              rows where row age > 120 but some cell <= 120 (the defect itself; ~0 after the load)
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/Syndicate"))
from syndicate.features.shared.book_grid_artifact import select_inplay_rows  # noqa: E402

sport = sys.argv[1] if len(sys.argv) > 1 else "ncaab"
date = sys.argv[2] if len(sys.argv) > 2 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
path = os.path.expanduser(f"~/syndicate-prod/data/{sport}_source/data/book_grid/book_grid_{date}.json")
g = json.load(open(path, encoding="utf-8"))
out = {"read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sport": sport, "date": date,
       "grid_generated_at": g.get("generated_at"), "rows": 0, "venue_rows": 0, "p1_sportsbook_newest": 0,
       "h2h": 0, "h2h_row_fresh": 0, "h2h_cell_fresh": 0, "mismatch": 0}
for r in select_inplay_rows(g.get("rows") or []):
    if r.get("player_name") or str(r.get("segment") or "full") not in ("full", "full_game", "game"):
        continue
    market = str(r.get("market") or "")
    if market not in ("h2h", "spreads", "totals"):
        continue
    out["rows"] += 1
    cells = r.get("cells") or {}
    ages = [s.get("age_seconds") for c in cells.values() if isinstance(c, dict)
            for s in c.values() if isinstance(s, dict) and s.get("age_seconds") is not None]
    cell_min = min(ages) if ages else None
    row_age = r.get("age_seconds")
    if any(str(b).lower() in ("kalshi", "polymarket") for b in cells):
        out["venue_rows"] += 1
        if "T" not in str(r.get("updated_at") or "")[:11]:
            out["p1_sportsbook_newest"] += 1
    if row_age is not None and cell_min is not None and row_age > 120 >= cell_min:
        out["mismatch"] += 1
    if market == "h2h":
        out["h2h"] += 1
        out["h2h_row_fresh"] += bool(row_age is not None and row_age <= 120)
        out["h2h_cell_fresh"] += bool(cell_min is not None and cell_min <= 120)
print(json.dumps(out), flush=True)
