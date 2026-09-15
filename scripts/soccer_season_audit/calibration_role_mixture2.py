# -*- coding: utf-8 -*-
"""Fix #2, SECOND measurement. PRE-REGISTERED 2026-09-15 ~19:55Z, after the first
run (role_mixture_out.txt) and before this one ran.

First-run verdicts: H1 SUPPORTED (10/10 leagues), H2 SUPPORTED for big-five starters,
H3 FALSIFIED as registered (pooled and both halves pass, but 5/10 leagues against the
>=7 required), H4 ceiling 0.020 / 0.013 log loss.

H5 (H2 on the ladder the board prices): U_T, i.e. team-minutes shares, no divisor,
    unconditional, beats U_RAW on log loss at both lines in the BIG FIVE (the only
    leagues where T differs) and pooled.
    FALSIFIED IF big-five log loss at either line is not lower.
H6 (why H3 missed: roles under-separated): among appeared outfield players, the mean
    predicted P(start | appear) is < 0.80 for actual starters OR > 0.40 for actual
    substitutes.
    FALSIFIED IF starters >= 0.80 AND substitutes <= 0.40. The miss would then be in
    minutes or intensity, not role.
H7 (substitute intensity): over actual substitutes, sum(actual shots) / sum(r * 15.6/90)
    > 1.5 pooled, i.e. subs shoot more per minute than the on-pitch rate says.
    FALSIFIED IF <= 1.5.
Reported for the decision, not hypotheses: MIX_T vs U_T per league, and p_start
calibration by decile.
"""
import collections
import contextlib
import importlib.util
import io
import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("crm", HERE / "calibration_role_mixture.py")
crm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crm)

import pandas as pd  # noqa: E402

from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles  # noqa: E402

ARMS = ("U_RAW", "U_T", "MIX_T", "ORACLE_T")


def main():
    recs, outc = crm.load_recs(), crm.load_outcomes()
    hist = crm.role_history(outc)
    tmp = Path(crm.S) / "calib_mix2_root"
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
                eu_a, eu_t = team_shots * pa.shot_share, team_shots * pt.shot_share
                mt = max(pt.expected_minutes_share, 1e-3)
                r_t = eu_t / mt
                prior = min(0.95, max(0.05, mt / (crm.MIN_START / 90.0)))
                p_start = (s + 2.0 * prior) / (s + b + 2.0)
                ladders = {
                    "U_RAW": [(1.0, eu_a)],
                    "U_T": [(1.0, eu_t)],
                    "MIX_T": [(p_start, r_t * crm.MIN_START / 90.0), (1.0 - p_start, r_t * crm.MIN_SUB / 90.0)],
                    "ORACLE_T": [(1.0, r_t * (crm.MIN_START if q["starter"] else crm.MIN_SUB) / 90.0)],
                }
                rec = {"lg": lg, "big5": lg in crm.BIG_FIVE, "starter": bool(q["starter"]), "p_start": p_start,
                       "has_hist": bool(s + b), "actual": float(q.get("shots") or 0.0),
                       "sub_pred": r_t * crm.MIN_SUB / 90.0}
                for arm, mix in ladders.items():
                    rec[arm + "_mean"] = sum(w * u for w, u in mix)
                    for k in (1, 2):
                        rec[f"{arm}_p{k}"] = min(1 - crm.EPS, max(crm.EPS, sum(w * crm.p_ge(u, k) for w, u in mix)))
                pts.append(rec)
    print("points:", len(pts))

    def ll(sel, arm, k):
        return crm.mean(-(math.log(x[f"{arm}_p{k}"]) if x["actual"] >= k else math.log(1 - x[f"{arm}_p{k}"])) for x in sel)

    def ratio(sel, arm):
        return crm.mean(x[arm + "_mean"] for x in sel) / max(crm.mean(x["actual"] for x in sel), 1e-9)

    print("\n=== H5: U_T vs U_RAW (unconditional ladder)")
    for title, sel in (("pooled", pts), ("big five", [x for x in pts if x["big5"]]), ("other five", [x for x in pts if not x["big5"]])):
        print(f"  {title:10s} n={len(sel):5d} U_RAW LL1 {ll(sel, 'U_RAW', 1):.4f} LL2 {ll(sel, 'U_RAW', 2):.4f} ratio {ratio(sel, 'U_RAW'):.2f}"
              f" | U_T LL1 {ll(sel, 'U_T', 1):.4f} LL2 {ll(sel, 'U_T', 2):.4f} ratio {ratio(sel, 'U_T'):.2f}")

    print("\n=== H6: mean predicted P(start | appear) by actual role")
    for title, sel in (("all", pts), ("with history", [x for x in pts if x["has_hist"]]), ("prior only", [x for x in pts if not x["has_hist"]])):
        st = [x["p_start"] for x in sel if x["starter"]]
        sb = [x["p_start"] for x in sel if not x["starter"]]
        print(f"  {title:13s} starters n={len(st):5d} mean p_start {crm.mean(st) if st else float('nan'):.3f}"
              f" | subs n={len(sb):5d} mean p_start {crm.mean(sb) if sb else float('nan'):.3f}")
    print("  calibration by p_start decile (with history): predicted -> actual start rate")
    sel = sorted((x for x in pts if x["has_hist"]), key=lambda x: x["p_start"])
    for d in range(10):
        chunk = sel[d * len(sel) // 10:(d + 1) * len(sel) // 10]
        if chunk:
            print(f"    d{d} n={len(chunk):5d} pred {crm.mean(x['p_start'] for x in chunk):.3f} actual {crm.mean(1.0 if x['starter'] else 0.0 for x in chunk):.3f}")

    print("\n=== H7: substitute intensity = sum(actual) / sum(r * 15.6/90)")
    subs = [x for x in pts if not x["starter"]]
    starters = [x for x in pts if x["starter"]]
    print(f"  subs pooled n={len(subs)} intensity {sum(x['actual'] for x in subs) / max(sum(x['sub_pred'] for x in subs), 1e-9):.2f}")
    for grp, flt in (("big five", lambda x: x["big5"]), ("other five", lambda x: not x["big5"])):
        sel = [x for x in subs if flt(x)]
        print(f"  subs {grp:10s} n={len(sel)} intensity {sum(x['actual'] for x in sel) / max(sum(x['sub_pred'] for x in sel), 1e-9):.2f}")
    print(f"  starters pooled n={len(starters)} ORACLE ratio {ratio(starters, 'ORACLE_T'):.2f}")

    print("\n=== decision table by league: LL1/LL2  U_T vs MIX_T")
    wins = collections.Counter()
    for lg in crm.LEAGUES:
        sel = [x for x in pts if x["lg"] == lg]
        if not sel:
            continue
        u1, u2, m1, m2 = ll(sel, "U_T", 1), ll(sel, "U_T", 2), ll(sel, "MIX_T", 1), ll(sel, "MIX_T", 2)
        wins["MIX_T<U_T line0.5"] += m1 < u1
        wins["MIX_T<U_T line1.5"] += m2 < u2
        print(f"  {lg:20s} n={len(sel):5d} U_T {u1:.4f}/{u2:.4f}  MIX_T {m1:.4f}/{m2:.4f}")
    print("wins:", dict(wins))


if __name__ == "__main__":
    main()
