# -*- coding: utf-8 -*-
"""Did the shipped soccer shot-shrinkage divisor ever reach the engine?

The lane's owed reading was blocked on the served board carrying shot rows.
This asks the same question of the PRODUCTION PREDICTION ARCHIVE instead,
which the engine writes on every sim run and which is exportable.

SELF-NORMALISED, so slate composition cannot drive the answer: only players
appearing BOTH before and on/after the ship date are used, and every player is
compared to HIMSELF. Fixtures dated before the ship are frozen at their
pre-divisor write; fixtures dated on/after have been re-written since.

  divisor live  -> post/pre expected_shots ~ 1/divisor
  never landed  -> ~1.00

CONFOUND, KILLED EXPLICITLY: a shots-only drop could instead be "future
fixtures carry lower minutes". A divisor moves shots and leaves minutes alone,
so expected_minutes_share is ratioed too, and shots are re-ratioed per unit of
minutes share. A flat minutes ratio with a moved per-minute ratio is the
divisor and nothing else.
"""
import collections, glob, io, json, os, statistics, sys, unicodedata

sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS

RECS = os.path.join(os.environ.get("TEMP", "."), "prod_recs")
SHIP = os.environ.get("SHIP_DATE", "2026-08-31")
DIVISOR = float(os.environ.get("SHIPPED_DIVISOR", "1.3979"))


def fold(n):
    return "".join(c for c in unicodedata.normalize("NFKD", str(n))
                   if not unicodedata.combining(c)).lower().strip()


pre = collections.defaultdict(list)
post = collections.defaultdict(list)
dates = collections.Counter()
for f in sorted(glob.glob(os.path.join(RECS, "*.json"))):
    try:
        j = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        continue
    lg, dt = j.get("league"), str(j.get("date") or "")
    if lg not in LEAGUE_ESPN_SLUGS or not dt:
        continue
    rows = j.get("player_props") or []
    if rows:
        dates[dt] += len(rows)
    tgt = post if dt >= SHIP else pre
    for r in rows:
        nm, es = r.get("player_name"), r.get("expected_shots")
        ms = r.get("expected_minutes_share")
        if nm and es is not None and float(es) > 0 and ms and float(ms) > 0.05:
            tgt[(lg, fold(nm))].append((float(es), float(ms)))

print("archive dates carrying prop rows: %d, %s..%s"
      % (len(dates), min(dates), max(dates)))
both = sorted(set(pre) & set(post))
print("players on BOTH sides of %s: %d (pre-only %d, post-only %d)"
      % (SHIP, len(both), len(set(pre) - set(post)), len(set(post) - set(pre))))
if not both:
    print("NO OVERLAP -- this check cannot run.")
    raise SystemExit(0)


def med(fn):
    return statistics.median(sorted(fn(k) for k in both))


r_shots = med(lambda k: statistics.mean(a for a, _ in post[k])
                      / statistics.mean(a for a, _ in pre[k]))
r_min = med(lambda k: statistics.mean(b for _, b in post[k])
                    / statistics.mean(b for _, b in pre[k]))
r_per = med(lambda k: statistics.mean(a / b for a, b in post[k])
                    / statistics.mean(a / b for a, b in pre[k]))

print("")
print("  median post/pre  expected_shots           %.3f" % r_shots)
print("  median post/pre  expected_minutes_share   %.3f   flat -> minutes are NOT the cause" % r_min)
print("  median post/pre  shots PER minute-share   %.3f   <- this is the divisor" % r_per)
print("")
print("  1 / %.4f = %.3f  if the divisor IS live" % (DIVISOR, 1.0 / DIVISOR))
print("  ~1.00              if it never reached the engine")
