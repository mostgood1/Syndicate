# -*- coding: utf-8 -*-
"""Fix #2, measurement BEFORE code. PRE-REGISTERED 2026-09-15 ~19:50Z, before this ran.

The bet population is APPEARED players: books void a shot prop on a DNP. The board
prices `shots_over_probabilities`, a Poisson ladder over the UNCONDITIONAL mean
(DNP mass included) divided by the live divisor 1.393. Scored as P(shots >= 1) and
P(shots >= 2), i.e. lines 0.5 and 1.5, by log loss and Brier on appeared outfield
players. Squads are fix #1's.

H1 (retire the divisor): U_RAW beats BOARD on log loss at both lines, pooled.
    FALSIFIED IF pooled log loss at either line is not lower.
H2 (share semantics): with Understat shares recomputed as share of TEAM minutes
    (T), big-five appeared STARTERS' mean ratio moves toward 1.0 against A.
    FALSIFIED IF big-five starters' |ratio - 1| does not shrink.
H3 (conditioning on appearing): MIX_T, a start/sub mixture conditional on appearing,
    beats the better of U_RAW and IFP_T on log loss at BOTH lines, pooled, on BOTH
    date halves, and in >= 7 of 10 leagues at line 0.5.
    FALSIFIED IF any pooled/half comparison is not lower, or fewer than 7 leagues.
H4 (confirmed-lineup ceiling, descriptive): ORACLE_T minus MIX_T log loss is the
    most a confirmed lineup could add. If it is <= 0, the lineup path is not worth building.

Mixture: P(start | appear) = (s + 2*prior) / (s + b + 2), where s and b are the player's
starts and sub appearances in his club's matches STRICTLY BEFORE this match's date
(ESPN box scores in outcomes.json), and prior = clamp(m / (83/90), 0.05, 0.95).
On-pitch rate r = team_shots * shot_share / m, with m the profile's minutes share.
mu_start = r * 83.1/90, mu_sub = r * 15.6/90: least-squares minutes per start and
per sub appearance over 1,240 ESPN-league outfield players, 2026 files.
These constants use the same season, so they are a MILD in-sample choice; the
role counts are strictly prior.

Arms (all on fix #1 squads):
  BOARD      A shares, divisor 1.393, unconditional ladder (today's board)
  U_RAW      A shares, no divisor, unconditional ladder
  IFP_A_DIV  A shares, divisor, mean / max(m, 0.25) (today's *_if_playing)
  IFP_T      T shares, no divisor, mean / max(m, 0.25)
  MIX_A      A shares, no divisor, role mixture
  MIX_T      T shares, no divisor, role mixture
  ORACLE_T   T shares, no divisor, the player's ACTUAL role (start vs sub)
"""
import collections
import contextlib
import glob
import importlib.util
import io
import math
import os
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

WT = Path(os.environ.get("SYNDICATE_CHECKOUT") or Path(__file__).resolve().parents[2])  # the checkout this file lives in
sys.path.insert(0, str(WT))
sys.path.append(str(WT / "scripts" / "soccer_season_audit"))
spec = importlib.util.spec_from_file_location("bsa_mix", WT / "scripts" / "build_soccer_artifacts.py")
bsa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsa)
from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles  # noqa: E402

from common import LEAGUES, S, fold, load_outcomes, load_recs, mean  # noqa: E402
from decompose_squads import appeared  # noqa: E402
from namejoin_diag import strict_match  # noqa: E402
import replay_squads as rs  # noqa: E402

BIG_FIVE = {"epl", "la_liga", "bundesliga", "serie_a", "ligue_1"}
DIVISOR = 1.3930
MIN_START, MIN_SUB = 83.1, 15.6
EPS = 1e-6
ARMS = ("BOARD", "U_RAW", "IFP_A_DIV", "IFP_T", "MIX_A", "MIX_T", "ORACLE_T")


def p_ge(mu, k):
    mu = max(mu, 0.0)
    if k == 1:
        return 1.0 - math.exp(-mu)
    return 1.0 - math.exp(-mu) * (1.0 + mu)


