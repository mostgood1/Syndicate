# -*- coding: utf-8 -*-
"""Did a shipped soccer shot-shrinkage divisor reach the engine, and is it STILL there?

The lane's owed reading was blocked on the served board carrying shot rows.
This asks the same question of the PRODUCTION PREDICTION ARCHIVE instead,
which the engine writes on every sim run and which is exportable.

SELF-NORMALISED, so slate composition cannot drive the answer: every player is
compared to HIMSELF across the split, using only players present on both sides.
A fixture dated before a ship date is frozen at its write from before that
ship; a fixture dated after has been re-written since.

  divisor live  -> later/earlier expected_shots ~ 1/divisor
  never landed  -> ~1.00

CONFOUND, KILLED EXPLICITLY: a shots-only drop could instead be "future
fixtures carry lower minutes". A divisor moves shots and leaves minutes alone,
so expected_minutes_share is ratioed too, and shots are re-ratioed per unit of
minutes share. A flat minutes ratio with a moved per-minute ratio is the
divisor and nothing else.

WHAT THIS CANNOT DO. Every bucket is compared to the FIRST one, never to its
neighbour, because consecutive re-fits move the divisor by well under this
measure's noise floor -- 1.3979 -> 1.3930 is 0.35%, while a 496-player bucket
here scattered 0.669 against a 3,428-player bucket's 0.726. So it answers "is a
divisor of roughly the shipped size being applied", NOT "which dated artifact
is the worker resolving". The second question needs the worker's own disk.
Its real job is catching the resolver BREAKING on a newly published file, where
the expected reading jumps all the way back to 1.00.

  SHIP_DATES       comma-separated, ascending. Each opens a bucket; everything
                   before the first is the pre-divisor baseline.
  SHIPPED_DIVISOR  comma-separated, one per ship date, for the printed target.
"""
import collections, glob, io, json, os, statistics, sys, unicodedata

sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS

RECS = os.path.join(os.environ.get("TEMP", "."), "prod_recs")
SHIPS = [s.strip() for s in os.environ.get("SHIP_DATES", "2026-08-31,2026-09-02").split(",") if s.strip()]
DIVS = [float(s) for s in os.environ.get("SHIPPED_DIVISOR", "1.3979,1.3930").split(",") if s.strip()]
MIN_SHARED = 100


def fold(n):
    return "".join(c for c in unicodedata.normalize("NFKD", str(n))
                   if not unicodedata.combining(c)).lower().strip()


def bucket_of(dt):
    """Index into SHIPS+1: 0 is the pre-divisor baseline."""
    i = 0
    for s in SHIPS:
        if dt >= s:
            i += 1
    return i


buckets = collections.defaultdict(lambda: collections.defaultdict(list))
dates = collections.Counter()
for f in sorted(glob.glob(os.path.join(RECS, "*.json"))):
    try:
        j = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        continue
    lg, dt = j.get("league"), str(j.get("date") or "")
    if lg not in LEAGUE_ESPN_SLUGS or not dt:
        continue
    for r in (j.get("player_props") or []):
        nm, es = r.get("player_name"), r.get("expected_shots")
        ms = r.get("expected_minutes_share")
        if nm and es is not None and float(es) > 0 and ms and float(ms) > 0.05:
            dates[dt] += 1
            buckets[bucket_of(dt)][(lg, fold(nm))].append((float(es), float(ms)))

if not dates:
    print("NO PROP ROWS in %s -- pull the archive first." % RECS)
    raise SystemExit(2)


def label(i):
    if i == 0:
        return "BASE (< %s, no divisor)" % SHIPS[0]
    lo = SHIPS[i - 1]
    hi = ("< %s" % SHIPS[i]) if i < len(SHIPS) else "onward"
    d = (", divisor %.4f" % DIVS[i - 1]) if i - 1 < len(DIVS) else ""
    return ">= %s %s%s" % (lo, hi, d)


print("archive dates %d, %s..%s" % (len(dates), min(dates), max(dates)))
for i in sorted(buckets):
    print("  [%d] %-42s players=%d" % (i, label(i), len(buckets[i])))

base = buckets.get(0)
if not base:
    print("\nNO pre-divisor baseline -- the archive no longer reaches back before %s." % SHIPS[0])
    raise SystemExit(0)

for i in sorted(buckets):
    if i == 0:
        continue
    both = sorted(set(base) & set(buckets[i]))
    if len(both) < MIN_SHARED:
        print("\n[%d] vs BASE: only %d shared players (< %d) -- SKIPPED, too thin to read."
              % (i, len(both), MIN_SHARED))
        continue
    later = buckets[i]

    def med(fn):
        return statistics.median(sorted(fn(k) for k in both))

    r_shots = med(lambda k: statistics.mean(p for p, _ in later[k])
                          / statistics.mean(p for p, _ in base[k]))
    r_min = med(lambda k: statistics.mean(m for _, m in later[k])
                        / statistics.mean(m for _, m in base[k]))
    r_per = med(lambda k: statistics.mean(p / m for p, m in later[k])
                        / statistics.mean(p / m for p, m in base[k]))
    tgt = (1.0 / DIVS[i - 1]) if i - 1 < len(DIVS) else None
    print("\n[%d] %s  vs  BASE   (n=%d shared players)" % (i, label(i), len(both)))
    print("     expected_shots           %.3f" % r_shots)
    print("     expected_minutes_share   %.3f   flat -> minutes are NOT the cause" % r_min)
    print("     shots per minute-share   %.3f   <- this is the divisor" % r_per)
    if tgt is not None:
        verdict = "A DIVISOR IS BEING APPLIED" if r_per < 0.9 else "NO DIVISOR -- resolver may be BROKEN"
        print("     target %.3f (= 1/%.4f)   vs 1.00 if absent   ->  %s" % (tgt, DIVS[i - 1], verdict))
