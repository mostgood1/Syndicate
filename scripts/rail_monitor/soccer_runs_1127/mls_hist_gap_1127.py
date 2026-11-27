"""Read-only, nice 19: the MLS history gap (user 11-27 "check the MLS history gap").
 (1) mls/history/matches_*.csv: rows, last match date, rows with corners, per file.
 (2) mls/api/live_state/live_state_<date>.json since 2026-10-01: match_box entries, how many carry both teams' corners.
 (3) what the corners estimator actually sees: league_corner_rows() row count and newest day (fleet checkout code).
 (4) ASA /mls/teams/xgoals season 2026 (the ratings source): per-team count_games -- > 34 means playoffs are counted --
     plus the same call with stage_name=Playoffs, to see whether ASA splits them. One public GET each.
WSL: cd ~/syndicate-prod && nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/mls_hist_gap_1127.py"""
import csv, glob, json, os, sys
from collections import Counter

root = os.path.expanduser("~/syndicate-prod/data/soccer_source/mls")
print("== (1) history files")
for p in sorted(glob.glob(os.path.join(root, "history", "matches_*.csv"))):
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    days = sorted(r.get("date", "")[:10] for r in rows if r.get("date"))
    corners = sum(1 for r in rows if (r.get("home_corners") or "").strip() and (r.get("away_corners") or "").strip())
    print(f"  {os.path.basename(p)}: rows {len(rows)} first {days[0] if days else None} last {days[-1] if days else None} "
          f"with corners {corners}; columns {list(rows[0].keys())[:12] if rows else []}")

print("== (2) live_state files since 2026-10-01")
tot = with_c = 0
by_month = Counter()
last_day = None
for p in sorted(glob.glob(os.path.join(root, "api", "live_state", "live_state_2026-1*.json"))):
    day = os.path.basename(p)[len("live_state_"):-5]
    try:
        d = json.load(open(p))
    except Exception:
        continue
    boxes = d.get("match_box") or {}
    n = len(boxes)
    c = 0
    for rec in boxes.values():
        teams = (rec or {}).get("teams") or {}
        vals = [((teams.get(side) or {}).get("statistics") or {}) for side in ("home", "away")]
        if all(any("orner" in str(k) for k in (v.keys() if isinstance(v, dict) else [])) for v in vals):
            c += 1
    if n:
        tot += n
        with_c += c
        by_month[day[:7]] += n
        last_day = day
        print(f"  {day}: match_box {n}, both teams' corners {c}")
print(f"  total match_box {tot}, with corners {with_c}; by month {dict(by_month)}; last {last_day}")

print("== (3) the corners estimator's own rows (fleet code)")
sys.path.insert(0, os.path.expanduser("~/Syndicate"))
try:
    from pathlib import Path
    from syndicate.features.soccer.features.corners_estimator import league_corner_rows, history_corner_rows, live_state_corner_rows
    allr = league_corner_rows(Path(root))
    h = history_corner_rows(Path(root))
    l = live_state_corner_rows(Path(root))
    print(f"  history rows {len(h)} (last {max(r.day for r in h) if h else None}); live_state rows {len(l)} "
          f"(first {min(r.day for r in l) if l else None}, last {max(r.day for r in l) if l else None}); merged {len(allr)}")
    hk = {(r.day, r.home, r.away) for r in h}
    lk = Counter((r.day, r.home, r.away) for r in allr)
    print(f"  merged rows sharing (day, home, away) with another merged row: {sum(v for v in lk.values() if v > 1)}")
except Exception as exc:
    print("  estimator import failed:", type(exc).__name__, exc)

print("== (4) ASA teams/xgoals 2026")
try:
    import requests
    ua = {"User-Agent": "syndicate-readonly-check"}
    base = "https://app.americansocceranalysis.com/api/v1/mls"
    for label, params in (("default", {"season_name": "2026"}), ("Regular Season", {"season_name": "2026", "stage_name": "Regular Season"}),
                          ("Playoffs", {"season_name": "2026", "stage_name": "Playoffs"})):
        r = requests.get(f"{base}/teams/xgoals", params=params, headers=ua, timeout=30)
        try:
            data = r.json()
        except ValueError:
            print(f"  {label}: HTTP {r.status_code} non-JSON {r.text[:120]!r}")
            continue
        if not isinstance(data, list):
            print(f"  {label}: HTTP {r.status_code} {str(data)[:200]}")
            continue
        games = sorted(int(t.get("count_games") or 0) for t in data)
        print(f"  {label}: HTTP {r.status_code} teams {len(data)} count_games min {games[0] if games else None} "
              f"max {games[-1] if games else None} teams over 34: {sum(g > 34 for g in games)} distribution {Counter(games).most_common(6)}")
except Exception as exc:
    print("  ASA call failed:", type(exc).__name__, exc)
