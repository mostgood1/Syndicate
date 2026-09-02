# -*- coding: utf-8 -*-
"""INSTRUMENT VALIDATION: per-league shots-per-match extracted from ESPN.

A league whose capture is far below the ~23.4 shots/match benchmark has MISSING
outcomes, not zero shots. Including such a league inflates the fitted divisor.
"""
import collections, datetime, glob, io, json, os, sys
sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

RECS = os.path.join(os.environ.get("TEMP", "."), "prod_recs")
CACHE = os.path.join(os.environ.get("TEMP", "."), "espn_shots_cache")
TODAY = datetime.date.today().isoformat()
BENCH = 23.4

# which (league, match_id) pairs the archive actually predicted on, past only
want = set()
dates = collections.defaultdict(set)
for f in sorted(glob.glob(os.path.join(RECS, "*.json"))):
    try: j = json.load(io.open(f, encoding="utf-8"))
    except Exception: continue
    lg, dt = j.get("league"), str(j.get("date") or "")
    if lg not in LEAGUE_ESPN_SLUGS or not dt or dt >= TODAY: continue
    for r in (j.get("player_props") or []):
        if r.get("match_id"):
            want.add((lg, str(r["match_id"])))
            dates[lg].add(dt)

shots = collections.Counter(); nm_ct = collections.Counter()
mt = collections.Counter(); empty = collections.Counter()
for lg, mid in sorted(want):
    cf = os.path.join(CACHE, "%s_%s.json" % (lg, mid))
    if not os.path.exists(cf): continue
    try: s = json.load(io.open(cf, encoding="utf-8"))
    except Exception: continue
    try: ev = extract_shot_events(s, event_id=mid)
    except Exception: ev = None
    mt[lg] += 1
    if not ev:
        empty[lg] += 1; continue
    shots[lg] += len(ev)
    nm_ct[lg] += sum(1 for e in ev if (e.get("player_name") or "").strip())

print("benchmark %.1f shots/match; capture floor 0.75 -> %.2f" % (BENCH, 0.75*BENCH))
print("%-22s %7s %7s %10s %9s %9s  %s" % ("league","matches","empty","shots/match","capture","named/mt","verdict"))
bad = []
for lg in sorted(mt, key=lambda l: -mt[l]):
    played = mt[lg] - empty[lg]
    spm = shots[lg]/max(played, 1)
    cap = spm / BENCH
    npm = nm_ct[lg]/max(played, 1)
    v = "OK" if cap >= 0.75 else "EXCLUDE - outcomes missing"
    if cap < 0.75: bad.append(lg)
    print("%-22s %7d %7d %10.2f %9.2f %9.2f  %s" % (lg, mt[lg], empty[lg], spm, cap, npm, v))
print("\nleagues failing capture: %s" % (", ".join(bad) or "(none)"))
