from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import math

import numpy as np
import pandas as pd

from nba_betting.sim_games import SimConfig
from nba_betting.teams import to_tricode


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def daterange(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def american_to_prob(price: float) -> float:
    try:
        p = float(price)
    except Exception:
        return float("nan")
    if p == 0:
        return float("nan")
    if p > 0:
        return 100.0 / (p + 100.0)
    return abs(p) / (abs(p) + 100.0)


def american_profit(price: float, win: bool) -> float:
    if not win:
        return -1.0
    p = float(price)
    if p > 0:
        return p / 100.0
    return 100.0 / abs(p)


def load_day(ds: str) -> pd.DataFrame | None:
    pred_p = PROCESSED / f"predictions_{ds}.csv"
    finals_p = PROCESSED / f"finals_{ds}.csv"
    odds_p = PROCESSED / f"game_odds_{ds}.csv"
    if not (pred_p.exists() and finals_p.exists() and odds_p.exists()):
        return None

    p = pd.read_csv(pred_p)
    f = pd.read_csv(finals_p)
    o = pd.read_csv(odds_p)

    # date normalize
    for df in (p, f, o):
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    # add tri codes from names
    p["home_tri"] = p.get("home_team", "").astype(str).map(to_tricode)
    p["away_tri"] = p.get("visitor_team", "").astype(str).map(to_tricode)
    o["home_tri"] = o.get("home_team", "").astype(str).map(to_tricode)
    o["away_tri"] = o.get("visitor_team", "").astype(str).map(to_tricode)

    # join pred<->finals on tri
    keys_pf = ["date", "home_tri", "away_tri"]
    if not all(k in p.columns for k in keys_pf) or not all(k in f.columns for k in keys_pf):
        return None
    pf = p.merge(f, on=keys_pf, how="inner", suffixes=("_p", "_f"))
    if pf.empty:
        return None

    # join odds on tri
    keys_o = ["date", "home_tri", "away_tri"]
    m = pf.merge(o, on=keys_o, how="inner", suffixes=("", "_odds"))
    if m.empty:
        return None

    # actual margin
    m["actual_margin"] = pd.to_numeric(m.get("home_pts"), errors="coerce") - pd.to_numeric(m.get("visitor_pts"), errors="coerce")

    m["pred_margin"] = pd.to_numeric(m.get("spread_margin"), errors="coerce")
    m["home_spread"] = pd.to_numeric(m.get("home_spread"), errors="coerce")

    # Prices may be missing historically; assume -110
    # If the column is missing, m.get(...) returns a scalar; handle both cases.
    hp = m.get("home_spread_price")
    ap = m.get("away_spread_price")
    m["home_price"] = pd.to_numeric(hp, errors="coerce") if isinstance(hp, pd.Series) else float("nan")
    m["away_price"] = pd.to_numeric(ap, errors="coerce") if isinstance(ap, pd.Series) else float("nan")
    m["home_price"] = m["home_price"].fillna(-110.0)
    m["away_price"] = m["away_price"].fillna(-110.0)

    # Outcome: home covers if actual_margin + home_spread > 0 (push excluded)
    adj = m["actual_margin"] + m["home_spread"]
    mask = (~adj.isna()) & (~m["pred_margin"].isna()) & (~m["home_spread"].isna())
    m = m[mask]
    if m.empty:
        return None
    adj = m["actual_margin"] + m["home_spread"]
    m = m[adj != 0]
    if m.empty:
        return None

    m["y_home_cover"] = (adj > 0).astype(int)
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate ATS calibration over a date window")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--min-edge", type=float, default=0.02, help="Bet when model edge over market >= this")
    ap.add_argument(
        "--sweep-edges",
        type=str,
        default=None,
        help="Optional comma-separated list of min-edge thresholds to sweep; writes a CSV summary.",
    )
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    frames: list[pd.DataFrame] = []
    for d in daterange(start, end):
        ds = d.strftime("%Y-%m-%d")
        m = load_day(ds)
        if m is not None and not m.empty:
            m = m.copy()
            m["ds"] = ds
            frames.append(m)

    if not frames:
        print({"error": "No overlapping predictions/finals/odds"})
        return 2

    df = pd.concat(frames, ignore_index=True)
    cfg = SimConfig()

    eps = 1e-6
    y = df["y_home_cover"].astype(float)
    line = df["home_spread"].astype(float)
    mu = df["pred_margin"].astype(float)

    threshold = -line

    # Model prob (current calibrated)
    mu_ats = float(cfg.ats_scale) * mu + float(cfg.ats_bias)
    z = (threshold - mu_ats) / max(1e-6, float(cfg.sd_margin_ats))
    p_home = (1.0 - z.map(phi)).clip(eps, 1 - eps)

    # Model prob (legacy / pre-calibration): used margin_mu directly and sd_margin
    z_old = (threshold - mu) / max(1e-6, float(cfg.sd_margin))
    p_home_old = (1.0 - z_old.map(phi)).clip(eps, 1 - eps)

    # market prob (no-vig if both prices exist)
    p_mkt_home = df["home_price"].map(american_to_prob)
    p_mkt_away = df["away_price"].map(american_to_prob)
    s = (p_mkt_home + p_mkt_away).replace(0, np.nan)
    p_mkt_home_nv = (p_mkt_home / s).clip(eps, 1 - eps)

    def _brier(p: pd.Series) -> float:
        return float(((p - y) ** 2).mean())

    def _logloss(p: pd.Series) -> float:
        return float((-(y * np.log(p) + (1 - y) * np.log(1 - p))).mean())

    brier_model = _brier(p_home)
    ll_model = _logloss(p_home)
    brier_old = _brier(p_home_old)
    ll_old = _logloss(p_home_old)

    brier_mkt = float(((p_mkt_home_nv - y) ** 2).mean())
    ll_mkt = float((-(y * np.log(p_mkt_home_nv) + (1 - y) * np.log(1 - p_mkt_home_nv))).mean())

    def _bet_eval(p_home_like: pd.Series, min_edge: float) -> dict:
        edge_home = p_home_like - p_mkt_home_nv
        edge_away = (1 - p_home_like) - (1 - p_mkt_home_nv)
        choose_home = edge_home >= edge_away
        edge = edge_home.where(choose_home, edge_away)

        bet_mask = edge >= float(min_edge)
        profits: list[float] = []
        hits = 0
        for i in df[bet_mask].index:
            yh = bool(df.loc[i, "y_home_cover"] == 1)
            if bool(choose_home.loc[i]):
                price = float(df.loc[i, "home_price"])
                win = yh
            else:
                price = float(df.loc[i, "away_price"])
                win = (not yh)
            prof = american_profit(price, win=win)
            profits.append(prof)
            if win:
                hits += 1
        roi = float(np.nan) if not profits else float(np.mean(profits))
        hit_rate = float(np.nan) if not profits else float(hits / len(profits))
        return {"n_bets": int(len(profits)), "hit_rate": hit_rate, "roi": roi}

    bet_model = _bet_eval(p_home, float(args.min_edge))
    bet_old = _bet_eval(p_home_old, float(args.min_edge))

    # Optimal linear blend vs market: p = w*model + (1-w)*market
    best_brier = {"w": None, "brier": None, "logloss": None}
    best_ll = {"w": None, "brier": None, "logloss": None}
    for wi in range(0, 101):
        w = wi / 100.0
        p_blend = (w * p_home + (1 - w) * p_mkt_home_nv).clip(eps, 1 - eps)
        b = _brier(p_blend)
        ll = _logloss(p_blend)
        if (best_brier["brier"] is None) or (b < float(best_brier["brier"])):
            best_brier = {"w": float(w), "brier": float(b), "logloss": float(ll)}
        if (best_ll["logloss"] is None) or (ll < float(best_ll["logloss"])):
            best_ll = {"w": float(w), "brier": float(b), "logloss": float(ll)}

    p_blend_brier = (float(best_brier["w"]) * p_home + (1 - float(best_brier["w"])) * p_mkt_home_nv).clip(eps, 1 - eps)
    p_blend_ll = (float(best_ll["w"]) * p_home + (1 - float(best_ll["w"])) * p_mkt_home_nv).clip(eps, 1 - eps)
    bet_blend_brier = _bet_eval(p_blend_brier, float(args.min_edge))
    bet_blend_ll = _bet_eval(p_blend_ll, float(args.min_edge))

    # Optional sweep
    sweep_rows: list[dict] = []
    if args.sweep_edges:
        try:
            edges = [float(x.strip()) for x in str(args.sweep_edges).split(",") if x.strip()]
        except Exception:
            edges = []
        for me in edges:
            bm = _bet_eval(p_home, float(me))
            bo = _bet_eval(p_home_old, float(me))
            sweep_rows.append({
                "min_edge": float(me),
                "n_games": int(len(df)),
                "model_n_bets": int(bm["n_bets"]),
                "model_hit_rate": bm["hit_rate"],
                "model_roi": bm["roi"],
                "old_n_bets": int(bo["n_bets"]),
                "old_hit_rate": bo["hit_rate"],
                "old_roi": bo["roi"],
            })
        if sweep_rows:
            sweep_path = PROCESSED / f"ats_sweep_{args.start}_{args.end}.csv"
            pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)

    out = {
        "start": args.start,
        "end": args.end,
        "n_games": int(len(df)),
        "cfg": {"ats_scale": cfg.ats_scale, "ats_bias": cfg.ats_bias, "sd_margin_ats": cfg.sd_margin_ats},
        "brier_model": brier_model,
        "logloss_model": ll_model,
        "brier_old": brier_old,
        "logloss_old": ll_old,
        "brier_market_nv": brier_mkt,
        "logloss_market_nv": ll_mkt,
        "min_edge": float(args.min_edge),
        "bet_model": bet_model,
        "bet_old": bet_old,
        "blend_opt_brier": best_brier,
        "blend_opt_logloss": best_ll,
        "bet_blend_opt_brier": bet_blend_brier,
        "bet_blend_opt_logloss": bet_blend_ll,
    }

    out_path = PROCESSED / f"ats_eval_{args.start}_{args.end}_edge{args.min_edge:.2f}.json".replace(".", "p")
    try:
        import json

        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception:
        pass

    print(out)
    print({"output": str(out_path)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
