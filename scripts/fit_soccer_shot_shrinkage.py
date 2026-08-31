# -*- coding: utf-8 -*-
"""Fit a shrinkage for the soccer shots model, and validate it HELD OUT by DATE.

PRE-REGISTERED BEFORE THE HELD-OUT NUMBERS WERE SEEN. This lane's standing rule
exists because the most trustworthy-looking in-sample result the soccer lane
ever produced failed a held-out check, so the criterion is fixed first:

  SPLIT      by DATE, never by row. Train on the earlier half of the archive,
             test on the later. Rows from one match cannot straddle the split,
             so a match's shared conditions cannot leak.

  CANDIDATES three, deliberately including the one I already argued against, so
             the argument is TESTED rather than assumed:
               (a) RAW            -- the model as it ships
               (b) SCALAR         -- predicted / c, c fit on train
               (c) AFFINE         -- a + b*predicted, fit on train by least
                                     squares. b < 1 IS the shrinkage.

  SUCCESS    a candidate wins only if, ON TEST, it beats RAW on MAE **and**
             leaves less absolute bias than RAW. Beating the constant-mean
             baseline is reported too, because a correction that cannot beat
             "predict the average" is not worth shipping.

  MY STATED EXPECTATION, recorded so it can be wrong: AFFINE beats SCALAR,
  because the production run showed the error has a SLOPE -- under-predicting
  the bottom two deciles and over-predicting from the fourth up. If SCALAR wins
  or ties, my "spread is too wide" reading was wrong and a divisor is enough.

CONFOUND STATED UP FRONT: the archive's league mix is not uniform over time
(MLS is heavy and runs a different calendar), so a DATE split also shifts the
LEAGUE mix. Per-league test results are printed for exactly this reason -- a
pooled win driven by one league is not a win.
"""
import collections, datetime, glob, io, json, os, sys, unicodedata

sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

RECS = os.path.join(os.environ.get("TEMP", "."), "prod_recs")
CACHE = os.path.join(os.environ.get("TEMP", "."), "espn_shots_cache")
TODAY = datetime.date.today().isoformat()
BAD = {"belgian_pro_league"}          # capture 0.13 -- outcomes absent, not zero


def fold(n):
    return "".join(c for c in unicodedata.normalize("NFKD", str(n))
                   if not unicodedata.combining(c)).lower().strip()


rows = []
for f in sorted(glob.glob(os.path.join(RECS, "*.json"))):
    try: j = json.load(io.open(f, encoding="utf-8"))
    except Exception: continue
    lg, dt = j.get("league"), str(j.get("date") or "")
    if lg not in LEAGUE_ESPN_SLUGS or lg in BAD or dt >= TODAY or not dt:
        continue
    for r in (j.get("player_props") or []):
        if r.get("match_id") and r.get("player_name") and r.get("expected_shots") is not None:
            rows.append([dt, lg, str(r["match_id"]), fold(r["player_name"]),
                         float(r["expected_shots"]), 0])

realized, ok = collections.Counter(), set()
for f in glob.glob(os.path.join(CACHE, "*.json")):
    b = os.path.basename(f)[:-5]; lg, mid = b.rsplit("_", 1)
    if lg in BAD: continue
    try: s = json.load(io.open(f, encoding="utf-8"))
    except Exception: continue
    try: ev = extract_shot_events(s, event_id=mid)
    except Exception: continue
    if not ev: continue
    ok.add(mid)
    for e in ev:
        nm = (e.get("player_name") or "").strip()
        if nm: realized[(mid, fold(nm))] += 1

D = [r for r in rows if r[2] in ok]
for r in D: r[5] = realized.get((r[2], r[3]), 0)
print("dataset: n=%d over %d matches, %d leagues, dates %s..%s"
      % (len(D), len({r[2] for r in D}), len({r[1] for r in D}),
         min(r[0] for r in D), max(r[0] for r in D)))

# --- split by DATE at the row-count median, whole dates only ---------------
per_date = collections.Counter(r[0] for r in D)
run, cut, half = 0, None, len(D) / 2.0
for d in sorted(per_date):
    run += per_date[d]
    if run >= half: cut = d; break
