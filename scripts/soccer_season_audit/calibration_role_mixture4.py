# -*- coding: utf-8 -*-
"""Fix #2, FOURTH measurement: SHOTS ON TARGET. PRE-REGISTERED 2026-09-15 ~20:00Z,
before this ran. The board prices `player_shots_on_target` from the same allocation,
so H8 (shots only) does not license switching SOT.

SOT mean = shots mean * on-target rate. The rate is the profile's own
`on_target_rate` when present, else the team's SOT/shots, clamped to [0.05, 0.80]
(exactly `project_player_props`). Mixture parameters are run 3's, fitted on SHOTS
over dates < 2026-08-26: k = 1.8, c = 2. Nothing is fitted here.

H10: on dates >= 2026-08-26, MIX_T2's SOT ladder beats U_RAW's SOT ladder (no
     divisor, unconditional) on pooled log loss at P(SOT >= 1) AND P(SOT >= 2), and
     at P(SOT >= 1) in >= 8 of 10 leagues.
     FALSIFIED IF either pooled comparison is not lower, or fewer than 8 leagues.
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
K, C = 1.8, 2.0


def main():
    recs, outc = crm.load_recs(), crm.load_outcomes()
    hist = crm.role_history(outc)
    tmp = Path(crm.S) / "calib_mix4_root"
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
        if not o or m["shots_h"] is None or str(m["date"]) < CUT:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            feats = build_soccer_player_features(rows_by_league[lg], league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
        by_id = {str(r.get("player_id")): r for r in rows_by_league[lg]}
        for side, club, team_shots, team_sot in (("home", m["home"], m["shots_h"], m["sot_h"]), ("away", m["away"], m["shots_a"], m["sot_a"])):
            base = [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, "team": f.team,
                     **dict(f.usage_metrics or {})} for f in feats if f.team == club]
            if not base or not team_shots:
                continue
            team_rate = (team_sot / team_shots) if team_sot else 0.33
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
                rate = pa.on_target_rate if pa.on_target_rate is not None else team_rate
                rate = min(0.80, max(0.05, float(rate)))
                s, b, _n = crm.prior_counts(hist, lg, club, q.get("name"), m["date"])
                mt = max(pt.expected_minutes_share, 1e-3)
                r_t = team_shots * pt.shot_share / mt
                prior = min(0.95, max(0.05, mt / (crm.MIN_START / 90.0)))
                p_start = (s + C * prior) / (s + b + C)
                ladders = {
                    "U_RAW": [(1.0, team_shots * pa.shot_share * rate)],
                    "MIX_T2": [(p_start, r_t * crm.MIN_START / 90.0 * rate), (1.0 - p_start, K * r_t * crm.MIN_SUB / 90.0 * rate)],
                }
                rec = {"lg": lg, "actual": float(q.get("sot") or 0.0)}
                for arm, mix in ladders.items():
                    rec[arm + "_mean"] = sum(w * u for w, u in mix)
                    for kk in (1, 2):
                        rec[f"{arm}_p{kk}"] = min(1 - crm.EPS, max(crm.EPS, sum(w * crm.p_ge(u, kk) for w, u in mix)))
                pts.append(rec)

    def ll(sel, arm, kk):
        return crm.mean(-(math.log(x[f"{arm}_p{kk}"]) if x["actual"] >= kk else math.log(1 - x[f"{arm}_p{kk}"])) for x in sel)

    def ratio(sel, arm):
        return crm.mean(x[arm + "_mean"] for x in sel) / max(crm.mean(x["actual"] for x in sel), 1e-9)

    print(f"TEST (>= {CUT}) SOT points: {len(pts)}  P(SOT>=1)={crm.mean(1.0 if x['actual'] >= 1 else 0.0 for x in pts):.3f}")
    u1, u2, m1, m2 = ll(pts, "U_RAW", 1), ll(pts, "U_RAW", 2), ll(pts, "MIX_T2", 1), ll(pts, "MIX_T2", 2)
    print(f"  pooled U_RAW {u1:.4f}/{u2:.4f} ratio {ratio(pts, 'U_RAW'):.2f} | MIX_T2 {m1:.4f}/{m2:.4f} ratio {ratio(pts, 'MIX_T2'):.2f}")
    wins = collections.Counter()
    for lg in crm.LEAGUES:
        sel = [x for x in pts if x["lg"] == lg]
        if not sel:
            continue
        a1, a2, b1, b2 = ll(sel, "U_RAW", 1), ll(sel, "U_RAW", 2), ll(sel, "MIX_T2", 1), ll(sel, "MIX_T2", 2)
        wins["line0.5"] += b1 < a1
        wins["line1.5"] += b2 < a2
        print(f"  {lg:20s} n={len(sel):5d} U_RAW {a1:.4f}/{a2:.4f}  MIX_T2 {b1:.4f}/{b2:.4f}  ratio {ratio(sel, 'U_RAW'):.2f} -> {ratio(sel, 'MIX_T2'):.2f}")
    h10 = m1 < u1 and m2 < u2 and wins["line0.5"] >= 8
    print("league wins:", dict(wins), "| H10", "NOT FALSIFIED" if h10 else "FALSIFIED")


if __name__ == "__main__":
    main()
