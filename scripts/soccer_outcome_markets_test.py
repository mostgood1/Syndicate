"""Do the live signals improve END-OF-MATCH and LONG-HORIZON market predictions?

The short-window "goal in the next 2 minutes" signal decays in ~60s. The
DIRECTIONAL signal (which team scores next) does not -- 94% of it survives a
60s lag and 88% a 300s lag. A slow signal should pay on slow markets, and those
are the ones actually quoted in-play: match winner, total goals, BTTS, team to
score in the next 15 minutes, goal before a period ends.

Every target is computed from the live state at sample time t (every 60s, all
holdout matches), and every baseline is the state a book already knows: clock,
score difference, goals so far, home flag. The signals are the only thing
added. If the baseline alone matches the full model, the signal is worthless
for that market even if it is real.

CORNERS ARE NOT HERE. The FotMob cache carries corners only as full-match
totals under `content.stats`, which are known at the whistle and would leak.
Timed corner events exist in the ESPN commentary cache (370 matches) -- a
different source, an order of magnitude smaller, and untested against these
signals. Stated rather than faked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

from scripts.soccer_goal_model_test import _hold, wilson
from scripts.soccer_load_2y import load_2y

OUT = Path("reports/soccer_backtest/outcome_markets_test.json")
HL = 60.0


def build(matches, step=60.0):
    """Per sample: baseline state, signals, and every long-horizon label."""
    B, S, L, T, LG = [], [], {}, [], []
    keys = ["home_win", "draw", "away_win", "rem_ge1", "rem_ge2", "btts_pending",
            "btts_label", "home_in_900", "away_in_900", "goal_in_900",
            "goal_before_half_end", "goal_before_75"]
    for k in keys:
        L[k] = []
    for m in matches:
        shots, goals = m["shots"], m["goals"]
        st = np.array([s["t"] for s in shots], dtype=float)
        sxg = np.array([s.get("xg", 0.0) for s in shots], dtype=float)
        sh = np.array([1.0 if s.get("home") else -1.0 for s in shots])
        gt = np.array([g["t"] for g in goals], dtype=float)
        gh = np.array([1.0 if g["home"] else 0.0 for g in goals])
        fh_stop = float(m.get("first_half_stoppage_min") or 0.0)
        half_end = (45.0 + fh_stop) * 60.0
        last = max(st.max() if st.size else 0.0, gt.max() if gt.size else 0.0, half_end)
        end = min(5700.0, last)
        times = np.arange(60.0, end - 120.0, step)
        if times.size == 0:
            continue
        if st.size:
            dt = times[:, None] - st[None, :]
            w = np.where(dt >= 0, np.power(0.5, np.maximum(dt, 0) / HL), 0.0)
            xg_signed = w @ (sxg * sh)
            xg_abs = w @ sxg
        else:
            xg_signed = xg_abs = np.zeros_like(times)
        vm = m.get("vendor_momentum") or []
        vt = np.array([q["t"] for q in vm]) if vm else np.zeros(0)
        vv = np.array([q["value"] for q in vm]) if vm else np.zeros(0)
        if vt.size:
            idx = np.searchsorted(vt, times, side="right") - 1
            vsig = np.where(idx >= 0, vv[np.clip(idx, 0, None)], 0.0)
        else:
            vsig = np.zeros_like(times)
        final_h = float(gh.sum()) if gt.size else 0.0
        final_a = float((1 - gh).sum()) if gt.size else 0.0
        if gt.size:
            before = (gt[None, :] <= times[:, None]).astype(float)
            sc_h = before @ gh
            sc_a = before @ (1.0 - gh)
            fut = lambda lo, hi: (gt[None, :] > lo[:, None]) & (gt[None, :] <= hi[:, None])
            f900 = fut(times, times + 900.0)
            home_900 = (f900 & (gh[None, :] == 1)).any(axis=1)
            away_900 = (f900 & (gh[None, :] == 0)).any(axis=1)
            rem = (final_h + final_a) - (sc_h + sc_a)
            hend = np.full(times.size, half_end)
            g_half = ((gt[None, :] > times[:, None]) & (gt[None, :] <= hend[:, None])).any(axis=1)
            g75 = ((gt[None, :] > times[:, None]) & (gt[None, :] <= 75 * 60.0)).any(axis=1)
        else:
            sc_h = sc_a = np.zeros_like(times)
            home_900 = away_900 = np.zeros(times.size, bool)
            rem = np.zeros_like(times)
            g_half = g75 = np.zeros(times.size, bool)
        diff = sc_h - sc_a
        B.append(np.column_stack([times / 5700.0, (times / 5700.0) ** 2, diff, np.abs(diff), sc_h + sc_a]))
        S.append(np.column_stack([vsig, np.abs(vsig), xg_signed, xg_abs]))
        L["home_win"].append(np.full(times.size, 1.0 if final_h > final_a else 0.0))
        L["draw"].append(np.full(times.size, 1.0 if final_h == final_a else 0.0))
        L["away_win"].append(np.full(times.size, 1.0 if final_a > final_h else 0.0))
        L["rem_ge1"].append((rem >= 1).astype(float))
        L["rem_ge2"].append((rem >= 2).astype(float))
        pend = (sc_h == 0) | (sc_a == 0)
        L["btts_pending"].append(pend)
        L["btts_label"].append(np.full(times.size, 1.0 if (final_h > 0 and final_a > 0) else 0.0))
        L["home_in_900"].append(home_900.astype(float))
        L["away_in_900"].append(away_900.astype(float))
        L["goal_in_900"].append((home_900 | away_900).astype(float))
        # only meaningful while in the first half / before 75'
        L["goal_before_half_end"].append(np.where(times < half_end - 120.0, g_half.astype(float), -1.0))
        L["goal_before_75"].append(np.where(times < 73 * 60.0, g75.astype(float), -1.0))
        T.append(times)
        LG.append(np.full(times.size, m["league"]))
    return (np.vstack(B), np.vstack(S), {k: np.concatenate(v) for k, v in L.items()},
            np.concatenate(T), np.concatenate(LG))


def fit(X, y):
    m = LogisticRegression(max_iter=3000, C=1.0)
    m.fit(X, y)
    return m


def main() -> int:
    ms = load_2y()["matches"]
    fitm = [m for m in ms if not _hold(m["match_id"])]
    holdm = [m for m in ms if _hold(m["match_id"])]
    Btr, Str_, Ltr, Ttr, _ = build(fitm)
    Bte, Ste, Lte, Tte, LGte = build(holdm)
    print("holdout samples %d" % Bte.shape[0], flush=True)
    R = {}

    def run(name, ytr, yte, mtr=None, mte=None, note=""):
        mtr = np.ones(ytr.size, bool) if mtr is None else mtr
        mte = np.ones(yte.size, bool) if mte is None else mte
        if yte[mte].sum() < 50 or (1 - yte[mte]).sum() < 50:
            print("  %-24s insufficient positives/negatives" % name)
            return
        b = fit(Btr[mtr], ytr[mtr]); f = fit(np.hstack([Btr, Str_])[mtr], ytr[mtr])
        pb = b.predict_proba(Bte[mte])[:, 1]; pf = f.predict_proba(np.hstack([Bte, Ste])[mte])[:, 1]
        ab, af = roc_auc_score(yte[mte], pb), roc_auc_score(yte[mte], pf)
        lb, lf = log_loss(yte[mte], pb), log_loss(yte[mte], pf)
        # momentum-only increment
        mo = fit(np.hstack([Btr, Str_[:, :2]])[mtr], ytr[mtr])
        am = roc_auc_score(yte[mte], mo.predict_proba(np.hstack([Bte, Ste[:, :2]])[mte])[:, 1])
        # top-decile conviction
        o = np.argsort(-pf); k = int(len(o) * 0.1); top = o[:k]
        hits = int(yte[mte][top].sum()); ci = wilson(hits, k)
        base = float(yte[mte].mean())
        print("  %-24s n=%7d base %.3f | AUC state %.4f  +signals %.4f  d %+.4f (mom %+.4f) | LL d %+.5f | top-decile %.3f [%.3f,%.3f] lift %.2fx%s"
              % (name, int(mte.sum()), base, ab, af, af - ab, am - ab, lb - lf, hits / k, ci[0], ci[1], (hits / k) / base, note), flush=True)
        R[name] = {"n": int(mte.sum()), "base": base, "auc_state": ab, "auc_full": af, "d_auc": af - ab,
                   "d_auc_momentum_only": am - ab, "d_logloss": lb - lf,
                   "top_decile": hits / k, "top_decile_ci": ci, "top_decile_lift": (hits / k) / base}

    print("\n=== MATCH WINNER (from live state at t) ===")
    for k in ("home_win", "draw", "away_win"):
        run(k, Ltr[k], Lte[k])
    print("\n=== TOTAL GOALS: goals REMAINING in the match (live over/under primitive) ===")
    run("remaining >= 1", Ltr["rem_ge1"], Lte["rem_ge1"])
    run("remaining >= 2", Ltr["rem_ge2"], Lte["rem_ge2"])
    print("\n=== BOTH TEAMS TO SCORE (while at least one side has not yet scored) ===")
    run("btts", Ltr["btts_label"], Lte["btts_label"], Ltr["btts_pending"], Lte["btts_pending"])
    print("\n=== TEAM TO SCORE AND WHEN: within the next 15 minutes ===")
    run("home scores in 15m", Ltr["home_in_900"], Lte["home_in_900"])
    run("away scores in 15m", Ltr["away_in_900"], Lte["away_in_900"])
    run("any goal in 15m", Ltr["goal_in_900"], Lte["goal_in_900"])
    print("\n=== GOAL TIMING WITHIN A PERIOD ===")
    m1 = Ltr["goal_before_half_end"] >= 0; m2 = Lte["goal_before_half_end"] >= 0
    run("goal before half ends", np.clip(Ltr["goal_before_half_end"], 0, 1), np.clip(Lte["goal_before_half_end"], 0, 1), m1, m2, "  (1st-half samples)")
    m1 = Ltr["goal_before_75"] >= 0; m2 = Lte["goal_before_75"] >= 0
    run("goal before 75'", np.clip(Ltr["goal_before_75"], 0, 1), np.clip(Lte["goal_before_75"], 0, 1), m1, m2)

    # winner: where in the match does momentum matter most?
    print("\n=== WINNER signal by time band (home_win, dAUC from signals) ===")
    b = fit(Btr, Ltr["home_win"]); f = fit(np.hstack([Btr, Str_]), Ltr["home_win"])
    pb = b.predict_proba(Bte)[:, 1]; pf = f.predict_proba(np.hstack([Bte, Ste]))[:, 1]
    y = Lte["home_win"]; byt = []
    for lo in range(0, 90, 15):
        s = (Tte >= lo * 60) & (Tte < (lo + 15) * 60)
        if s.sum() < 500:
            continue
        d = roc_auc_score(y[s], pf[s]) - roc_auc_score(y[s], pb[s])
        print("  %2d-%-3d n=%6d  AUC state %.4f  +signals %.4f  d %+.4f" % (lo, lo + 15, int(s.sum()), roc_auc_score(y[s], pb[s]), roc_auc_score(y[s], pf[s]), d))
        byt.append({"lo": lo, "hi": lo + 15, "n": int(s.sum()), "d_auc": d})
    R["home_win_by_time"] = byt

    OUT.write_text(json.dumps(R, indent=2, default=float), encoding="utf-8")
    print("\nwrote %s" % OUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
