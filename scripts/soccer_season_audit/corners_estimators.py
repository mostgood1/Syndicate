# -*- coding: utf-8 -*-
"""Stage 1 of lane `soccer-corners-model-rebuild` (#664 item 6): which corners ESTIMATOR carries information?

H26: the engine's corners are uninformative (r = 0.02 against actual totals, season to date)
because the per-possession corner chance ignores each team's measured corner rates.
Falsified if, on held-out current-season matches, the team-rate estimator fails to beat
last season's league mean on total-corners MAE, or its r(total) is below 0.20.

Estimators, each predicting (home corners, away corners) from data dated BEFORE the match:
  E0  production engine: `volume_projection` from the recommendations artifacts
  E1  last season's league mean (the audit's baseline)
  E1r rolling league mean, 365 days
  E2  team rates: league venue means x shrunk corners-for x opponent corners-against,
      exponentially weighted by age; (k, half-life) chosen on the 2025 season only
  E3  E2 + a pregame pressure adjustment from closing odds (favourite strength, O/U 2.5),
      coefficients fitted on the 2025 season only

Training data: `data/soccer_source/<league>/history/matches_{2023,2024,2025}.csv`
(football-data; nine European leagues, none for MLS). Held out: the current season's ESPN
box scores (`outcomes.json`), which are also the current-season rate history for later
matches. Nothing from the held-out season chooses a parameter.

    SOCCER_AUDIT_CACHE=<cache> py -3 scripts/soccer_season_audit/corners_estimators.py --history-root <checkout-with-data>/data/soccer_source
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import io
import json
import math
import os
import sys

import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from syndicate.features.soccer.features.team_names import canonical_team_name, match_team_name  # noqa: E402

CACHE = os.environ.get("SOCCER_AUDIT_CACHE") or os.path.dirname(os.path.abspath(__file__))
LEAGUES = ["epl", "championship", "la_liga", "bundesliga", "serie_a", "ligue_1",
           "eredivisie", "primeira_liga", "belgian_pro_league", "mls"]
TRAIN_SEASON_START = pd.Timestamp("2025-07-01")
HELD_OUT_START = pd.Timestamp("2026-07-01")
K_GRID = (2.0, 5.0, 10.0, 20.0)
H_GRID = (None, 365.0, 180.0)


def _utc_naive(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_convert("UTC").tz_localize(None) if stamp.tzinfo is not None else stamp


def devig(prices):
    inv = [1.0 / float(p) for p in prices if p is not None and not (isinstance(p, float) and math.isnan(p)) and float(p) > 1.0]
    if len(inv) != len(prices):
        return None
    total = sum(inv)
    return [x / total for x in inv]


# ---------------------------------------------------------------------------- data

def load_history(root):
    rows = []
    for lg in LEAGUES:
        for season in (2023, 2024, 2025):
            path = os.path.join(root, lg, "history", f"matches_{season}.csv")
            if not os.path.exists(path):
                continue
            f = pd.read_csv(path).dropna(subset=["home_corners", "away_corners"])
            for r in f.itertuples():
                one = devig([getattr(r, "odds_home", None), getattr(r, "odds_draw", None), getattr(r, "odds_away", None)])
                ou = devig([getattr(r, "odds_over_2_5", None), getattr(r, "odds_under_2_5", None)])
                rows.append({
                    "lg": lg, "date": pd.to_datetime(r.date, dayfirst=True), "src": "history",
                    "home": canonical_team_name(r.home_team), "away": canonical_team_name(r.away_team),
                    "hc": float(r.home_corners), "ac": float(r.away_corners),
                    "p_home": one[0] if one else None, "p_away": one[2] if one else None, "p_over": ou[0] if ou else None,
                })
    return pd.DataFrame(rows)


def history_name_mapper(hist):
    """ESPN name -> the league's history (football-data) name, by the rule production's
    loaders use (`match_team_name`, threshold 0.72). Unmatched names keep their canonical
    form, which only ever joins to current-season ESPN rows."""
    names = {lg: sorted(set(g.home) | set(g.away)) for lg, g in hist.groupby("lg")}
    cache = {}

    def mapped(lg, name):
        key = (lg, name)
        if key not in cache:
            hit = match_team_name(name, names.get(lg, [])) if names.get(lg) else None
            cache[key] = canonical_team_name(hit) if hit else canonical_team_name(name)
        return cache[key]

    return mapped


def load_current(cache, mapped=None):
    outcomes = json.load(io.open(os.path.join(cache, "outcomes.json"), encoding="utf-8"))
    fd = {}
    for lg in LEAGUES:
        path = os.path.join(cache, "fd", f"{lg}.csv")
        if os.path.exists(path):
            f = pd.read_csv(path, encoding="utf-8-sig")
            # The "new leagues" format (MLS) names teams Home/Away. CLOSING odds
            # (AvgC*) are used wherever published, as in the audit; European files
            # carry both opening (AvgH) and closing (AvgCH) columns.
            f = f.rename(columns={"Home": "HomeTeam", "Away": "AwayTeam"})
            out = pd.DataFrame({"Date": f["Date"], "HomeTeam": f["HomeTeam"], "AwayTeam": f["AwayTeam"]})
            for dst, closing, opening in (("OddsH", "AvgCH", "AvgH"), ("OddsD", "AvgCD", "AvgD"), ("OddsA", "AvgCA", "AvgA"),
                                          ("OddsOver", "AvgC>2.5", "Avg>2.5"), ("OddsUnder", "AvgC<2.5", "Avg<2.5")):
                src = closing if closing in f.columns else (opening if opening in f.columns else None)
                out[dst] = pd.to_numeric(f[src], errors="coerce") if src else np.nan
            fd[lg] = out
    rows = []
    for o in outcomes.values():
        th, ta = (o.get("teams") or {}).get("home") or {}, (o.get("teams") or {}).get("away") or {}
        hc, ac = th.get("wonCorners"), ta.get("wonCorners")
        if hc is None or ac is None or not o.get("completed"):
            continue
        date = _utc_naive(o["kickoff"])
        name = mapped or (lambda lg, n: canonical_team_name(n))
        row = {"lg": o["league"], "date": date, "src": "espn", "match_id": str(o["match_id"]),
               "home": name(o["league"], o["home"]), "away": name(o["league"], o["away"]),
               "hc": float(hc), "ac": float(ac), "p_home": None, "p_away": None, "p_over": None}
        f = fd.get(o["league"])
        if f is not None and len(f):
            day = f[pd.to_datetime(f["Date"], dayfirst=True).dt.date == date.date()]
            if len(day):
                hn = match_team_name(o["home"], list(day["HomeTeam"]))
                an = match_team_name(o["away"], list(day["AwayTeam"]))
                hit = day[(day["HomeTeam"] == hn) & (day["AwayTeam"] == an)] if hn and an else day.iloc[0:0]
                if len(hit):
                    g = hit.iloc[0]
                    one = devig([g["OddsH"], g["OddsD"], g["OddsA"]])
                    ou = devig([g["OddsOver"], g["OddsUnder"]])
                    if one:
                        row["p_home"], row["p_away"] = one[0], one[2]
                    if ou:
                        row["p_over"] = ou[0]
        rows.append(row)
    return pd.DataFrame(rows)


def load_engine(cache):
    """E0: the production engine's corners, latest generation per match."""
    best = {}
    for path in glob.glob(os.path.join(cache, "prod", "recs", "*.json")):
        if os.path.basename(path).startswith("_"):
            continue
        try:
            j = json.load(io.open(path, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        gen = str(j.get("generated_at") or "")
        for m in j.get("matches") or []:
            vp = m.get("volume_projection") or {}
            if vp.get("home_corners") is None:
                continue
            key = (j.get("league"), str(m.get("match_id")))
            if key not in best or gen > best[key][0]:
                best[key] = (gen, float(vp["home_corners"]), float(vp["away_corners"]))
    return {k: v[1:] for k, v in best.items()}


# ---------------------------------------------------------------------------- estimators

def league_means(train, weights):
    w = weights.sum()
    return (float((weights * train["hc"]).sum() / w), float((weights * train["ac"]).sum() / w)) if w > 0 else (None, None)


def team_rates(train, weights, mu_h, mu_a, k):
    """Venue-normalised corners-for and corners-against, shrunk toward 1.0 with prior weight k."""
    num_for, num_against, den = collections.defaultdict(float), collections.defaultdict(float), collections.defaultdict(float)
    for (home, away, hc, ac), w in zip(train[["home", "away", "hc", "ac"]].itertuples(index=False, name=None), weights):
        num_for[home] += w * hc / mu_h
        num_against[home] += w * ac / mu_a
        den[home] += w
        num_for[away] += w * ac / mu_a
        num_against[away] += w * hc / mu_h
        den[away] += w
    cf = {t: (num_for[t] + k) / (den[t] + k) for t in den}
    ca = {t: (num_against[t] + k) / (den[t] + k) for t in den}
    return cf, ca


def predict_e2(history_lg, target, k, h):
    """history_lg: every match in the league (any date). target: rows to predict."""
    out = []
    dates = history_lg["date"].values
    for r in target.itertuples():
        mask = dates < np.datetime64(r.date)
        train = history_lg[mask]
        if len(train) < 30:
            out.append((None, None))
            continue
        age = (np.datetime64(r.date) - train["date"].values).astype("timedelta64[D]").astype(float)
        weights = np.ones(len(train)) if h is None else np.power(0.5, age / h)
        mu_h, mu_a = league_means(train, weights)
        cf, ca = team_rates(train, weights, mu_h, mu_a, k)
        out.append((mu_h * cf.get(r.home, 1.0) * ca.get(r.away, 1.0), mu_a * cf.get(r.away, 1.0) * ca.get(r.home, 1.0)))
    return out


def rolling_mean(history_lg, target, days=365.0):
    out = []
    dates = history_lg["date"].values
    for r in target.itertuples():
        start = np.datetime64(r.date) - np.timedelta64(int(days), "D")
        train = history_lg[(dates < np.datetime64(r.date)) & (dates >= start)]
        out.append((float(train["hc"].mean()), float(train["ac"].mean())) if len(train) >= 30 else (None, None))
    return out


def pressure_features(r):
    if r["p_home"] is None or r["p_away"] is None or (isinstance(r["p_home"], float) and math.isnan(r["p_home"])):
        return None
    fav = abs(r["p_home"] - r["p_away"])
    over = r["p_over"] if r["p_over"] is not None and not (isinstance(r["p_over"], float) and math.isnan(r["p_over"])) else None
    return fav, over, r["p_home"] - r["p_away"]


# ---------------------------------------------------------------------------- scoring

def score(df, col_h, col_a, label):
    d = df.dropna(subset=[col_h, col_a])
    if len(d) < 10:
        return None
    pred, act = d[col_h] + d[col_a], d["hc"] + d["ac"]
    team_pred = pd.concat([d[col_h], d[col_a]])
    team_act = pd.concat([d["hc"], d["ac"]])
    res = {"label": label, "n": len(d), "mae": float((act - pred).abs().mean()), "r": float(np.corrcoef(pred, act)[0, 1]) if pred.std() > 0 else float("nan"),
           "bias": float((act - pred).mean()), "team_mae": float((team_act - team_pred).abs().mean()),
           "team_r": float(np.corrcoef(team_pred, team_act)[0, 1]) if team_pred.std() > 0 else float("nan"),
           "by_league": {}}
    for lg, g in d.groupby("lg"):
        res["by_league"][lg] = {"n": len(g), "bias": float(((g["hc"] + g["ac"]) - (g[col_h] + g[col_a])).mean()),
                                "mae": float(((g["hc"] + g["ac"]) - (g[col_h] + g[col_a])).abs().mean())}
    return res


def show(res):
    if res is None:
        return
    print(f"  {res['label']:34s} n={res['n']:4d}  MAE {res['mae']:.3f}  r {res['r']:+.3f}  bias {res['bias']:+.2f}  | team MAE {res['team_mae']:.3f} r {res['team_r']:+.3f}")


# ---------------------------------------------------------------------------- the ceiling

def market_benchmark(frame, hist):
    """How much can a pregame number know? The corners MARKET's main line, read the audit's way.

    A DIAGNOSTIC, chosen after the estimators were scored and changing nothing about them:
    if the market's own implied total reaches the same r, the estimators are near what
    pregame information allows and the r >= 0.20 bar was set above the ceiling.
    Main line and fair probability from `audit_games.corners_market` (last pre-kickoff
    capture, two-sided half lines); implied mean by inverting `nb_sf` with last season's
    league dispersion (pooled where absent).
    """
    from audit_games import corners_market, load_game_markets  # noqa: E402 -- reads SOCCER_AUDIT_CACHE
    from common import nb_sf  # noqa: E402

    disp = {}
    for lg, g in hist[hist.date >= TRAIN_SEASON_START].groupby("lg"):
        tot = g.hc + g.ac
        disp[lg] = max(1.0, float(tot.var() / tot.mean()))
    pooled = float(np.mean(list(disp.values()))) if disp else 1.0
    events = load_game_markets()
    by_league_day = collections.defaultdict(list)
    for e in events.values():
        by_league_day[(e["league"], e["game_time"].date())].append(e)

    def implied_mean(line, fair_over, d):
        k, lo, hi = int(math.floor(line)) + 1, 1.0, 25.0
        for _ in range(50):
            mid = (lo + hi) / 2.0
            if nb_sf(k, mid, d) < fair_over:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    rows = []
    for r in frame.to_dict("records"):
        cands = by_league_day.get((r["lg"], r["date"].date()), [])
        hit = None
        for e in cands:
            if match_team_name(e["home"] or "", [r["home"]]) and match_team_name(e["away"] or "", [r["away"]]):
                hit = e
                break
        mk = corners_market(hit["rows"]) if hit else None
        if not mk:
            continue
        rows.append({**r, "mkt": implied_mean(mk["line"], mk["fair"], disp.get(r["lg"], pooled)), "line": mk["line"]})
    out = {"n": len(rows)}
    if len(rows) < 30:
        print(f"\n  market benchmark: only {len(rows)} matches joined to a corners main line; not reported")
        return out
    b = pd.DataFrame(rows)
    act = b.hc + b.ac
    print(f"\n================ CEILING: the corners market's main line, same matches ({len(b)}) ================")
    for label, pred in (("market implied mean", b.mkt), ("market line itself", b.line),
                        ("E0 production engine", b.e0_h + b.e0_a), ("E2 team rates", b.e2_h + b.e2_a),
                        ("E3 team rates + pressure", b.e3_h + b.e3_a)):
        ok = pred.notna()
        mae = float((act[ok] - pred[ok]).abs().mean())
        rr = float(np.corrcoef(pred[ok], act[ok])[0, 1])
        out[label] = {"n": int(ok.sum()), "mae": mae, "r": rr, "bias": float((act[ok] - pred[ok]).mean())}
        print(f"  {label:28s} n={int(ok.sum()):4d}  MAE {mae:.3f}  r {rr:+.3f}  bias {out[label]['bias']:+.2f}")
    return out


# ---------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-root", required=True)
    ap.add_argument("--out", default=os.path.join(CACHE, "corners_estimators_results.json"))
    args = ap.parse_args()

    hist = load_history(args.history_root)
    cur = load_current(CACHE, history_name_mapper(hist))
    engine = load_engine(CACHE)

    print("================ COVERAGE (per family; dates as data, not as claims about production) ================")
    for lg in LEAGUES:
        h = hist[hist.lg == lg]
        c = cur[cur.lg == lg]
        e = sum(1 for (l, mid) in engine if l == lg)
        ce = sum(1 for mid in c.get("match_id", pd.Series(dtype=str)) if (lg, mid) in engine)
        odds = int(c["p_home"].notna().sum()) if len(c) else 0
        print(f"  {lg:20s} history {len(h):5d} {str(h.date.min())[:10] if len(h) else '-'}..{str(h.date.max())[:10] if len(h) else '-'} | "
              f"current ESPN {len(c):4d} {str(c.date.min())[:10] if len(c) else '-'}..{str(c.date.max())[:10] if len(c) else '-'} | "
              f"current with odds {odds:4d} | engine matches {e:4d}, joined to current {ce:4d}")

    everything = pd.concat([hist, cur], ignore_index=True).sort_values("date")

    # ---- choose (k, h) on the 2025 season ONLY (the held-out season never chooses anything)
    train_targets = hist[(hist.date >= TRAIN_SEASON_START) & (hist.date < HELD_OUT_START)]
    print(f"\n================ SELECTION on the 2025 season: {len(train_targets)} matches ================")
    grid = {}
    for k in K_GRID:
        for h in H_GRID:
            maes = []
            for lg, tg in train_targets.groupby("lg"):
                preds = predict_e2(everything[everything.lg == lg], tg, k, h)
                for (ph, pa), r in zip(preds, tg.itertuples()):
                    if ph is not None:
                        maes.append(abs((r.hc + r.ac) - (ph + pa)))
            grid[(k, h)] = (float(np.mean(maes)), len(maes))
            print(f"  k={k:5.1f} half-life={str(h):6s}  MAE {grid[(k, h)][0]:.4f}  n={grid[(k, h)][1]}")
    k_best, h_best = min(grid, key=lambda key: grid[key][0])
    print(f"  CHOSEN k={k_best} half-life={h_best}")

    # ---- E3 pressure coefficients on the 2025 season ONLY
    X, y_total, share_x, share_y = [], [], [], []
    for lg, tg in train_targets.groupby("lg"):
        preds = predict_e2(everything[everything.lg == lg], tg, k_best, h_best)
        for (ph, pa), r in zip(preds, tg.to_dict("records")):
            feats = pressure_features(r)
            if ph is None or feats is None or feats[1] is None:
                continue
            X.append([1.0, feats[0], feats[1] - 0.5])
            y_total.append((r["hc"] + r["ac"]) - (ph + pa))
            share_x.append([1.0, feats[2]])
            share_y.append((r["hc"] - r["ac"]) - (ph - pa))
    beta_total = np.linalg.lstsq(np.array(X), np.array(y_total), rcond=None)[0] if len(X) > 50 else np.zeros(3)
    beta_share = np.linalg.lstsq(np.array(share_x), np.array(share_y), rcond=None)[0] if len(share_x) > 50 else np.zeros(2)
    print(f"  E3 fit on {len(X)} matches: total_resid = {beta_total[0]:+.3f} {beta_total[1]:+.3f}*|pH-pA| {beta_total[2]:+.3f}*(pOver-0.5); "
          f"margin_resid = {beta_share[0]:+.3f} {beta_share[1]:+.3f}*(pH-pA)")

    # ---- held out: the current season
    held = cur[cur.date >= HELD_OUT_START].copy()
    last_season = {lg: (float(g.hc.mean()), float(g.ac.mean())) for lg, g in hist[hist.date >= TRAIN_SEASON_START].groupby("lg")}
    for col in ("e0_h", "e0_a", "e1_h", "e1_a", "e1r_h", "e1r_a", "e2_h", "e2_a", "e3_h", "e3_a"):
        held[col] = np.nan
    for lg, tg in held.groupby("lg"):
        idx = tg.index
        league_all = everything[everything.lg == lg]
        e2 = predict_e2(league_all, tg, k_best, h_best)
        e1r = rolling_mean(league_all, tg)
        for i, (ph, pa), (rh, ra), r in zip(idx, e2, e1r, tg.to_dict("records")):
            eng = engine.get((lg, r.get("match_id")))
            if eng:
                held.loc[i, ["e0_h", "e0_a"]] = eng
            if lg in last_season:
                held.loc[i, ["e1_h", "e1_a"]] = last_season[lg]
            if rh is not None:
                held.loc[i, ["e1r_h", "e1r_a"]] = (rh, ra)
            if ph is not None:
                held.loc[i, ["e2_h", "e2_a"]] = (ph, pa)
                feats = pressure_features(r)
                adj_total = beta_total[0] + beta_total[1] * feats[0] + beta_total[2] * ((feats[1] if feats[1] is not None else 0.5) - 0.5) if feats else 0.0
                adj_margin = beta_share[0] + beta_share[1] * feats[2] if feats else 0.0
                total, margin = ph + pa + adj_total, ph - pa + adj_margin
                held.loc[i, ["e3_h", "e3_a"]] = (max(0.5, (total + margin) / 2.0), max(0.5, (total - margin) / 2.0))

    print(f"\n================ HELD OUT: current season, {len(held)} ESPN matches ================")
    results = {"chosen": {"k": k_best, "half_life": h_best}, "beta_total": list(map(float, beta_total)), "beta_margin": list(map(float, beta_share)),
               "grid": {f"k={k},h={h}": v for (k, h), v in grid.items()}, "held_out": {}}
    # Same matches for every estimator: rows every estimator can predict.
    common = held.dropna(subset=["e1r_h", "e2_h", "e3_h"])
    common_e0 = common.dropna(subset=["e0_h"])
    for frame, tag in ((common, "all estimable"), (common_e0, "with engine output")):
        print(f"\n  -- {tag} ({len(frame)} matches) --")
        for cols, label in ((("e0_h", "e0_a"), "E0 production engine"), (("e1_h", "e1_a"), "E1 last-season league mean"),
                            (("e1r_h", "e1r_a"), "E1r rolling 365d league mean"), (("e2_h", "e2_a"), "E2 team rates"),
                            (("e3_h", "e3_a"), "E3 team rates + pressure")):
            res = score(frame, cols[0], cols[1], label)
            show(res)
            results["held_out"][f"{tag}|{label}"] = res
    print("\n  per-league bias (actual - predicted) on 'all estimable':")
    for lg in LEAGUES:
        g = common[common.lg == lg]
        if len(g) < 8:
            continue
        parts = []
        for cols, label in ((("e0_h", "e0_a"), "E0"), (("e1_h", "e1_a"), "E1"), (("e1r_h", "e1r_a"), "E1r"), (("e2_h", "e2_a"), "E2"), (("e3_h", "e3_a"), "E3")):
            gg = g.dropna(subset=list(cols))
            if len(gg):
                parts.append(f"{label} {((gg.hc + gg.ac) - (gg[cols[0]] + gg[cols[1]])).mean():+.2f}")
        print(f"    {lg:20s} n={len(g):3d}  " + "  ".join(parts))
    results["market_benchmark"] = market_benchmark(common, hist)
    held.to_csv(os.path.join(CACHE, "corners_estimators_heldout.csv"), index=False)
    io.open(args.out, "w", encoding="utf-8").write(json.dumps(results, indent=1, default=str))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
