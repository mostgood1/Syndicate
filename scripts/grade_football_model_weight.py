"""How much weight does the model's opinion actually deserve? Fit it.

Established: the model trails always-bet-the-underdog by 4.4 ATS points in NCAAF
and 4.2 in NFL preseason. Nearly identical in two independent sports, which
points at something SYSTEMATIC rather than per-sport calibration.

THE TEST that settles what to do about it. Regress the realised margin on the
market and on the model's DEVIATION from the market:

    actual = a + b*market + w*(model - market)

`w` is the answer, and it is not a diagnostic -- it is a decision:

    w ~ 1     the model's disagreement is fully informative; trust it
    w ~ 0     the model adds NOTHING beyond the market; blending is pointless
    w < 0     the model is ANTI-predictive; its disagreements point the wrong
              way, and the correct use of it is to FADE it

`b` is a second, independent read on the market itself: b ~ 1 means the closing
line is unbiased, b < 1 means favourites are over-priced.

WHY THIS BEATS ANOTHER ATS SWEEP. A win rate is one bit per game and needs
hundreds of bets to resolve. A regression uses the full magnitude of every
error, so 751 games give a tight estimate of `w` -- and `w` says not just
"is there an edge" but "how much of the model should survive", which is exactly
the Stage 5 blend question.

Reports a bootstrap CI because the point estimate alone cannot distinguish
"w is 0" from "w is unmeasurable here".
"""
import random
import statistics
import sys
from pathlib import Path

REPO = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
sys.path.insert(0, str(REPO))
from syndicate.features.football.pick_ledger import load_ledger  # noqa: E402

random.seed(20260820)  # deterministic: Math.random equivalents drift between runs


def games(sport, seasons):
    rows = []
    for s in seasons:
        rows += load_ledger(sport, s)
    out = {}
    for r in rows:
        if r.model_margin is None or r.spread_close is None or r.realised_margin is None:
            continue
        g = out.setdefault((r.season, r.game_id),
                           {"m": r.model_margin, "a": r.realised_margin, "l": []})
        g["l"].append(r.spread_close)
    return [(v["m"], -statistics.median(v["l"]), v["a"]) for v in out.values()]


def ols2(y, x1, x2):
    """y = a + b*x1 + w*x2 by residualisation (2 predictors, no matrix lib)."""
    n = len(y)
    def reg(t, p):
        mp, mt = statistics.fmean(p), statistics.fmean(t)
        sxx = sum((v - mp) ** 2 for v in p)
        if sxx == 0:
            return t, 0.0
        b = sum((v - mp) * (c - mt) for v, c in zip(p, t)) / sxx
        return [c - (b * (v - mp) + mt) for v, c in zip(p, t)], b
    # w: coefficient on x2 after removing x1 from both
    ry, _ = reg(y, x1)
    rx, _ = reg(x2, x1)
    mrx = statistics.fmean(rx)
    sxx = sum((v - mrx) ** 2 for v in rx)
    w = sum((v - mrx) * c for v, c in zip(rx, ry)) / sxx if sxx else 0.0
    # b: coefficient on x1 after removing x2
    ry2, _ = reg(y, x2)
    rx2, _ = reg(x1, x2)
    mrx2 = statistics.fmean(rx2)
    sxx2 = sum((v - mrx2) ** 2 for v in rx2)
    b = sum((v - mrx2) * c for v, c in zip(rx2, ry2)) / sxx2 if sxx2 else 0.0
    return b, w


def boot(data, fn, reps=2000):
    n = len(data)
    vals = []
    for _ in range(reps):
        s = [data[random.randrange(n)] for _ in range(n)]
        vals.append(fn(s))
    vals.sort()
    return vals[int(0.025 * reps)], vals[int(0.975 * reps)]


def report(label, data):
    print("\n" + "=" * 76)
    print("%s  --  %d games" % (label, len(data)))
    print("=" * 76)
    if len(data) < 30:
        print("  too few")
        return
    y = [d[2] for d in data]
    mk = [d[1] for d in data]
    dev = [d[0] - d[1] for d in data]
    b, w = ols2(y, mk, dev)
    lo_w, hi_w = boot(data, lambda s: ols2([d[2] for d in s], [d[1] for d in s],
                                           [d[0] - d[1] for d in s])[1])
    lo_b, hi_b = boot(data, lambda s: ols2([d[2] for d in s], [d[1] for d in s],
                                           [d[0] - d[1] for d in s])[0])
    print("    actual = a + b*market + w*(model - market)")
    print()
    print("    b (market)          %+.3f   95%% CI [%+.3f, %+.3f]" % (b, lo_b, hi_b))
    print("    w (model deviation) %+.3f   95%% CI [%+.3f, %+.3f]" % (w, lo_w, hi_w))
    print()
    if hi_w < 0:
        verdict = "ANTI-PREDICTIVE -- the model's disagreements point the WRONG WAY"
    elif lo_w > 0:
        verdict = "INFORMATIVE -- the model's disagreements carry real signal"
    else:
        verdict = "NO MEASURABLE VALUE -- w is indistinguishable from zero"
    print("    -> %s" % verdict)
    print("    market bias: b=%.2f %s" % (
        b, "(unbiased)" if lo_b <= 1.0 <= hi_b else
           ("(favourites OVER-priced)" if hi_b < 1.0 else "(favourites UNDER-priced)")))
    # how much of the model's spread is deviation at all
    print("    model deviation SD %.2f vs market SD %.2f" % (
        statistics.pstdev(dev), statistics.pstdev(mk)))


report("NCAAF 2024 -- clean out-of-sample, 2023 SP+ on 2024 games", games("ncaaf", (2024,)))
report("NFL PRESEASON 2023+2024 -- leak-free by construction", games("nfl", (2023, 2024)))

print("\n" + "=" * 76)
print("w is a DECISION, not a diagnostic:")
print("  w ~ 1  trust the model's disagreement")
print("  w ~ 0  the model adds nothing beyond the market -- blending is pointless")
print("  w < 0  the model is anti-predictive; the correct use is to FADE it")
print("=" * 76)
