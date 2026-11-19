"""Build the dashboard's two results files from local inputs (read-only sources):

- rail_results.json: rail MODEL != LINE flags graded at first sighting, per day and per scope
  (all, sport, market), from the monitor's nightly grade outputs in C:\\tmp\\railmon.
- board_results.json: per day and sport, the fleet's 28-day rolling results for the whole board, the
  lines published to the shortlist, and the portfolio's staked paper bets (perf_series_raw.json,
  extracted read-only from reports/model_scorecard/model_scorecard_<day>.json by perf_series.py).

  py -3 perf_build.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
RM = os.path.dirname(HERE)
GRADES = [("2026-11-15", "grade_1557.json"), ("2026-11-16", "grade_1116.json"), ("2026-11-17", "grade1117_out.json"),
          ("2026-11-18", "grade1118_out.json")]
import glob as _glob
for _f in sorted(_glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "grade_20??-??-??_out.json"))):
    _d = os.path.basename(_f)[6:16]
    if _d not in {g[0] for g in GRADES}:
        GRADES.append((_d, os.path.basename(_f)))
SPORT_NAMES = {"nba": "NBA", "ncaab": "NCAAB", "wncaab": "Women's college", "ncaaf": "NCAAF", "nfl": "NFL", "nhl": "NHL"}


def scope_of(key):
    if key == "ALL":
        return "All flags"
    if key.startswith("sport:"):
        return SPORT_NAMES.get(key[6:], key[6:])
    if key in SPORT_NAMES:
        return SPORT_NAMES[key]
    if key.startswith("market:"):
        key = key[7:]
    if ":" in key and key.split(":")[0] in ("h2h", "spreads", "totals"):
        m, seg = key.split(":", 1)
        return {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}[m] + (" (full game)" if seg == "full" else " (half / quarter)")
    return None


rail = []
for day, fname in GRADES:
    p = os.path.join(RM, fname)
    if not os.path.exists(p):
        continue
    d = json.load(open(p, encoding="utf-8"))
    for key, b in (d.get("buckets") or {}).items():
        scope = scope_of(key)
        if scope is None or not b.get("graded"):
            continue
        ci = b.get("hit_minus_fair_ci90") or [None, None]
        hit, fair = b.get("hit_rate"), b.get("mean_fair_p")
        rail.append({
            "id": f"{day}|{scope}", "day": day, "scope": scope, "kind": "all" if scope == "All flags" else ("sport" if scope in SPORT_NAMES.values() else "market"),
            "flags": b.get("graded"), "games": b.get("games"), "won": b.get("win"), "lost": b.get("loss"),
            "hit_pct": round(100 * hit, 1) if hit is not None else None,
            "fair_pct": round(100 * fair, 1) if fair is not None else None,
            "edge_pp": round(100 * (hit - fair), 1) if hit is not None and fair is not None else None,
            "ci90_lo_pp": round(100 * ci[0], 1) if ci[0] is not None else None,
            "ci90_hi_pp": round(100 * ci[1], 1) if ci[1] is not None else None,
            "brier_model": b.get("brier_model"), "brier_book": b.get("brier_fair"),
        })
rail.sort(key=lambda r: (r["day"], {"all": 0, "sport": 1, "market": 2}[r["kind"]], -(r["flags"] or 0)))
json.dump(rail, open(os.path.join(HERE, "rail_results.json"), "w", encoding="utf-8"), indent=0)

raw = json.load(open(os.path.join(HERE, "perf_series_raw.json"), encoding="utf-8"))
board = []
for r in raw:
    sport = SPORT_NAMES.get(r["sport"], r["sport"].upper() if len(r["sport"]) <= 4 else r["sport"].title())
    board.append({"id": f"{r['day']}|{r['sport']}|{r['set']}", "day": r["day"], "sport": sport, "set": r["set"],
                  "bets": r["bets"], "games": r.get("games"), "roi_pct": r["roi_pct"],
                  "predicted_ev_pct": r["predicted_ev_pct"], "market_ev_pct": r["market_ev_pct"]})
sug_path = os.path.join(HERE, "sug_raw.json")
if os.path.exists(sug_path):
    for r in json.load(open(sug_path, encoding="utf-8"))["rows"]:
        sport = SPORT_NAMES.get(r["sport"], r["sport"].upper() if len(r["sport"]) <= 4 else r["sport"].title())
        board.append({"id": f"{r['day']}|{r['sport']}|{r['set']}", "day": r["day"], "sport": sport, "set": r["set"],
                      "bets": r["bets"], "games": r.get("games"), "roi_pct": r["roi_pct"],
                      "predicted_ev_pct": r.get("predicted_ev_pct"), "market_ev_pct": r.get("market_ev_pct"),
                      "roi_ci95_lo_pct": r.get("roi_ci95_lo_pct"), "roi_ci95_hi_pct": r.get("roi_ci95_hi_pct")})
board.sort(key=lambda r: (r["day"], r["sport"], r["set"]))
json.dump(board, open(os.path.join(HERE, "board_results.json"), "w", encoding="utf-8"), indent=0)
print("rail rows", len(rail), "days", sorted({r["day"] for r in rail}), "| board rows", len(board),
      "days", len({r["day"] for r in board}))
