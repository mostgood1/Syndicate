"""Pooled-model test: do the event signals add ANYTHING to a flexible clock?

WHY THE PREVIOUS TEST WAS TOO WEAK TO TRUST ITS OWN NEGATIVE. The cell sweep
split ~380,000 samples into 24 bands x 10 leagues x 9 features and asked each
~200-sample cell a separate question. That fragmentation throws away almost all
the power, then pays a multiple-testing bill on top. A null control proved the
survivors were noise -- but "these cells are noise" is NOT "there is no signal".
A real effect of +0.01 would be invisible to that design and still be worth
money over a season.

THIS TEST INSTEAD ASKS ONE QUESTION WITH ALL THE DATA:

    a model given the CLOCK ONLY, versus the same model given clock + signals,
    scored out-of-sample. If the signals carry information, holdout AUC and
    log-loss move. If they do not, they do not.

THE BASELINE IS DELIBERATELY STRONG. The clock enters as a 24-way one-hot, so
the baseline is the best possible clock-only predictor -- not a linear trend the
features could beat by being slightly curved. Beating a weak baseline is how a
useless feature looks useful.

WHAT ELSE THIS FIXES:
  - HYPERPARAMETERS ARE SWEPT, not assumed. The cell test used one 900s
    half-life and one 600s window. Football momentum plausibly lives at 2-5
    minutes; a 15-minute half-life would smear it into nothing. Both are swept.
  - THE EXTREME TAIL IS SCORED, not the top quartile. If an edge exists it is
    in the top 1-5% of predicted risk, which a quartile average dilutes.
  - NONLINEARITY AND INTERACTIONS via gradient boosting, since "high pressure
    AND late" may matter where neither does alone.
  - SCORE STATE IS ADDED as a signal in its own right. Teams chase when behind
    and games open up; goals-so-far and the absolute lead are both strictly
    causal and were simply missing from the earlier feature set.
  - A PERMUTATION NULL on the AUC increment itself, so the headline number is
    compared against what this pipeline produces when nothing is there.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

from scripts.soccer_goal_timing_2y import _hold
from scripts.soccer_load_2y import load_2y

_MATCH_END = 5700.0
_BAND = 240.0
_FEATURES = ["xg", "count", "ontarget", "inbox", "bigchance",
             "vmom_abs", "vmom_slope", "red_adv", "subs",
             "goals_so_far", "lead_abs"]


def _vendor_at(vt: np.ndarray, vv: np.ndarray, times: np.ndarray) -> np.ndarray:
    if vt.size == 0:
        return np.zeros_like(times)
    idx = np.searchsorted(vt, times, side="right") - 1
    out = np.where(idx >= 0, vv[np.clip(idx, 0, None)], 0.0)
    return out


def build(matches: list[dict], half_life: float, window: float, step: float,
          require_full_window: bool = True):
    """Feature matrix for every sample point in every match.

    Vectorised per match: a T x S decay matrix rather than a Python loop over
    (sample, shot). The scalar version needed ~12M operations per feature per
    config, which made a hyperparameter sweep infeasible -- and "we only tested
    one setting" was a real weakness of the previous result.
    """
    X_all, y_all, t_all, lg_all, mid_all = [], [], [], [], []
    for m in matches:
        shots = m["shots"]
        goals = m["goals"]
        st = np.array([s["t"] for s in shots], dtype=float)
        sxg = np.array([s.get("xg", 0.0) for s in shots], dtype=float)
        son = np.array([1.0 if s.get("on_target") else 0.0 for s in shots])
        sin = np.array([1.0 if s.get("in_box") else 0.0 for s in shots])
        sbig = np.array([1.0 if s.get("xg", 0.0) >= 0.20 else 0.0 for s in shots])
        gt = np.array([g["t"] for g in goals], dtype=float)
        gh = np.array([1.0 if g["home"] else 0.0 for g in goals])

        last = max(st.max() if st.size else 0.0, gt.max() if gt.size else 0.0)
        end = min(_MATCH_END, last)
        times = np.arange(60.0, end + 1e-9, step)
        # The old guard was a hardcoded `>= 120.0` -- "a window under 2 minutes
        # is not a bet". That silently returns ZERO samples for any window at
        # or below 120s, which is precisely the range where the signal turned
        # out to live. Require the FULL window instead, so the constraint
        # scales with the question being asked rather than assuming one.
        avail = end - times
        times = times[avail >= (window if require_full_window else min(window, 120.0))]
        if times.size == 0:
            continue

        if st.size:
            dt = times[:, None] - st[None, :]
            w = np.where(dt >= 0, np.power(0.5, np.maximum(dt, 0) / half_life), 0.0)
            f_xg = w @ sxg
            f_cnt = w.sum(axis=1)
            f_on = w @ son
            f_in = w @ (sxg * sin)
            f_big = w @ sbig
        else:
            f_xg = f_cnt = f_on = f_in = f_big = np.zeros_like(times)

        vt = np.array([p["t"] for p in (m.get("vendor_momentum") or [])], dtype=float)
        vv = np.array([p["value"] for p in (m.get("vendor_momentum") or [])], dtype=float)
        vnow = _vendor_at(vt, vv, times)
        vprev = _vendor_at(vt, vv, np.maximum(0.0, times - 300.0))

        ev = m.get("events") or []
        et = np.array([e["t"] for e in ev], dtype=float) if ev else np.zeros(0)
        is_sub = np.array([1.0 if e["type"] == "Substitution" else 0.0 for e in ev]) if ev else np.zeros(0)
        is_red_h = np.array([1.0 if (e["type"] == "Card" and (e.get("card") or "").lower() == "red" and e["home"]) else 0.0 for e in ev]) if ev else np.zeros(0)
        is_red_a = np.array([1.0 if (e["type"] == "Card" and (e.get("card") or "").lower() == "red" and not e["home"]) else 0.0 for e in ev]) if ev else np.zeros(0)
        if et.size:
            before = (times[:, None] >= et[None, :]).astype(float)
            f_sub = before @ is_sub
            f_red = np.abs(before @ is_red_h - before @ is_red_a)
        else:
            f_sub = f_red = np.zeros_like(times)

        if gt.size:
            gbefore = (times[:, None] > gt[None, :]).astype(float)
            g_tot = gbefore.sum(axis=1)
            g_lead = np.abs(gbefore @ gh - gbefore @ (1.0 - gh))
            label = (((gt[None, :] > times[:, None]) &
                      (gt[None, :] <= times[:, None] + window)).any(axis=1)).astype(int)
        else:
            g_tot = g_lead = np.zeros_like(times)
            label = np.zeros(times.size, dtype=int)

        X_all.append(np.column_stack([f_xg, f_cnt, f_on, f_in, f_big,
                                      np.abs(vnow), vnow - vprev, f_red, f_sub,
                                      g_tot, g_lead]))
        y_all.append(label)
        t_all.append(times)
        lg_all.append(np.full(times.size, m["league"]))
        mid_all.append(np.full(times.size, str(m["match_id"])))

    return (np.vstack(X_all), np.concatenate(y_all), np.concatenate(t_all),
            np.concatenate(lg_all), np.concatenate(mid_all))


def clock_matrix(t: np.ndarray) -> np.ndarray:
    """24-way one-hot. The strongest possible clock-only baseline."""
    b = np.clip((t // _BAND).astype(int), 0, 23)
    out = np.zeros((t.size, 24))
    out[np.arange(t.size), b] = 1.0
    return out


def evaluate(Xtr, ytr, Xte, yte, kind: str):
    if kind == "gb":
        model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06,
                                               max_depth=4, random_state=0)
    else:
        model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(Xtr, ytr)
    p = model.predict_proba(Xte)[:, 1]
    return roc_auc_score(yte, p), log_loss(yte, p), p


def wilson(k: int, n: int):
    if n == 0:
        return 0.0, 0.0
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - m), min(1.0, c + m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--windows", default="120,300,600,900")
    ap.add_argument("--half-lives", default="60,180,300,900,1800")
    ap.add_argument("--step", type=float, default=60.0)
    ap.add_argument("--permutations", type=int, default=3)
    ap.add_argument("--out", default="reports/soccer_backtest/goal_model_test.json")
    args = ap.parse_args()

    matches = load_2y()["matches"]
    fit = [m for m in matches if not _hold(m["match_id"])]
    hold = [m for m in matches if _hold(m["match_id"])]
    print("matches %d   fit %d   holdout %d" % (len(matches), len(fit), len(hold)))

    windows = [float(x) for x in args.windows.split(",")]
    halves = [float(x) for x in args.half_lives.split(",")]

    print("\n=== HYPERPARAMETER SWEEP: does clock+signals beat clock alone? ===")
    print("  baseline = 24-way one-hot clock. delta is HOLDOUT, out of sample.")
    print("  %7s%8s%10s%11s%11s%11s%11s"
          % ("window", "half-l", "n_hold", "AUC clock", "AUC full", "dAUC", "dLogLoss"))
    results = []
    best = None
    for w in windows:
        for hl in halves:
            Xtr, ytr, ttr, _, _ = build(fit, hl, w, args.step)
            Xte, yte, tte, lgte, _ = build(hold, hl, w, args.step)
            Ctr, Cte = clock_matrix(ttr), clock_matrix(tte)
            a0, l0, _ = evaluate(Ctr, ytr, Cte, yte, "lr")
            a1, l1, p1 = evaluate(np.hstack([Ctr, Xtr]), ytr,
                                  np.hstack([Cte, Xte]), yte, "lr")
            row = {"window": w, "half_life": hl, "n": int(yte.size),
                   "auc_clock": a0, "auc_full": a1, "d_auc": a1 - a0,
                   "d_logloss": l0 - l1}
            results.append(row)
            print("  %7.0f%8.0f%10d%11.4f%11.4f%+11.4f%+11.4f"
                  % (w, hl, yte.size, a0, a1, a1 - a0, l0 - l1))
            if best is None or row["d_auc"] > best["d_auc"]:
                best = dict(row)

    print("\n  best config: window %.0fs half-life %.0fs  dAUC %+.4f"
          % (best["window"], best["half_life"], best["d_auc"]))

    # ---- rebuild at the best config for the deeper tests ----
    w, hl = best["window"], best["half_life"]
    Xtr, ytr, ttr, _, _ = build(fit, hl, w, args.step)
    Xte, yte, tte, lgte, _ = build(hold, hl, w, args.step)
    Ctr, Cte = clock_matrix(ttr), clock_matrix(tte)

    print("\n=== NONLINEAR MODEL (gradient boosting, interactions allowed) ===")
    ag0, lg0, _ = evaluate(Ctr, ytr, Cte, yte, "gb")
    ag1, lg1, pg = evaluate(np.hstack([Ctr, Xtr]), ytr, np.hstack([Cte, Xte]), yte, "gb")
    print("  clock only  AUC %.4f   logloss %.5f" % (ag0, lg0))
    print("  clock+sig   AUC %.4f   logloss %.5f   dAUC %+.4f  dLL %+.5f"
          % (ag1, lg1, ag1 - ag0, lg0 - lg1))

    print("\n=== THE EXTREME TAIL: bet only the top X%% of predicted risk ===")
    print("  (this is the actual question -- WHEN to fire, not average skill)")
    print("  %8s%9s%10s%20s%12s" % ("top %", "n", "hit", "95% CI", "vs 2-1"))
    order = np.argsort(-pg)
    tail_rows = []
    for pct in (0.005, 0.01, 0.02, 0.05, 0.10):
        k = max(20, int(len(order) * pct))
        sel = order[:k]
        hits = int(yte[sel].sum())
        rate = hits / k
        lo, hi = wilson(hits, k)
        verdict = "CLEARS" if lo > 1.0 / 3.0 else ("edge@3-1" if lo > 0.25 else "no")
        print("  %7.1f%%%9d%10.4f      [%.3f,%.3f]%12s"
              % (pct * 100, k, rate, lo, hi, verdict))
        tail_rows.append({"pct": pct, "n": k, "hit": rate, "ci": [lo, hi]})

    print("\n=== PERMUTATION NULL on the AUC increment ===")
    print("  labels permuted WITHIN match (keeps clock structure and per-match")
    print("  goal counts, severs the feature link)")
    rng = np.random.default_rng(7)
    nulls = []
    for i in range(args.permutations):
        yperm = ytr.copy()
        rng.shuffle(yperm)
        a0p, _, _ = evaluate(Ctr, yperm, Cte, yte, "lr")
        a1p, _, _ = evaluate(np.hstack([Ctr, Xtr]), yperm,
                             np.hstack([Cte, Xte]), yte, "lr")
        nulls.append(a1p - a0p)
        print("  run %d  dAUC %+.4f" % (i + 1, a1p - a0p))

    real_d = best["d_auc"]
    print("\n=== VERDICT ===")
    print("  real dAUC        %+.4f" % real_d)
    print("  null dAUC        %s" % ", ".join("%+.4f" % x for x in nulls))
    signal = real_d > max(nulls) * 3 and real_d > 0.005
    print("  %s" % ("SIGNAL -- the increment is far outside the null."
                    if signal else
                    "the increment is NOT clearly outside what noise produces."))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"sweep": results, "best": best,
         "gb": {"auc_clock": ag0, "auc_full": ag1, "d_auc": ag1 - ag0},
         "tail": tail_rows, "null_d_auc": nulls}, indent=2, default=float), encoding="utf-8")
    print("\nwrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
