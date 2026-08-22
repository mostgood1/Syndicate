"""Deep dive: what DECISIONS can the momentum/xG signals actually support?

"Is there a signal" was answered this evening (yes, small, short-lived, driven
by FotMob momentum). That is not a decision. A decision needs:

  1. CALIBRATION -- a probability the model says is 9% must come true 9% of
     the time, or it cannot be compared to a book price at all.
  2. DIRECTION -- "a goal is coming" is a different market from "HOME scores
     next". The second is quoted with no time limit, so the 60s half-life
     stops being a constraint.
  3. ANTICIPATION vs REACTION -- momentum that only rises AFTER goals cannot
     inform a bet placed before them. Strip the post-goal reaction and see
     what survives.
  4. CONTEXT -- where in the match, at what score state, in which leagues,
     does the signal carry weight? A pooled number hides all of that.
  5. ECONOMICS -- at what book price does firing on the signal make money,
     under explicit assumptions about how sophisticated the book is.
  6. THE OTHER SIDE -- does the model identify LULLS? "No goal" is a market
     too, and books may reprice lulls less aggressively than spikes.
  7. FREQUENCY -- how often per match does an actionable moment occur? A
     signal that fires twice a season is not a strategy.

Every number is HOLDOUT (id-hash split, never touched for selection). Every
rate carries an interval. The same discipline that caught five false positives
today applies here.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

from scripts.soccer_goal_model_test import _hold, build, clock_matrix, wilson
from scripts.soccer_load_2y import load_2y

OUT = Path("reports/soccer_backtest/signal_decision_deepdive.json")
R: dict = {}


def p(msg=""):
    print(msg, flush=True)


def fit_gb(Xtr, ytr):
    m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_depth=4, random_state=0)
    m.fit(Xtr, ytr)
    return m


def fit_lr(Xtr, ytr):
    m = LogisticRegression(max_iter=3000, C=1.0)
    m.fit(Xtr, ytr)
    return m


# ----------------------------------------------------------------------------
# directional feature builder: SIGNED pressure, next-goal-team labels
# ----------------------------------------------------------------------------
def build_directional(matches, half_life, step=60.0):
    X, y_next, y_win300, t_all, lg_all, has_next = [], [], [], [], [], []
    for m in matches:
        shots, goals = m["shots"], m["goals"]
        st = np.array([s["t"] for s in shots], dtype=float)
        sxg = np.array([s.get("xg", 0.0) for s in shots], dtype=float)
        sh = np.array([1.0 if s.get("home") else -1.0 for s in shots])
        gt = np.array([g["t"] for g in goals], dtype=float)
        gh = np.array([1.0 if g["home"] else 0.0 for g in goals])
        last = max(st.max() if st.size else 0.0, gt.max() if gt.size else 0.0)
        end = min(5700.0, last)
        times = np.arange(60.0, end - 60.0, step)
        if times.size == 0:
            continue
        if st.size:
            dt = times[:, None] - st[None, :]
            w = np.where(dt >= 0, np.power(0.5, np.maximum(dt, 0) / half_life), 0.0)
            xg_signed = w @ (sxg * sh)          # home positive, away negative
            cnt_signed = w @ sh
        else:
            xg_signed = cnt_signed = np.zeros_like(times)
        vm = m.get("vendor_momentum") or []
        vt = np.array([q["t"] for q in vm]) if vm else np.zeros(0)
        vv = np.array([q["value"] for q in vm]) if vm else np.zeros(0)
        if vt.size:
            idx = np.searchsorted(vt, times, side="right") - 1
            vsig = np.where(idx >= 0, vv[np.clip(idx, 0, None)], 0.0)
        else:
            vsig = np.zeros_like(times)
        if gt.size:
            before = (gt[None, :] <= times[:, None]).astype(float)
            sdiff = before @ gh - before @ (1.0 - gh)      # home minus away
            # next goal after t: team
            nxt = np.full(times.size, -1.0)
            hn = np.zeros(times.size, dtype=bool)
            for i, tt in enumerate(times):
                fut = np.where(gt > tt)[0]
                if fut.size:
                    nxt[i] = gh[fut[0]]
                    hn[i] = True
            win = ((gt[None, :] > times[:, None]) & (gt[None, :] <= times[:, None] + 300.0))
            # within-300s directional: 1 home, 0 away, only if exactly one side scores
            w_home = (win & (gh[None, :] == 1)).any(axis=1)
            w_away = (win & (gh[None, :] == 0)).any(axis=1)
        else:
            sdiff = np.zeros_like(times)
            nxt = np.full(times.size, -1.0)
            hn = np.zeros(times.size, dtype=bool)
            w_home = w_away = np.zeros(times.size, dtype=bool)
        X.append(np.column_stack([xg_signed, cnt_signed, vsig, sdiff, times / 5700.0]))
        y_next.append(nxt)
        has_next.append(hn)
        y_win300.append(np.where(w_home & ~w_away, 1.0, np.where(w_away & ~w_home, 0.0, -1.0)))
        t_all.append(times)
        lg_all.append(np.full(times.size, m["league"]))
    return (np.vstack(X), np.concatenate(y_next), np.concatenate(has_next),
            np.concatenate(y_win300), np.concatenate(t_all), np.concatenate(lg_all))


def main() -> int:
    matches = load_2y()["matches"]
    fit = [m for m in matches if not _hold(m["match_id"])]
    hold = [m for m in matches if _hold(m["match_id"])]
    p("matches %d  fit %d  holdout %d" % (len(matches), len(fit), len(hold)))
    R["n"] = {"matches": len(matches), "fit": len(fit), "holdout": len(hold)}

    # ======================================================================
    # 1. CALIBRATION of the best model (120s window, 60s half-life)
    # ======================================================================
    p("\n" + "=" * 72)
    p("1. CALIBRATION -- can the model's probability be compared to a price?")
    p("=" * 72)
    W, HL = 120.0, 60.0
    Xtr, ytr, ttr, lgtr, _ = build(fit, HL, W, 60.0)
    Xte, yte, tte, lgte, midte = build(hold, HL, W, 60.0)
    Ctr, Cte = clock_matrix(ttr), clock_matrix(tte)
    gb = fit_gb(np.hstack([Ctr, Xtr]), ytr)
    pg = gb.predict_proba(np.hstack([Cte, Xte]))[:, 1]
    gb0 = fit_gb(Ctr, ytr)
    p0 = gb0.predict_proba(Cte)[:, 1]
    base = float(yte.mean())
    p("  holdout n=%d  base %.4f  AUC clock %.4f  AUC full %.4f" %
      (yte.size, base, roc_auc_score(yte, p0), roc_auc_score(yte, pg)))
    p("\n  reliability (holdout, deciles of predicted prob):")
    p("  %8s%10s%10s%8s%22s" % ("decile", "pred", "observed", "n", "95% CI"))
    qs = np.quantile(pg, np.linspace(0, 1, 11))
    calib = []
    for i in range(10):
        lo, hi = qs[i], qs[i + 1]
        sel = (pg >= lo) & (pg <= hi) if i == 9 else (pg >= lo) & (pg < hi)
        if sel.sum() == 0:
            continue
        k = int(yte[sel].sum()); n = int(sel.sum())
        obs = k / n; ci = wilson(k, n)
        calib.append({"decile": i + 1, "pred": float(pg[sel].mean()), "obs": obs, "n": n, "ci": ci})
        p("  %8d%10.4f%10.4f%8d      [%.4f, %.4f]" % (i + 1, pg[sel].mean(), obs, n, ci[0], ci[1]))
    # expected calibration error
    ece = sum(abs(c["pred"] - c["obs"]) * c["n"] for c in calib) / yte.size
    p("  expected calibration error %.4f  (top decile pred %.4f vs obs %.4f)" %
      (ece, calib[-1]["pred"], calib[-1]["obs"]))
    R["calibration"] = {"ece": ece, "bins": calib, "base": base,
                        "auc_clock": roc_auc_score(yte, p0), "auc_full": roc_auc_score(yte, pg)}

    # ======================================================================
    # 2. ANTICIPATION vs REACTION -- strip the post-goal window
    # ======================================================================
    p("\n" + "=" * 72)
    p("2. ANTICIPATION vs REACTION -- does the signal survive with no recent goal?")
    p("=" * 72)
    # goals_so_far is column 9 in build(); need "time since last goal" -- rebuild cheaply
    tsl_te = np.full(yte.size, 9999.0)
    i0 = 0
    for m in hold:
        gt = np.array([g["t"] for g in m["goals"]], dtype=float)
        n_here = int(np.sum(midte == str(m["match_id"])))
        if n_here == 0:
            continue
        tt = tte[i0:i0 + n_here]
        if gt.size:
            past = np.where(gt[None, :] <= tt[:, None], tt[:, None] - gt[None, :], np.inf)
            tsl_te[i0:i0 + n_here] = past.min(axis=1)
        i0 += n_here
    # (same for train)
    tsl_tr = np.full(ytr.size, 9999.0)
    i0 = 0
    mid_tr = None
    _, _, _, _, mid_tr = build(fit, HL, W, 60.0)
    for m in fit:
        gt = np.array([g["t"] for g in m["goals"]], dtype=float)
        n_here = int(np.sum(mid_tr == str(m["match_id"])))
        if n_here == 0:
            continue
        tt = ttr[i0:i0 + n_here]
        if gt.size:
            past = np.where(gt[None, :] <= tt[:, None], tt[:, None] - gt[None, :], np.inf)
            tsl_tr[i0:i0 + n_here] = past.min(axis=1)
        i0 += n_here
    p("  %18s%10s%12s%12s%10s" % ("no goal in last", "n_hold", "AUC clock", "AUC full", "dAUC"))
    react = []
    for gap in (0.0, 120.0, 300.0, 600.0):
        mtr = tsl_tr > gap; mte = tsl_te > gap
        lr0 = fit_lr(Ctr[mtr], ytr[mtr]); lr1 = fit_lr(np.hstack([Ctr, Xtr])[mtr], ytr[mtr])
        a0 = roc_auc_score(yte[mte], lr0.predict_proba(Cte[mte])[:, 1])
        a1 = roc_auc_score(yte[mte], lr1.predict_proba(np.hstack([Cte, Xte])[mte])[:, 1])
        # momentum alone
        lrm = fit_lr(np.hstack([Ctr, Xtr[:, [5]]])[mtr], ytr[mtr])
        am = roc_auc_score(yte[mte], lrm.predict_proba(np.hstack([Cte, Xte[:, [5]]])[mte])[:, 1])
        p("  %15.0fs%10d%12.4f%12.4f%+10.4f   (momentum alone %+.4f)" %
          (gap, int(mte.sum()), a0, a1, a1 - a0, am - a0))
        react.append({"gap_s": gap, "n": int(mte.sum()), "auc_clock": a0, "auc_full": a1,
                      "d_auc": a1 - a0, "d_auc_momentum_only": am - a0})
    R["reaction_strip"] = react

    # ======================================================================
    # 3. CONTEXT -- score state, time band, league
    # ======================================================================
    p("\n" + "=" * 72)
    p("3. CONTEXT -- where does the signal carry weight?")
    p("=" * 72)
    lr_full = fit_lr(np.hstack([Ctr, Xtr]), ytr)
    lr_clk = fit_lr(Ctr, ytr)
    pf = lr_full.predict_proba(np.hstack([Cte, Xte]))[:, 1]
    pc = lr_clk.predict_proba(Cte)[:, 1]
    lead = Xte[:, 10]
    p("\n  by SCORE STATE (absolute lead):")
    p("  %10s%10s%12s%12s%10s" % ("lead", "n", "AUC clock", "AUC full", "dAUC"))
    ctx = {"score_state": [], "time": [], "league": []}
    for name, sel in (("level", lead == 0), ("one goal", lead == 1), ("2+", lead >= 2)):
        if sel.sum() < 500 or yte[sel].sum() < 20:
            continue
        a0 = roc_auc_score(yte[sel], pc[sel]); a1 = roc_auc_score(yte[sel], pf[sel])
        p("  %10s%10d%12.4f%12.4f%+10.4f" % (name, int(sel.sum()), a0, a1, a1 - a0))
        ctx["score_state"].append({"state": name, "n": int(sel.sum()), "d_auc": a1 - a0})
    p("\n  by TIME (15-min bands):")
    p("  %10s%10s%12s%12s%10s" % ("band", "n", "AUC clock", "AUC full", "dAUC"))
    for lo in range(0, 90, 15):
        sel = (tte >= lo * 60) & (tte < (lo + 15) * 60)
        if sel.sum() < 500 or yte[sel].sum() < 20:
            continue
        a0 = roc_auc_score(yte[sel], pc[sel]); a1 = roc_auc_score(yte[sel], pf[sel])
        p("  %6d-%-3d%10d%12.4f%12.4f%+10.4f" % (lo, lo + 15, int(sel.sum()), a0, a1, a1 - a0))
        ctx["time"].append({"lo": lo, "hi": lo + 15, "n": int(sel.sum()), "d_auc": a1 - a0})
    p("\n  by LEAGUE (pooled model, scored per league):")
    p("  %20s%10s%12s%12s%10s" % ("league", "n", "AUC clock", "AUC full", "dAUC"))
    for lg in sorted(set(lgte)):
        sel = lgte == lg
        if sel.sum() < 500:
            continue
        a0 = roc_auc_score(yte[sel], pc[sel]); a1 = roc_auc_score(yte[sel], pf[sel])
        p("  %20s%10d%12.4f%12.4f%+10.4f" % (lg, int(sel.sum()), a0, a1, a1 - a0))
        ctx["league"].append({"league": lg, "n": int(sel.sum()), "d_auc": a1 - a0})
    R["context"] = ctx

    # ======================================================================
    # 4. DIRECTION -- who scores next?
    # ======================================================================
    p("\n" + "=" * 72)
    p("4. DIRECTION -- the 'next team to score' market has NO time limit")
    p("=" * 72)
    Dtr, ntr, htr, wtr, dttr, _ = build_directional(fit, 60.0)
    Dte, nte, hte, wte, dtte, dlg = build_directional(hold, 60.0)
    # baseline: home advantage + score diff + clock; full: + signed xg, count, momentum
    btr, bte = Dtr[:, [3, 4]], Dte[:, [3, 4]]
    ftr, fte = Dtr, Dte
    p("\n  A. next goal (any time later in the match), home vs away:")
    sel_tr, sel_te = htr, hte
    lb = fit_lr(btr[sel_tr], ntr[sel_tr]); lf = fit_lr(ftr[sel_tr], ntr[sel_tr])
    ab = roc_auc_score(nte[sel_te], lb.predict_proba(bte[sel_te])[:, 1])
    af = roc_auc_score(nte[sel_te], lf.predict_proba(fte[sel_te])[:, 1])
    p("     n=%d   home share %.3f   AUC baseline(score,clock) %.4f   +signals %.4f   dAUC %+.4f" %
      (int(sel_te.sum()), float(nte[sel_te].mean()), ab, af, af - ab))
    dirA = {"n": int(sel_te.sum()), "auc_base": ab, "auc_full": af, "d_auc": af - ab}
    # which direction signal matters
    for j, nm in ((0, "signed xG"), (1, "signed count"), (2, "signed vendor momentum")):
        lj = fit_lr(np.column_stack([btr, Dtr[:, j]])[sel_tr], ntr[sel_tr])
        aj = roc_auc_score(nte[sel_te], lj.predict_proba(np.column_stack([bte, Dte[:, j]])[sel_te])[:, 1])
        p("       + %-24s AUC %.4f  (%+.4f)" % (nm, aj, aj - ab))
        dirA[nm] = aj - ab
    # decile lift for the directional model
    pd_ = lf.predict_proba(fte[sel_te])[:, 1]
    yy = nte[sel_te]
    order = np.argsort(pd_)
    p("     conviction deciles (pred P(home next) -> observed home share):")
    dec = []
    for i in range(10):
        idx = order[int(len(order) * i / 10):int(len(order) * (i + 1) / 10)]
        k = int(yy[idx].sum()); n = len(idx); ci = wilson(k, n)
        dec.append({"decile": i + 1, "pred": float(pd_[idx].mean()), "obs": k / n, "n": n, "ci": ci})
    for d in (dec[0], dec[4], dec[9]):
        p("       decile %2d  pred %.3f  obs %.3f  [%.3f,%.3f]  n=%d" %
          (d["decile"], d["pred"], d["obs"], d["ci"][0], d["ci"][1], d["n"]))
    dirA["deciles"] = dec
    p("\n  B. goal within 300s, home vs away (conditional on exactly one side scoring):")
    s_tr, s_te = wtr >= 0, wte >= 0
    lb = fit_lr(btr[s_tr], wtr[s_tr]); lf2 = fit_lr(ftr[s_tr], wtr[s_tr])
    ab2 = roc_auc_score(wte[s_te], lb.predict_proba(bte[s_te])[:, 1])
    af2 = roc_auc_score(wte[s_te], lf2.predict_proba(fte[s_te])[:, 1])
    p("     n=%d   AUC baseline %.4f   +signals %.4f   dAUC %+.4f" %
      (int(s_te.sum()), ab2, af2, af2 - ab2))
    R["direction"] = {"next_goal_any_time": dirA,
                      "within_300s": {"n": int(s_te.sum()), "auc_base": ab2, "auc_full": af2, "d_auc": af2 - ab2}}

    # ======================================================================
    # 5. ECONOMICS -- firing rules under explicit book models
    # ======================================================================
    p("\n" + "=" * 72)
    p("5. ECONOMICS -- when does firing on the signal make money?")
    p("=" * 72)
    p("  Two book models bracket reality:")
    p("    NAIVE book  prices 'goal in window' at the CLOCK rate for that band, +8% overround.")
    p("    SHARP book  prices it at OUR model's probability, +8% overround (edge = -vig).")
    p("  Reality sits between; the live-odds pilot (partial corr +0.14, n=106) will locate it.")
    econ = {}
    for Wn in (120.0, 300.0, 600.0):
        Xtr2, ytr2, ttr2, _, _ = build(fit, 60.0, Wn, 60.0)
        Xte2, yte2, tte2, _, mid2 = build(hold, 60.0, Wn, 60.0)
        Ctr2, Cte2 = clock_matrix(ttr2), clock_matrix(tte2)
        g = fit_gb(np.hstack([Ctr2, Xtr2]), ytr2)
        pp = g.predict_proba(np.hstack([Cte2, Xte2]))[:, 1]
        g0 = fit_gb(Ctr2, ytr2)
        pclk = g0.predict_proba(Cte2)[:, 1]
        order = np.argsort(-pp)
        p("\n  window %.0fs  base %.4f  AUC %.4f" % (Wn, yte2.mean(), roc_auc_score(yte2, pp)))
        p("  %7s%8s%9s%18s%10s%12s%12s" % ("top%", "n", "hit", "95% CI", "lift", "ROI naive", "fires/match"))
        rows = []
        n_matches_hold = len(set(mid2))
        for frac in (0.005, 0.01, 0.02, 0.05, 0.10):
            k = max(30, int(len(order) * frac)); sel = order[:k]
            hits = int(yte2[sel].sum()); hit = hits / k; ci = wilson(hits, k)
            # naive book: odds = 1/(clock_prob*1.08) per observation; ROI = mean(hit*odds - 1)
            naive_odds = 1.0 / np.clip(pclk[sel] * 1.08, 1e-6, 0.999)
            roi_naive = float(np.mean(yte2[sel] * naive_odds - 1.0))
            fires = k / n_matches_hold
            p("  %6.1f%%%8d%9.4f   [%.4f,%.4f]%10.2fx%+12.3f%12.2f" %
              (frac * 100, k, hit, ci[0], ci[1], hit / yte2.mean(), roi_naive, fires))
            rows.append({"frac": frac, "n": k, "hit": hit, "ci": ci, "lift": hit / yte2.mean(),
                         "roi_naive_book": roi_naive, "fires_per_match": fires})
        # LULL side
        lo_sel = order[-int(len(order) * 0.10):]
        lk = int(yte2[lo_sel].sum()); ln = len(lo_sel); lci = wilson(lk, ln)
        clk_lo = float(pclk[lo_sel].mean())
        p("  bottom 10%%: observed %.4f [%.4f,%.4f] vs clock-expected %.4f  -> lull ratio %.2fx" %
          (lk / ln, lci[0], lci[1], clk_lo, (lk / ln) / clk_lo))
        econ[str(int(Wn))] = {"base": float(yte2.mean()), "auc": roc_auc_score(yte2, pp),
                              "top": rows, "lull": {"obs": lk / ln, "ci": lci, "clock_expected": clk_lo}}
    R["economics"] = econ

    # ======================================================================
    # 6. MOMENTUM SEMANTICS -- what does a high reading mean, concretely?
    # ======================================================================
    p("\n" + "=" * 72)
    p("6. WHAT A MOMENTUM READING MEANS -- goal rate by vendor momentum band")
    p("=" * 72)
    vm = Xte[:, 5]
    p("  (120s window, holdout; clock-expected computed from the same samples)")
    p("  %14s%10s%10s%12s%10s" % ("|momentum|", "n", "goal%", "clock-exp", "ratio"))
    sem = []
    for lo, hi in ((0, 10), (10, 25), (25, 40), (40, 60), (60, 80), (80, 101)):
        sel = (vm >= lo) & (vm < hi)
        if sel.sum() < 200:
            continue
        obs = float(yte[sel].mean()); exp = float(p0[sel].mean())
        p("  %8d-%-5d%10d%10.4f%12.4f%10.2fx" % (lo, hi, int(sel.sum()), obs, exp, obs / exp))
        sem.append({"lo": lo, "hi": hi, "n": int(sel.sum()), "obs": obs, "clock_exp": exp})
    R["momentum_semantics"] = sem

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(R, indent=2, default=float), encoding="utf-8")
    p("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
