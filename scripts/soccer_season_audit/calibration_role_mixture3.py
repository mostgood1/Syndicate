# -*- coding: utf-8 -*-
"""Fix #2, THIRD measurement. PRE-REGISTERED 2026-09-15 ~20:00Z, after runs 1-2 and
before this one ran.

Run 2: H5 FALSIFIED (team-minutes shares make the UNCONDITIONAL ladder worse in the
big five, so they ship only inside a conditional ladder); H6 SUPPORTED (P(start |
appear) under-separated: starters 0.751, subs 0.409; low deciles 0.09 predicted vs
0.23 actual); H7 SUPPORTED (substitute per-minute intensity 1.87).

Two parameters, FITTED ON THE FIRST HALF ONLY (dates < 2026-08-26) by grid search on
pooled log loss at line 0.5 + line 1.5, then SCORED ON THE SECOND HALF:
  k  substitute intensity: mu_sub = k * r * 15.6/90,  grid 1.0..2.6 step 0.1
  c  pseudo-count weight on the prior in P(start | appear) = (s + c*prior) / (s + b + c),
     grid {0.25, 0.5, 1, 2, 4}
A linear recalibration of p_start is NOT fitted: two parameters on 6,567 rows is
the budget.

H8: on the SECOND HALF, MIX_T2 (fitted k, c) beats MIX_T (k=1, c=2) AND U_RAW (the
    board ladder once the divisor is retired) on pooled log loss at both lines, and
    beats U_RAW at line 0.5 in >= 8 of 10 leagues.
    FALSIFIED IF any pooled comparison is not lower, or fewer than 8 leagues.
H9: the fitted k lies within 1.5..2.2. Run 2 read 1.87 on ALL dates, including the
    second half; if the fit is elsewhere, the intensity effect is not stable
    across halves.
    FALSIFIED IF k is outside [1.5, 2.2].
"""
import collections
import contextlib
import importlib.util
import io
import math
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("crm", HERE / "calibration_role_mixture.py")
crm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crm)

import pandas as pd  # noqa: E402

from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles  # noqa: E402

CUT = "2026-08-26"
K_GRID = [round(1.0 + 0.1 * i, 1) for i in range(17)]
C_GRID = [0.25, 0.5, 1.0, 2.0, 4.0]


def collect():
    recs, outc = crm.load_recs(), crm.load_outcomes()
    hist = crm.role_history(outc)
    tmp = Path(crm.S) / "calib_mix3_root"
    shutil.rmtree(tmp, ignore_errors=True)
    root = crm.rs.build_root(tmp)
    crm.bsa.roster_rows = crm.rs.seed_roster_rows
    maxg = crm.club_max_games()
    rows_by_league = {}
    for league in crm.LEAGUES:
        with contextlib.redirect_stdout(io.StringIO()):
            rows = crm.bsa._load_player_rows(league, root)
        if league in crm.BIG_FIVE:
            for row in rows:
                season = str(row.get("season") or "").strip()
                season = int(float(season)) if season not in ("", "nan") else None
                minutes = pd.to_numeric(pd.Series([row.get("minutes")]), errors="coerce").iloc[0]
                club_games = maxg.get((league, season, str(row.get("team")))) if season else None
                if club_games and minutes == minutes and club_games > 0:
                    row["_team_share"] = round(min(1.0, float(minutes) / (club_games * 90.0)), 4)
        rows_by_league[league] = rows
    pts = []
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o or m["shots_h"] is None:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            feats = build_soccer_player_features(rows_by_league[lg], league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
        by_id = {str(r.get("player_id")): r for r in rows_by_league[lg]}
        for side, club, team_shots in (("home", m["home"], m["shots_h"]), ("away", m["away"], m["shots_a"])):
            base = [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, "team": f.team,
                     **dict(f.usage_metrics or {})} for f in feats if f.team == club]
            if not base or not team_shots:
                continue
            prof = {}
            for arm in ("A", "T"):
                rows = []
                for r in base:
                    r = dict(r)
                    src = by_id.get(str(r["player_id"]), {})
                    if arm == "T" and "_team_share" in src:
                        r["expected_minutes_share"] = src["_team_share"]
                    rows.append(r)
                prof[arm] = build_usage_profiles(rows, side=side, team=club)
            roster = [q for q in o["players"] if q["side"] == side]
            preds = [{"player_name": p.player_name, "side": side} for p in prof["A"]]
            for i, j in crm.strict_match(preds, roster).items():
                q = roster[j]
                pa, pt = prof["A"][i], prof["T"][i]
                if not crm.appeared(q) or pa.is_goalkeeper or pa.position.upper().startswith("G"):
                    continue
                s, b, _n = crm.prior_counts(hist, lg, club, q.get("name"), m["date"])
                mt = max(pt.expected_minutes_share, 1e-3)
                pts.append({"lg": lg, "date": m["date"], "starter": bool(q["starter"]),
                            "actual": float(q.get("shots") or 0.0), "s": s, "b": b,
                            "prior": min(0.95, max(0.05, mt / (crm.MIN_START / 90.0))),
                            "eu_a": team_shots * pa.shot_share, "r_t": team_shots * pt.shot_share / mt})
    return pts