def club_max_games():
    out = {}
    for f in glob.glob(os.path.join(S, "prod", "players", "soccer_source_*_players_players_*.csv")):
        m = re.search(r"soccer_source_(.+)_players_players_(\d{4})\.csv$", os.path.basename(f))
        if not m or m.group(1) not in BIG_FIVE:
            continue
        frame = pd.read_csv(f)
        for team, games in zip(frame["team"].astype(str), pd.to_numeric(frame["games"], errors="coerce").fillna(0)):
            key = (m.group(1), int(m.group(2)), team)
            out[key] = max(out.get(key, 0.0), float(games))
    return out


def role_history(outc):
    """(league, fold(club)) -> sorted [(date, {fold(player): 'S' | 'B'})]."""
    hist = collections.defaultdict(list)
    for (lg, _mid), o in outc.items():
        for side in ("home", "away"):
            club = o.get(side)
            roles = {}
            for q in o.get("players") or []:
                if q.get("side") != side or not appeared(q):
                    continue
                roles[fold(q.get("name") or "")] = "S" if q.get("starter") else "B"
            hist[(lg, fold(club or ""))].append((str(o.get("date")), roles))
    for key in hist:
        hist[key].sort(key=lambda x: x[0])
    return hist


def prior_counts(hist, lg, club, player, date):
    s = b = n = 0
    for d, roles in hist.get((lg, fold(club or "")), []):
        if d >= date:
            break
        n += 1
        r = roles.get(fold(player or ""))
        if r == "S":
            s += 1
        elif r == "B":
            b += 1
    return s, b, n


