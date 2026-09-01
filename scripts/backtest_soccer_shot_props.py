# -*- coding: utf-8 -*-
"""The soccer shots-prop skill number: archived predictions vs ESPN outcomes.

The join the repo already had and nobody had made. Predictions are archived,
dated, and carry `expected_shots` — the model's MEAN, so no inversion and no
replay. They are keyed by ESPN match id, and `espn_shot_events` reads shot
events FROM ESPN, so the ids are the same space and the join is direct.

ZEROS ARE THE WHOLE GAME HERE. A predicted player who took no shots is a real
observation and the one that most constrains a shot model. Realized counts
therefore default to 0 for every predicted player in a fetched match, rather
than being dropped for absence from the shot feed — dropping them would score
the model only on players who happened to shoot and flatter it enormously.
"""
import glob, io, json, os, sys, time, collections, unicodedata, statistics as st


def _fold(name):
    """NFKD-folded name key.

    EXACT matching scored accented shooters -- Odegaard, Magalhaes -- as ZERO
    shots across 48 events, inflating the measured bias from 1.362 to 1.434.
    A join key is part of the instrument, and this one was wrong first.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(name)) if not unicodedata.combining(c)
    ).lower().strip()

sys.path.insert(0, os.getcwd())
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary, LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_shot_events import extract_shot_events

CACHE = os.path.join(os.environ.get("TEMP", "."), "espn_shots_cache")
os.makedirs(CACHE, exist_ok=True)

# ---- prediction side -------------------------------------------------------
preds = []           # (league, date, match_id, player_name, expected_shots, minutes_share)
for f in sorted(glob.glob("data/soccer_source/*/api/recommendations/*.json")):
    try:
        j = json.load(io.open(f, encoding="utf-8"))
    except Exception:
        continue
    lg = j.get("league")
    if lg not in LEAGUE_ESPN_SLUGS:
        continue
    for r in (j.get("player_props") or []):
        mid, nm, es = r.get("match_id"), r.get("player_name"), r.get("expected_shots")
        if mid and nm and es is not None:
            preds.append((lg, j.get("date"), str(mid), nm.strip(), float(es),
                          float(r.get("expected_minutes_share") or 0.0)))
matches = sorted({(lg, mid) for lg, _, mid, _, _, _ in preds})
print("predictions: %d rows over %d matches, %d leagues"
      % (len(preds), len(matches), len({lg for lg, _ in matches})), flush=True)

# ---- outcome side: fetch each ESPN match summary once -----------------------
realized, fetched, failed = {}, 0, []
for lg, mid in matches:
    cf = os.path.join(CACHE, "%s_%s.json" % (lg, mid))
    summary = None
    if os.path.exists(cf):
        try: summary = json.load(io.open(cf, encoding="utf-8"))
        except Exception: summary = None
    if summary is None:
        try:
            summary = fetch_match_summary(lg, mid)  # takes the LEAGUE KEY; it resolves the slug itself
            json.dump(summary, io.open(cf, "w", encoding="utf-8"))
            time.sleep(0.4)                      # courtesy on an unauthenticated public API
        except Exception as exc:
            failed.append((lg, mid, "%s: %s" % (type(exc).__name__, exc)))
            continue
    try:
        events = extract_shot_events(summary, event_id=mid)
    except Exception as exc:
        failed.append((lg, mid, "extract: %s" % type(exc).__name__)); continue
    if not events:
        failed.append((lg, mid, "no shot events in feed")); continue
    fetched += 1
    for e in events:
        nm = (e.get("player_name") or "").strip()
        if nm:
            realized[(mid, _fold(nm))] = realized.get((mid, _fold(nm)), 0) + 1
print("matches with shot events: %d of %d   (failed/empty: %d)"
      % (fetched, len(matches), len(failed)), flush=True)
for row in failed[:5]:
    print("   miss:", row, flush=True)

ok_matches = {mid for (mid, _) in realized}
joined = [(lg, mid, nm, es, ms, realized.get((mid, _fold(nm)), 0))
          for lg, _, mid, nm, es, ms in preds if mid in ok_matches]
print("\njoined (player,match) pairs: %d  over %d matches" % (len(joined), len(ok_matches)))
if not joined:
    print("NO OVERLAP -- stopping rather than reporting a number off an empty join.")
    raise SystemExit(2)

pe = [e for _, _, _, e, _, _ in joined]
ac = [a for _, _, _, _, _, a in joined]
print("\n=== SKILL: predicted expected_shots vs realized shot count ===")
print("   n                 %d" % len(joined))
print("   predicted mean    %.4f" % (sum(pe)/len(pe)))
print("   realized  mean    %.4f" % (sum(ac)/len(ac)))
bias = sum(pe)/len(pe) - sum(ac)/len(ac)
print("   BIAS (pred-real)  %+.4f   ratio %.3f" % (bias, (sum(pe)/len(pe))/max(sum(ac)/len(ac), 1e-9)))
mae = sum(abs(e-a) for _, _, _, e, _, a in joined)/len(joined)
print("   MAE               %.4f" % mae)
base = sum(ac)/len(ac)
print("   MAE of a constant-mean baseline  %.4f  (model %s)"
      % (sum(abs(base-a) for a in ac)/len(ac),
         "BETTER" if mae < sum(abs(base-a) for a in ac)/len(ac) else "WORSE"))

print("\n=== calibration by predicted decile (bias should be ~0 in every bucket) ===")
sj = sorted(joined, key=lambda t: t[3])
k = max(1, len(sj)//10)
print("   %-16s %5s %10s %10s %9s" % ("pred range", "n", "pred mean", "real mean", "bias"))
for i in range(0, len(sj), k):
    ch = sj[i:i+k]
    if len(ch) < 5: continue
    p = sum(x[3] for x in ch)/len(ch); a = sum(x[5] for x in ch)/len(ch)
    print("   %6.2f-%-8.2f %5d %10.3f %10.3f %+9.3f" % (ch[0][3], ch[-1][3], len(ch), p, a, p-a))

print("\n=== split by expected_minutes_share (starter awareness is the named suspect) ===")
for lo, hi, lab in ((0.0, 0.5, "sub/fringe"), (0.5, 0.85, "rotation"), (0.85, 1.01, "near-ever-present")):
    g = [x for x in joined if lo <= x[4] < hi]
    if len(g) < 10: continue
    p = sum(x[3] for x in g)/len(g); a = sum(x[5] for x in g)/len(g)
    print("   %-20s n=%-5d pred %.3f  real %.3f  bias %+.3f  ratio %.2f"
          % (lab, len(g), p, a, p-a, p/max(a, 1e-9)))