train = [r for r in D if r[0] < cut]
test = [r for r in D if r[0] >= cut]
print("split at %s -> train n=%d (%d matches) | test n=%d (%d matches)"
      % (cut, len(train), len({r[2] for r in train}), len(test), len({r[2] for r in test})))
if not train or not test:
    print("degenerate split"); raise SystemExit(2)

def fit_scalar(S):
    p = sum(r[4] for r in S); a = sum(r[5] for r in S)
    return p / max(a, 1e-9)                      # divide predictions by this

def fit_affine(S):
    n = len(S)
    sx = sum(r[4] for r in S); sy = sum(r[5] for r in S)
    sxx = sum(r[4]*r[4] for r in S); sxy = sum(r[4]*r[5] for r in S)
    den = n*sxx - sx*sx
    if abs(den) < 1e-12: return 0.0, 1.0
    b = (n*sxy - sx*sy) / den
    a = (sy - b*sx) / n
    return a, b

c = fit_scalar(train)
a, b = fit_affine(train)
print("\nfitted on TRAIN only:")
print("   SCALAR  divide predictions by c = %.4f" % c)
print("   AFFINE  realized ~ %.4f + %.4f * predicted   (b<1 means shrinkage)" % (a, b))

def score(S, fn, label):
    pr = [max(0.0, fn(r[4])) for r in S]; ac = [r[5] for r in S]
    mae = sum(abs(p-x) for p, x in zip(pr, ac))/len(S)
    bias = sum(pr)/len(pr) - sum(ac)/len(ac)
    return label, mae, bias, sum(pr)/len(pr), sum(ac)/len(ac)

am_test = sum(r[5] for r in test)/len(test)
cands = [("RAW", lambda x: x), ("SCALAR", lambda x: x/c), ("AFFINE", lambda x: a + b*x),
         ("constant-mean baseline", lambda x: am_test)]
print("\n=== HELD-OUT TEST (dates >= %s), n=%d ===" % (cut, len(test)))
print("  %-24s %9s %9s %9s" % ("candidate", "MAE", "bias", "pred mean"))
res = {}
for lab, fn in cands:
    l, mae, bias, pm, amn = score(test, fn, lab)
    res[lab] = (mae, bias)
    print("  %-24s %9.4f %+9.4f %9.4f" % (l, mae, bias, pm))
raw_mae, raw_bias = res["RAW"]
print("\n  realized mean on test: %.4f" % am_test)
print("\n=== VERDICT against the PRE-REGISTERED criterion ===")
for lab in ("SCALAR", "AFFINE"):
    mae, bias = res[lab]
    win = (mae < raw_mae) and (abs(bias) < abs(raw_bias))
    print("  %-8s MAE %.4f vs raw %.4f (%s) | |bias| %.4f vs %.4f (%s) -> %s"
          % (lab, mae, raw_mae, "better" if mae < raw_mae else "WORSE",
             abs(bias), abs(raw_bias), "better" if abs(bias) < abs(raw_bias) else "WORSE",
             "PASSES" if win else "FAILS"))
print("  (baseline MAE %.4f -- a correction that cannot beat this is not worth shipping)"
      % res["constant-mean baseline"][0])

print("\n=== per-league on TEST (a pooled win driven by one league is not a win) ===")
byl = collections.defaultdict(list)
for r in test: byl[r[1]].append(r)
print("  %-20s %6s %9s %9s %9s" % ("league", "n", "RAW MAE", "AFFINE", "SCALAR"))
for lg, g in sorted(byl.items(), key=lambda kv: -len(kv[1])):
    if len(g) < 100: continue
    m0 = score(g, lambda x: x, "")[1]
    m1 = score(g, lambda x: a + b*x, "")[1]
    m2 = score(g, lambda x: x/c, "")[1]
    print("  %-20s %6d %9.4f %9.4f %9.4f  %s" % (
        lg, len(g), m0, m1, m2, "affine better" if m1 < m0 else "affine WORSE"))