def main():
    recs, outc = load_recs(), load_outcomes()
    hist = role_history(outc)
    tmp = Path(S) / "calib_mix_root"
    shutil.rmtree(tmp, ignore_errors=True)
    root = rs.build_root(tmp)
    bsa.roster_rows = rs.seed_roster_rows
    maxg = club_max_games()
    rows_by_league = {}
    for league in LEAGUES:
        with contextlib.redirect_stdout(io.StringIO()):
            rows = bsa._load_player_rows(league, root)
        if league in BIG_FIVE:
            for row in rows:
                season = str(row.get("season") or "").strip()
                season = int(float(season)) if season not in ("", "nan") else None
                minutes = pd.to_numeric(pd.Series([row.get("minutes")]), errors="coerce").iloc[0]
                club_games = maxg.get((league, season, str(row.get("team")))) if season else None
                if club_games and minutes == minutes and club_games > 0:
                    row["_team_share"] = round(min(1.0, float(minutes) / (club_games * 90.0)), 4)
        rows_by_league[league] = rows

    latest = {}
    for (lg, mid), m in recs.items():
        if (lg, mid) in outc:
            for club in (m["home"], m["away"]):
                latest[(lg, club)] = max(latest.get((lg, club), ""), m["date"])

    pts = []
    fallback = collections.Counter()
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
            for i, j in strict_match(preds, roster).items():
                q = roster[j]
                pa, pt = prof["A"][i], prof["T"][i]
                if not appeared(q) or pa.is_goalkeeper or pa.position.upper().startswith("G"):
                    continue
                s, b, n = prior_counts(hist, lg, club, q.get("name"), m["date"])
                fallback["history" if (s + b) else "prior_only"] += 1
                mu = {}
                eu_a = team_shots * pa.shot_share
                eu_t = team_shots * pt.shot_share
                ma, mt = max(pa.expected_minutes_share, 1e-3), max(pt.expected_minutes_share, 1e-3)
                ladders = {}
                ladders["BOARD"] = [(1.0, eu_a / DIVISOR)]
                ladders["U_RAW"] = [(1.0, eu_a)]
                ladders["IFP_A_DIV"] = [(1.0, eu_a / DIVISOR / max(ma, 0.25))]
                ladders["IFP_T"] = [(1.0, eu_t / max(mt, 0.25))]
                for arm, eu, mm in (("MIX_A", eu_a, ma), ("MIX_T", eu_t, mt)):
                    r = eu / mm
                    prior = min(0.95, max(0.05, mm / (MIN_START / 90.0)))
                    p_start = (s + 2.0 * prior) / (s + b + 2.0)
                    ladders[arm] = [(p_start, r * MIN_START / 90.0), (1.0 - p_start, r * MIN_SUB / 90.0)]
                r_t = eu_t / mt
                ladders["ORACLE_T"] = [(1.0, r_t * (MIN_START if q["starter"] else MIN_SUB) / 90.0)]
                actual = float(q.get("shots") or 0.0)
                rec = {"lg": lg, "date": m["date"], "latest": m["date"] == latest.get((lg, club)),
                       "starter": bool(q["starter"]), "big5": lg in BIG_FIVE, "actual": actual}
                for arm, mix in ladders.items():
                    rec[arm + "_mean"] = sum(w * u for w, u in mix)
                    for k in (1, 2):
                        rec[f"{arm}_p{k}"] = min(1 - EPS, max(EPS, sum(w * p_ge(u, k) for w, u in mix)))
                pts.append(rec)
    print("role history:", dict(fallback), "points:", len(pts))
    dates = sorted({x["date"] for x in pts})
    cut = dates[len(dates) // 2]
    print("date range", dates[0], "..", dates[-1], "| half split at", cut)

    def ll(sel, arm, k):
        return mean(-(math.log(x[f"{arm}_p{k}"]) if x["actual"] >= k else math.log(1 - x[f"{arm}_p{k}"])) for x in sel)

    def brier(sel, arm, k):
        return mean((x[f"{arm}_p{k}"] - (1.0 if x["actual"] >= k else 0.0)) ** 2 for x in sel)

    def ratio(sel, arm):
        return mean(x[arm + "_mean"] for x in sel) / max(mean(x["actual"] for x in sel), 1e-9)

    def table(title, sel):
        if not sel:
            print(f"\n=== {title}: n=0")
            return
        base1 = mean(1.0 if x["actual"] >= 1 else 0.0 for x in sel)
        base2 = mean(1.0 if x["actual"] >= 2 else 0.0 for x in sel)
        c1 = -(base1 * math.log(base1) + (1 - base1) * math.log(1 - base1))
        c2 = -(base2 * math.log(base2) + (1 - base2) * math.log(1 - base2))
        print(f"\n=== {title}: n={len(sel)}  P(>=1)={base1:.3f} P(>=2)={base2:.3f}  constant LL1 {c1:.4f} LL2 {c2:.4f}")
        for arm in ARMS:
            st = [x for x in sel if x["starter"]]
            sb = [x for x in sel if not x["starter"]]
            print(f"  {arm:10s} LL1 {ll(sel, arm, 1):.4f} LL2 {ll(sel, arm, 2):.4f} | B1 {brier(sel, arm, 1):.4f} B2 {brier(sel, arm, 2):.4f}"
                  f" | ratio all {ratio(sel, arm):.2f} start {ratio(st, arm) if st else float('nan'):.2f} sub {ratio(sb, arm) if sb else float('nan'):.2f}")

    for scope, flt in (("ALL", lambda x: True), ("LATEST", lambda x: x["latest"])):
        sel = [x for x in pts if flt(x)]
        table(f"{scope} pooled", sel)
        table(f"{scope} first half (< {cut})", [x for x in sel if x["date"] < cut])
        table(f"{scope} second half (>= {cut})", [x for x in sel if x["date"] >= cut])
        table(f"{scope} big five", [x for x in sel if x["big5"]])
        table(f"{scope} other five", [x for x in sel if not x["big5"]])

    print("\n=== ALL by league: LL1 / LL2 per arm")
    wins = collections.Counter()
    for lg in LEAGUES:
        sel = [x for x in pts if x["lg"] == lg]
        if not sel:
            continue
        cells = " ".join(f"{arm}:{ll(sel, arm, 1):.3f}/{ll(sel, arm, 2):.3f}" for arm in ARMS)
        best_other = min(ll(sel, "U_RAW", 1), ll(sel, "IFP_T", 1))
        if ll(sel, "MIX_T", 1) < best_other:
            wins["MIX_T_line0.5"] += 1
        if ll(sel, "U_RAW", 1) < ll(sel, "BOARD", 1):
            wins["U_RAW_beats_BOARD_line0.5"] += 1
        print(f"  {lg:20s} n={len(sel):5d} {cells}")
    print("league wins:", dict(wins))


if __name__ == "__main__":
    main()
