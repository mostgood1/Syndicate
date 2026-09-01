# -*- coding: utf-8 -*-
"""The shots-prop skill number against the PRODUCTION prediction archive.

Same measurement as `scripts/backtest_soccer_shot_props.py`, pointed at the 144
recommendation files pulled from `/api/ops/artifacts/export` (15,978 prop rows,
400 matches, 37 dates, 10 leagues) instead of the git mirror's 22 files.

TWO GUARDS THE MIRROR RUN DID NOT NEED:

  - FUTURE AND SAME-DAY FIXTURES ARE EXCLUDED. The archive runs to 2026-09-07,
    past today. An unplayed match returns a summary with no shot events, and an
    IN-PROGRESS one returns a partial set that would score as a completed
    match -- silently, and always in the direction of "the model over-predicted".
    Cutoff is strictly before today.
  - NFKD-FOLDED NAMES. Exact matching scored accented shooters as zero shots and
    inflated the mirror result from 1.362 to 1.434 before it was caught.
"""
import collections, datetime, glob, io, json, os, sys, time, unicodedata

sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary, LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

RECS = os.path.join(os.environ.get("TEMP", "."), "prod_recs")
CACHE = os.path.join(os.environ.get("TEMP", "."), "espn_shots_cache")
os.makedirs(CACHE, exist_ok=True)
TODAY = datetime.date.today().isoformat()


def fold(n):
    return "".join(c for c in unicodedata.normalize("NFKD", str(n))
                   if not unicodedata.combining(c)).lower().strip()


preds, skipped_future = [], 0
for f in sorted(glob.glob(os.path.join(RECS, "*.json"))):
    try:
        j = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        continue
    lg, dt = j.get("league"), str(j.get("date") or "")
    if lg not in LEAGUE_ESPN_SLUGS:
        continue
    if dt >= TODAY:                       # unplayed or in-progress
        skipped_future += len(j.get("player_props") or [])
        continue
    for r in (j.get("player_props") or []):
        mid, nm, es = r.get("match_id"), r.get("player_name"), r.get("expected_shots")
        if mid and nm and es is not None:
            preds.append((lg, str(mid), fold(nm), float(es),
                          float(r.get("expected_minutes_share") or 0.0)))
matches = sorted({(lg, mid) for lg, mid, _, _, _ in preds})
print("prediction rows %d over %d matches (excluded %d rows on today/future fixtures)"
      % (len(preds), len(matches), skipped_future), flush=True)

realized, ok, failed = collections.Counter(), set(), 0
for i, (lg, mid) in enumerate(matches, 1):
    cf = os.path.join(CACHE, "%s_%s.json" % (lg, mid))
    s = None
    if os.path.exists(cf):
        try: s = json.load(io.open(cf, encoding="utf-8"))
        except Exception: s = None
    if s is None:
        try:
            s = fetch_match_summary(lg, mid)
            json.dump(s, io.open(cf, "w", encoding="utf-8"))
            time.sleep(0.35)
        except Exception:
            failed += 1; continue
    try:
        ev = extract_shot_events(s, event_id=mid)
    except Exception:
        failed += 1; continue
    if not ev:
        failed += 1; continue
    ok.add(mid)
    for e in ev:
        nm = (e.get("player_name") or "").strip()
        if nm:
            realized[(mid, fold(nm))] += 1
    if i % 50 == 0:
        print("   fetched %d/%d ..." % (i, len(matches)), flush=True)

J = [(lg, mid, nm, es, ms, realized.get((mid, nm), 0))
     for lg, mid, nm, es, ms in preds if mid in ok]
print("matches with events %d of %d (no-events/failed %d) | joined pairs %d"
      % (len(ok), len(matches), failed, len(J)), flush=True)
if not J:
    print("EMPTY JOIN -- stopping."); raise SystemExit(2)

pe = [x[3] for x in J]; ac = [x[5] for x in J]
pm, am = sum(pe)/len(pe), sum(ac)/len(ac)
mae = sum(abs(x[3]-x[5]) for x in J)/len(J)
bmae = sum(abs(am-a) for a in ac)/len(ac)
print("\n=== PRODUCTION SKILL ===")
print("  n %d | matches %d | leagues %d" % (len(J), len(ok), len({x[0] for x in J})))
print("  predicted mean %.4f   realized mean %.4f" % (pm, am))
print("  BIAS %+.4f   RATIO %.3f" % (pm-am, pm/max(am, 1e-9)))
print("  MAE %.4f vs constant-mean baseline %.4f -> model %s by %.1f%%"
      % (mae, bmae, "BETTER" if mae < bmae else "WORSE", 100*abs(bmae-mae)/bmae))

print("\n=== calibration by predicted decile ===")
sj = sorted(J, key=lambda t: t[3]); k = max(1, len(sj)//10)
for i in range(0, len(sj), k):
    ch = sj[i:i+k]
    if len(ch) < 5: continue
    p = sum(x[3] for x in ch)/len(ch); a = sum(x[5] for x in ch)/len(ch)
    print("  %6.2f-%-6.2f n=%-5d pred %6.3f real %6.3f bias %+7.3f ratio %5.2f"
          % (ch[0][3], ch[-1][3], len(ch), p, a, p-a, p/max(a, 1e-9)))

print("\n=== by expected_minutes_share ===")
for lo, hi, lab in ((0.0,0.5,"sub/fringe"), (0.5,0.85,"rotation"), (0.85,1.01,"near-ever-present")):
    g = [x for x in J if lo <= x[4] < hi]
    if len(g) < 10: continue
    p = sum(x[3] for x in g)/len(g); a = sum(x[5] for x in g)/len(g)
    print("  %-20s n=%-5d pred %.3f real %.3f bias %+.3f ratio %.2f"
          % (lab, len(g), p, a, p-a, p/max(a, 1e-9)))

print("\n=== by league (is the level error universal or local?) ===")
byl = collections.defaultdict(list)
for x in J: byl[x[0]].append(x)
for lg, g in sorted(byl.items(), key=lambda kv: -len(kv[1])):
    if len(g) < 50: continue
    p = sum(x[3] for x in g)/len(g); a = sum(x[5] for x in g)/len(g)
    print("  %-20s n=%-5d pred %.3f real %.3f ratio %.2f" % (lg, len(g), p, a, p/max(a, 1e-9)))