def probs(x, arm, k=1.0, c=2.0):
    if arm == "U_RAW":
        mix = [(1.0, x["eu_a"])]
    else:
        p_start = (x["s"] + c * x["prior"]) / (x["s"] + x["b"] + c)
        mix = [(p_start, x["r_t"] * crm.MIN_START / 90.0), (1.0 - p_start, k * x["r_t"] * crm.MIN_SUB / 90.0)]
    out = []
    for kk in (1, 2):
        out.append(min(1 - crm.EPS, max(crm.EPS, sum(w * crm.p_ge(u, kk) for w, u in mix))))
    return out, sum(w * u for w, u in mix)


def loss(sel, arm, k=1.0, c=2.0):
    l1 = l2 = 0.0
    for x in sel:
        (p1, p2), _ = probs(x, arm, k, c)
        l1 -= math.log(p1) if x["actual"] >= 1 else math.log(1 - p1)
        l2 -= math.log(p2) if x["actual"] >= 2 else math.log(1 - p2)
    return l1 / len(sel), l2 / len(sel)


def main():
    pts = collect()
    train = [x for x in pts if x["date"] < CUT]
    test = [x for x in pts if x["date"] >= CUT]
    print(f"points {len(pts)} train {len(train)} test {len(test)} cut {CUT}")
    best = None
    for k in K_GRID:
        for c in C_GRID:
            l1, l2 = loss(train, "MIX", k, c)
            if best is None or l1 + l2 < best[0]:
                best = (l1 + l2, k, c)
    _, k_fit, c_fit = best
    print(f"FITTED on train: k={k_fit} c={c_fit}  (train LL sum {best[0]:.4f})")

    def row(title, sel):
        u = loss(sel, "U_RAW")
        m1 = loss(sel, "MIX", 1.0, 2.0)
        m2 = loss(sel, "MIX", k_fit, c_fit)
        r = lambda arm, k, c: crm.mean(probs(x, arm, k, c)[1] for x in sel) / max(crm.mean(x["actual"] for x in sel), 1e-9)  # noqa: E731
        st = [x for x in sel if x["starter"]]
        sb = [x for x in sel if not x["starter"]]
        print(f"  {title:22s} n={len(sel):5d} U_RAW {u[0]:.4f}/{u[1]:.4f}  MIX_T {m1[0]:.4f}/{m1[1]:.4f}  MIX_T2 {m2[0]:.4f}/{m2[1]:.4f}"
              f" | ratio U_RAW {r('U_RAW', 1, 2):.2f} MIX_T {r('MIX', 1, 2):.2f} MIX_T2 {r('MIX', k_fit, c_fit):.2f}"
              f" (T2 start {r('MIX', k_fit, c_fit) if False else crm.mean(probs(x, 'MIX', k_fit, c_fit)[1] for x in st) / max(crm.mean(x['actual'] for x in st), 1e-9):.2f}"
              f" sub {crm.mean(probs(x, 'MIX', k_fit, c_fit)[1] for x in sb) / max(crm.mean(x['actual'] for x in sb), 1e-9):.2f})")
        return u, m1, m2

    print("\n=== TRAIN (in-sample, for reference)")
    row("train pooled", train)
    print("\n=== TEST (held out)")
    u, m1, m2 = row("test pooled", test)
    wins = collections.Counter()
    for lg in crm.LEAGUES:
        sel = [x for x in test if x["lg"] == lg]
        if not sel:
            continue
        lu, _l1, l2 = row(lg, sel)
        wins["MIX_T2<U_RAW line0.5"] += l2[0] < lu[0]
        wins["MIX_T2<U_RAW line1.5"] += l2[1] < lu[1]
    print("\nleague wins (test):", dict(wins))
    h8 = (m2[0] < m1[0] and m2[1] < m1[1] and m2[0] < u[0] and m2[1] < u[1] and wins["MIX_T2<U_RAW line0.5"] >= 8)
    h9 = 1.5 <= k_fit <= 2.2
    print(f"H8 {'NOT FALSIFIED' if h8 else 'FALSIFIED'} | H9 {'NOT FALSIFIED' if h9 else 'FALSIFIED'} (k={k_fit})")


if __name__ == "__main__":
    main()
