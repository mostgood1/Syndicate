"""Fit a per-sport WIDTH SCALE for the live full-game totals probability, against finals. READ-ONLY.

Todo #780, candidate fix 2 (user 2026-11-13 "Fit it now"). Findings: .syndicate/findings_2026-11-10_live_totals_grade.md
(result 2: the model's implied sd is 10-30% narrower than its own error).

The transform: P_k(over) = Phi(Phi^-1(P) / k). Widening a normal predictive distribution by k around its own mean
divides every line's z by k, so this is the width fix with the mean left alone (an estimator, model_engine_standard
4.4; it adds no mechanism). k = 1 is today's probability. P is the ledger's `model_home_win_prob` (P(over) on a
totals row, the Agresti-Coull point the join priced).

Population: the fleet's live gameline ledgers, totals / full rows with a model probability and a line (priced or
not: this is the model's calibration, not the board's), one row per (event_id, live_state_as_of, line), matched to the
ESPN final. NCAAB ledger dates >= live_totals_grade.PREREG_FROM are NEVER read (the PREREG_780 window).

Prints, per sport: the population; final - model mean and the error sd against the implied sd, by progress
(score / line); the in-sample best k (log loss), overall and per progress bucket; and a WALK-FORWARD by ledger date
(fit on every earlier date, score the next) of the Brier change, k fitted vs k = 1, game-clustered 95% CI.

Run on the fleet host (nice 19):
    wsl -d Ubuntu-24.04 -- nice -n 19 python3 /mnt/c/<repo>/scripts/live_totals_width_fit.py </dev/null
    env: SPORTS=ncaab,nba (default ncaab,wncaab,nba,ncaaf), UNTIL=<ledger date, inclusive> (default 2026-11-12), FROM=<ledger date, inclusive>,
         ESPN_CACHE=<dir> (default /mnt/c/tmp/livegrade/espn)
"""
import glob
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

sys.argv = [sys.argv[0], os.environ.get("ESPN_CACHE", "/mnt/c/tmp/livegrade/espn")]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_totals_grade as g  # noqa: E402

SPORTS = (os.environ.get("SPORTS") or "ncaab,wncaab,nba,ncaaf").split(",")
UNTIL = os.environ.get("UNTIL") or "2026-11-12"
FROM = os.environ.get("FROM") or "0000-00-00"
BUCKETS = (("<0.40", 0.0, 0.40), ("0.40-0.75", 0.40, 0.75), (">=0.75", 0.75, 99.0))
K_LO, K_HI = 0.70, 3.00
SQ2 = math.sqrt(2.0)
EPS = 1e-4


def phi(x):
    return 0.5 * (1.0 + math.erf(x / SQ2))


def inv_phi(p):
    from statistics import NormalDist
    return NormalDist().inv_cdf(min(max(p, EPS), 1.0 - EPS))


def pk(z, k):
    return min(max(phi(z / k), EPS), 1.0 - EPS)


def logloss(rows, k):
    s = 0.0
    for x in rows:
        p = pk(x["z"], k)
        s -= math.log(p) if x["y"] else math.log(1.0 - p)
    return s / len(rows)


