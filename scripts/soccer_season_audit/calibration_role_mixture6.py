# -*- coding: utf-8 -*-
"""Fix #2, SIXTH measurement: SEASON-SCOPED production inputs. PRE-REGISTERED
2026-09-15 ~20:10Z, after run 5 and before this ran.

Run 5 (MIX_PROD): H11 FALSIFIED (6/10 leagues; pooled shots 0.5 0.6422 vs U_RAW
0.6414) and H12 FALSIFIED (+0.031 against box-score roles). The ESPN leagues and
MLS were fine (ratio 0.86-1.03). The big five blew up (1.15-1.67).

HYPOTHESIS: a side's rows MIX SEASONS. Fix #1 keeps prior-season rows for players
with no current row, and run 5 took the team's match count as the maximum `games`
over ALL the side's rows. A 38-game prior season against a player's 4-game
current minutes shrinks m, which inflates r = team_shots * share / m.

MIX_PROD2 changes exactly that. The match count is the maximum `games` among the
side's rows OF THE SAME SEASON as the row, m = minutes / (that * 90).
p_start is as run 5: ESPN counts, else Understat minutes per appearance, else the
prior. k = 1.8 and c = 2, as run 3. Nothing is fitted. Scored on dates >= 2026-08-26.

H13: MIX_PROD2 (a) beats U_RAW on pooled log loss at both lines for SHOTS and SOT,
     (b) beats U_RAW at shots line 0.5 in >= 8 of 10 leagues, and (c) is within
     0.005 of MIX_T2 at pooled shots line 0.5.
     FALSIFIED IF any of (a), (b), (c) fails. Then the conditional ladder needs an
     ESPN role artifact for all ten leagues before it can ship.
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
MS, MB = crm.MIN_START, crm.MIN_SUB


def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def main():
    recs, outc = crm.load_recs(), crm.load_outcomes()
    hist = crm.role_history(outc)
    tmp = Path(crm.S) / "calib_mix6_root"
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
    source_count = collections.Counter()
    season_mix = collections.Counter()
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
            season_max = collections.defaultdict(float)
            for r in base:
                src = by_id.get(str(r["player_id"]), {})
                g = num(src.get("games"))
                if g:
                    season_max[str(src.get("season"))] = max(season_max[str(src.get("season"))], g)
            season_mix["sides_mixed" if len(season_max) > 1 else "sides_single"] += 1
            rows_a, rows_t, rows_p = [], [], []
            for r in base:
                src = by_id.get(str(r["player_id"]), {})
                rows_a.append(dict(r))
                rt = dict(r)
                if "_team_share" in src:
                    rt["expected_minutes_share"] = src["_team_share"]
                rows_t.append(rt)
                rp = dict(r)
                minutes, games = num(src.get("minutes")), num(src.get("games"))
                smax = season_max.get(str(src.get("season")), 0.0)
                if games and minutes is not None and smax > 0:
                    rp["expected_minutes_share"] = round(min(1.0, minutes / (smax * 90.0)), 4)
                rows_p.append(rp)
            prof = {"A": build_usage_profiles(rows_a, side=side, team=club),
                    "T": build_usage_profiles(rows_t, side=side, team=club),
                    "P": build_usage_profiles(rows_p, side=side, team=club)}
            roster = [q for q in o["players"] if q["side"] == side]
            preds = [{"player_name": p.player_name, "side": side} for p in prof["A"]]
            for i, j in crm.strict_match(preds, roster).items():
                q = roster[j]
                pa, pt, pp = prof["A"][i], prof["T"][i], prof["P"][i]
                if not crm.appeared(q) or pa.is_goalkeeper or pa.position.upper().startswith("G"):
                    continue
                src = by_id.get(str(pa.player_id), {})
                rate = clamp(float(pa.on_target_rate) if pa.on_target_rate is not None else team_rate, 0.05, 0.80)
                s, b, _n = crm.prior_counts(hist, lg, club, q.get("name"), m["date"])
                mt = max(pt.expected_minutes_share, 1e-3)
                r_t = team_shots * pt.shot_share / mt
                ps_hist = (s + C * clamp(mt / (MS / 90.0), 0.05, 0.95)) / (s + b + C)
                mp = max(pp.expected_minutes_share, 1e-3)
                r_p = team_shots * pp.shot_share / mp
                prior_p = clamp(mp / (MS / 90.0), 0.05, 0.95)
                apps, starts = num(src.get("appearances")), num(src.get("starts"))
                games, minutes = num(src.get("games")), num(src.get("minutes"))
                if apps and starts is not None:
                    ps_prod = (starts + C * prior_p) / (apps + C)
                    source_count["espn_counts"] += 1
                elif games and minutes is not None:
                    ps_prod = clamp((minutes / games - MB) / (MS - MB), 0.02, 0.98)
                    source_count["understat_mpa"] += 1
                else:
                    ps_prod = prior_p
                    source_count["prior_only"] += 1
                mixes = {
                    "U_RAW": [(1.0, team_shots * pa.shot_share)],
                    "MIX_T2": [(ps_hist, r_t * MS / 90.0), (1.0 - ps_hist, K * r_t * MB / 90.0)],
                    "MIX_PROD2": [(ps_prod, r_p * MS / 90.0), (1.0 - ps_prod, K * r_p * MB / 90.0)],
                }
                rec = {"lg": lg, "shots": float(q.get("shots") or 0.0), "sot": float(q.get("sot") or 0.0)}
                for arm, mix in mixes.items():
                    rec[arm + "_mean"] = sum(w * u for w, u in mix)
                    for kk in (1, 2):
                        rec[f"{arm}_s{kk}"] = clamp(sum(w * crm.p_ge(u, kk) for w, u in mix), crm.EPS, 1 - crm.EPS)
                        rec[f"{arm}_t{kk}"] = clamp(sum(w * crm.p_ge(u * rate, kk) for w, u in mix), crm.EPS, 1 - crm.EPS)
                pts.append(rec)

    def ll(sel, arm, kind, kk):
        target = "shots" if kind == "s" else "sot"
        return crm.mean(-(math.log(x[f"{arm}_{kind}{kk}"]) if x[target] >= kk else math.log(1 - x[f"{arm}_{kind}{kk}"])) for x in sel)

    def ratio(sel, arm):
        return crm.mean(x[arm + "_mean"] for x in sel) / max(crm.mean(x["shots"] for x in sel), 1e-9)

    print(f"TEST (>= {CUT}) points {len(pts)} role source {dict(source_count)} sides {dict(season_mix)}")
    for arm in ("U_RAW", "MIX_T2", "MIX_PROD2"):
        print(f"  {arm:10s} SHOTS {ll(pts, arm, 's', 1):.4f}/{ll(pts, arm, 's', 2):.4f}  SOT {ll(pts, arm, 't', 1):.4f}/{ll(pts, arm, 't', 2):.4f}  ratio {ratio(pts, arm):.2f}")
    wins = 0
    for lg in crm.LEAGUES:
        sel = [x for x in pts if x["lg"] == lg]
        if not sel:
            continue
        u, h, p = ll(sel, "U_RAW", "s", 1), ll(sel, "MIX_T2", "s", 1), ll(sel, "MIX_PROD2", "s", 1)
        wins += p < u
        print(f"  {lg:20s} n={len(sel):5d} shots0.5 U_RAW {u:.4f} MIX_T2 {h:.4f} MIX_PROD2 {p:.4f} | ratio U_RAW {ratio(sel, 'U_RAW'):.2f} PROD2 {ratio(sel, 'MIX_PROD2'):.2f}")
    a = all(ll(pts, "MIX_PROD2", kind, kk) < ll(pts, "U_RAW", kind, kk) for kind in ("s", "t") for kk in (1, 2))
    gap = ll(pts, "MIX_PROD2", "s", 1) - ll(pts, "MIX_T2", "s", 1)
    print(f"(a) {a} | (b) wins {wins}/10 -> {wins >= 8} | (c) gap {gap:+.4f} -> {gap <= 0.005}")
    print("H13", "NOT FALSIFIED" if (a and wins >= 8 and gap <= 0.005) else "FALSIFIED")


if __name__ == "__main__":
    main()