def fit_k(rows):
    """Golden-section search for the log-loss minimum on [K_LO, K_HI] (unimodal in k for a probit scale)."""
    if not rows:
        return 1.0
    a, b = K_LO, K_HI
    gr = (math.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc, fd = logloss(rows, c), logloss(rows, d)
    for _ in range(40):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = logloss(rows, c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = logloss(rows, d)
    return round((a + b) / 2, 3)


def bucket_of(x):
    if x["prog"] is None:
        return None
    for lab, lo, hi in BUCKETS:
        if lo <= x["prog"] < hi:
            return lab
    return None


def load(sport):
    hold_from = g.PREREG_FROM if sport == g.PREREG_SPORT else "9999-12-31"
    states = {}
    for f in sorted(glob.glob(f"{g.DATA}/{sport}_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("market") != "totals" or r.get("segment") != "full":
                continue
            d = str(r.get("date") or "")
            if not d or d > UNTIL or d < FROM or d >= hold_from:
                continue
            if r.get("model_home_win_prob") is None or r.get("line") is None:
                continue
            states.setdefault((r.get("event_id"), r.get("live_state_as_of") or r.get("recorded_at"), float(r["line"])), r)
    idx = {}
    for ds in sorted({r["date"] for r in states.values()}):
        d0 = date.fromisoformat(ds)
        i = {}
        for d in (d0, d0 + timedelta(days=1)):
            i.update(g.finals(sport, d))
        idx[ds] = i
    fin, rows, drop = {}, [], defaultdict(int)
    for (eid, as_of, ln), r in states.items():
        if eid not in fin:
            h = g.match(idx[r["date"]], r.get("home_team"), r.get("away_team"))
            fin[eid] = idx[r["date"]][h][2] if h else None
        F = fin[eid]
        if F is None:
            drop["unmatched"] += 1
            continue
        try:
            sc = float(r.get("home_score")) + float(r.get("away_score"))
        except (TypeError, ValueError):
            sc = None
        if sc is not None and sc > F:
            drop["score_gt_final"] += 1
            continue
        if F == ln:
            drop["push"] += 1
            continue
        p = float(r["model_home_win_prob"])
        mt = r.get("model_total_mean")
        pf = r.get("market_fair_prob")
        rows.append({"g": eid, "date": r["date"], "y": 1 if F > ln else 0, "p": p, "z": inv_phi(p), "line": ln,
                     "final": F, "mean": float(mt) if mt is not None else None,
                     "pf": float(pf) if pf is not None else None, "priced": bool(r.get("priceable")),
                     "prog": (sc / ln) if (sc is not None and ln) else None})
    return rows, drop, len(states)


def width_ratio(rows):
    """The PURE WIDTH scale: sd of (final - model mean) over the model's own implied sd (median). k fitted on outcomes
    can exceed it when the model's distance from the line carries less information than it claims (beta < 1 below)."""
    res = [x["final"] - x["mean"] for x in rows if x["mean"] is not None]
    imp = [abs(x["mean"] - x["line"]) / abs(x["z"]) for x in rows if x["mean"] is not None and abs(x["z"]) > 0.25]
    if len(res) < 2 or not imp:
        return 1.0
    m = sum(res) / len(res)
    return math.sqrt(sum((v - m) ** 2 for v in res) / len(res)) / median(imp)


def ols(rows):
    """(final - line) = a + b (model mean - line): b < 1 means the model's disagreement with the line overstates."""
    pts = [(x["mean"] - x["line"], x["final"] - x["line"]) for x in rows if x["mean"] is not None]
    if len(pts) < 3:
        return float("nan"), float("nan"), float("nan")
    mx = sum(p for p, _ in pts) / len(pts)
    my = sum(q for _, q in pts) / len(pts)
    vx = sum((p - mx) ** 2 for p, _ in pts)
    b = sum((p - mx) * (q - my) for p, q in pts) / vx if vx else float("nan")
    a = my - b * mx
    sd = math.sqrt(sum((q - a - b * p) ** 2 for p, q in pts) / len(pts))
    return a, b, sd


def brier(rows, k=None, ks=None):
    out = []
    for x in rows:
        kk = ks.get(bucket_of(x), 1.0) if ks is not None else (k if k is not None else 1.0)
        out.append((x["g"], (pk(x["z"], kk) - x["y"]) ** 2))
    return out


def report(sport):
    rows, drop, n_states = load(sport)
    if not rows:
        print(f"\n## {sport}: no graded states on ledger dates <= {UNTIL}")
        return
    dates = sorted({x["date"] for x in rows})
    print(f"\n## {sport}: ledger dates {dates[0]}..{dates[-1]} ({len(dates)}), states {n_states}, graded {len(rows)} / "
          f"{len({x['g'] for x in rows})} games (priced {sum(x['priced'] for x in rows)}); dropped {dict(drop)}")

    print("   progress   states games  final-mean  err sd  implied sd  ratio   k(in-sample)   (final-line) = a + b(mean-line), resid sd")
    ks_all = {}
    for lab, lo, hi in BUCKETS:
        b = [x for x in rows if bucket_of(x) == lab]
        if not b:
            continue
        res = [x["final"] - x["mean"] for x in b if x["mean"] is not None]
        imp = [abs(x["mean"] - x["line"]) / abs(x["z"]) for x in b if x["mean"] is not None and abs(x["z"]) > 0.25]
        m = sum(res) / len(res) if res else float("nan")
        sd = math.sqrt(sum((v - m) ** 2 for v in res) / len(res)) if res else float("nan")
        isd = median(imp) if imp else float("nan")
        ks_all[lab] = fit_k(b)
        oa, ob, osd = ols(b)
        print(f"   {lab:<9} {len(b):>7} {len({x['g'] for x in b}):>5}  {m:>+9.2f}  {sd:>6.2f}  {isd:>10.2f}  "
              f"{sd / isd if isd == isd and isd else float('nan'):>5.2f}   {ks_all[lab]:.3f}          "
              f"a {oa:+.2f}  b {ob:.2f}  sd {osd:.2f}")
    k1 = fit_k(rows)
    b1 = g.cl_mean(brier(rows, 1.0))
    bk = g.cl_mean(brier(rows, k1))
    mk = [(x["g"], (x["pf"] - x["y"]) ** 2) for x in rows if x["pf"] is not None]
    bm = g.cl_mean(mk) if mk else (float("nan"), float("nan"), 0, 0)
    print(f"   in-sample one k = {k1:.3f}: Brier {b1[0]:.4f} (k=1) -> {bk[0]:.4f}; market Brier on the {bm[2]} rows with a "
          f"fair price {bm[0]:.4f}; log loss {logloss(rows, 1.0):.4f} -> {logloss(rows, k1):.4f}")

    # WALK-FORWARD: fit on all earlier dates, score the next date. The first two dates only train.
    oos_one, oos_bkt, oos_mkt1, oos_mktk, oos_w = [], [], [], [], []
    path = []
    for i in range(2, len(dates)):
        train = [x for x in rows if x["date"] < dates[i]]
        test = [x for x in rows if x["date"] == dates[i]]
        k = fit_k(train)
        kb = {lab: fit_k([x for x in train if bucket_of(x) == lab]) for lab, _lo, _hi in BUCKETS}
        kw = {lab: width_ratio([x for x in train if bucket_of(x) == lab]) for lab, _lo, _hi in BUCKETS}
        path.append(f"{dates[i][5:]}:{k:.2f}")
        for x in test:
            base = (pk(x["z"], 1.0) - x["y"]) ** 2
            one = (pk(x["z"], k) - x["y"]) ** 2
            kk = kb.get(bucket_of(x), k) if bucket_of(x) else k
            bkt = (pk(x["z"], kk) - x["y"]) ** 2
            wk = kw.get(bucket_of(x), 1.0) if bucket_of(x) else 1.0
            oos_w.append((x["g"], (pk(x["z"], wk) - x["y"]) ** 2 - base))
            oos_one.append((x["g"], one - base))
            oos_bkt.append((x["g"], bkt - base))
            if x["pf"] is not None:
                mk_ = (x["pf"] - x["y"]) ** 2
                oos_mkt1.append((x["g"], base - mk_))
                oos_mktk.append((x["g"], one - mk_))
    if oos_one:
        a, b = g.cl_mean(oos_one), g.cl_mean(oos_bkt)
        c, d = g.cl_mean(oos_mkt1), g.cl_mean(oos_mktk)
        print(f"   WALK-FORWARD on {len(dates) - 2} dates ({a[2]} states / {a[3]} games); k per step {' '.join(path)}")
        print(f"     Brier, one k minus k=1:        {g.fmt(a[0], a[1])}   (negative = the fit helps)")
        print(f"     Brier, k per bucket minus k=1: {g.fmt(b[0], b[1])}")
        w = g.cl_mean(oos_w)
        print(f"     Brier, PURE WIDTH (err sd / implied sd per bucket) minus k=1: {g.fmt(w[0], w[1])}")
        print(f"     Brier model - market: k=1 {g.fmt(c[0], c[1])}  ->  one k {g.fmt(d[0], d[1])}  ({c[2]} states)")
    else:
        print("   WALK-FORWARD: fewer than 3 dates, not run")


for sp in SPORTS:
    report(sp)
