import argparse
from pathlib import Path
from datetime import datetime, timedelta
import math
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def _norm_team_name(name: str) -> str:
    x = (name or "").strip().upper()
    x = x.replace(".", "")
    x = " ".join(x.split())
    return x


# Common team-name variants -> tri code.
_TEAM_NAME_TO_TRI: dict[str, str] = {
    "ATLANTA HAWKS": "ATL",
    "BOSTON CELTICS": "BOS",
    "BROOKLYN NETS": "BKN",
    "NEW JERSEY NETS": "BKN",
    "CHARLOTTE HORNETS": "CHA",
    "CHICAGO BULLS": "CHI",
    "CLEVELAND CAVALIERS": "CLE",
    "DALLAS MAVERICKS": "DAL",
    "DENVER NUGGETS": "DEN",
    "DETROIT PISTONS": "DET",
    "GOLDEN STATE WARRIORS": "GSW",
    "HOUSTON ROCKETS": "HOU",
    "INDIANA PACERS": "IND",
    "LOS ANGELES CLIPPERS": "LAC",
    "LA CLIPPERS": "LAC",
    "LOS ANGELES LAKERS": "LAL",
    "LA LAKERS": "LAL",
    "MEMPHIS GRIZZLIES": "MEM",
    "MIAMI HEAT": "MIA",
    "MILWAUKEE BUCKS": "MIL",
    "MINNESOTA TIMBERWOLVES": "MIN",
    "NEW ORLEANS PELICANS": "NOP",
    "NEW ORLEANS HORNETS": "NOP",
    "NEW YORK KNICKS": "NYK",
    "OKLAHOMA CITY THUNDER": "OKC",
    "ORLANDO MAGIC": "ORL",
    "PHILADELPHIA 76ERS": "PHI",
    "PHOENIX SUNS": "PHX",
    "PORTLAND TRAIL BLAZERS": "POR",
    "PORTLAND TRAILBLAZERS": "POR",
    "SACRAMENTO KINGS": "SAC",
    "SAN ANTONIO SPURS": "SAS",
    "TORONTO RAPTORS": "TOR",
    "UTAH JAZZ": "UTA",
    "WASHINGTON WIZARDS": "WAS",
}


def _team_to_tri(name: str) -> str | None:
    x = _norm_team_name(name)
    # If it's already a tri-code, accept it.
    if len(x) == 3 and x.isalpha():
        tri_alias = {
            "PHO": "PHX",
            "GS": "GSW",
            "SA": "SAS",
            "NO": "NOP",
            "NY": "NYK",
        }
        return tri_alias.get(x, x)
    return _TEAM_NAME_TO_TRI.get(x)


def daterange(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def _american_to_prob(price: float) -> float:
    try:
        p = float(price)
    except Exception:
        return float("nan")
    if p == 0:
        return float("nan")
    if p > 0:
        return 100.0 / (p + 100.0)
    return abs(p) / (abs(p) + 100.0)


def _american_profit(price: float, win: bool) -> float:
    if not win:
        return -1.0
    try:
        p = float(price)
    except Exception:
        return float("nan")
    if p == 0:
        return float("nan")
    if p > 0:
        return p / 100.0
    return 100.0 / abs(p)


def _norm_cdf(z: float) -> float:
    # Standard normal CDF via erf
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _merge_day(ds: str) -> pd.DataFrame | None:
    pred = _load_csv(PROCESSED / f"predictions_{ds}.csv")
    finals = _load_csv(PROCESSED / f"finals_{ds}.csv")
    odds = _load_csv(PROCESSED / f"game_odds_{ds}.csv")
    if pred is None or finals is None or odds is None:
        return None

    p = pred.copy()
    f = finals.copy()
    o = odds.copy()

    # Normalize date
    if "date" in p.columns:
        p["date"] = pd.to_datetime(p["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "date" in f.columns:
        f["date"] = pd.to_datetime(f["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "date" in o.columns:
        o["date"] = pd.to_datetime(o["date"], errors="coerce").dt.strftime("%Y-%m-%d")

    # Ensure predictions have tri-codes so we can join to finals robustly.
    if "home_tri" not in p.columns:
        p["home_tri"] = p.get("home_team", "").astype(str).map(_team_to_tri)
    away_name_col_p = "visitor_team" if "visitor_team" in p.columns else ("away_team" if "away_team" in p.columns else None)
    if "away_tri" not in p.columns:
        if away_name_col_p is None:
            return None
        p["away_tri"] = p.get(away_name_col_p, "").astype(str).map(_team_to_tri)

    # Ensure finals have expected columns (historically these are already tri-coded).
    if "away_tri" not in f.columns and "visitor_tri" in f.columns:
        f = f.rename(columns={"visitor_tri": "away_tri"})

    keys_pf = [c for c in ("date", "home_tri", "away_tri") if c in p.columns and c in f.columns]
    if len(keys_pf) < 3:
        return None

    pf = p.merge(f, on=keys_pf, how="inner", suffixes=("_p", "_f"))
    if pf.empty:
        return None

    # Join with odds using tri-codes derived from team names to avoid name-variant mismatches.
    o = o.copy()
    if "home_tri" not in o.columns:
        o["home_tri"] = o.get("home_team", "").astype(str).map(_team_to_tri)
    away_name_col = "visitor_team" if "visitor_team" in o.columns else ("away_team" if "away_team" in o.columns else None)
    if "away_tri" not in o.columns:
        if away_name_col is None:
            return None
        o["away_tri"] = o.get(away_name_col, "").astype(str).map(_team_to_tri)
    keys_o = [c for c in ("date", "home_tri", "away_tri") if c in pf.columns and c in o.columns]
    if len(keys_o) < 3:
        return None
    m = pf.merge(o, on=keys_o, how="inner")
    if m.empty:
        return None

    # Actual margin
    if {"home_pts", "visitor_pts"}.issubset(m.columns):
        m["actual_margin"] = pd.to_numeric(m["home_pts"], errors="coerce") - pd.to_numeric(m["visitor_pts"], errors="coerce")
    elif {"home_score", "visitor_score"}.issubset(m.columns):
        m["actual_margin"] = pd.to_numeric(m["home_score"], errors="coerce") - pd.to_numeric(m["visitor_score"], errors="coerce")
    else:
        return None

    # Required cols
    if "spread_margin" not in m.columns:
        return None
    if "home_spread" not in m.columns:
        return None

    m["mu"] = pd.to_numeric(m["spread_margin"], errors="coerce")
    m["line"] = pd.to_numeric(m["home_spread"], errors="coerce")
    # Some historical odds snapshots do not include spread prices.
    # Assume -110/-110 when missing so we can still compute implied probs and a reasonable ROI proxy.
    m["home_price"] = pd.to_numeric(m.get("home_spread_price"), errors="coerce")
    m["away_price"] = pd.to_numeric(m.get("away_spread_price"), errors="coerce")
    if "home_spread_price" not in m.columns:
        m["home_price"] = float("nan")
    if "away_spread_price" not in m.columns:
        m["away_price"] = float("nan")
    m["home_price"] = m["home_price"].fillna(-110.0)
    m["away_price"] = m["away_price"].fillna(-110.0)

    # Outcome: home covers if actual_margin + line > 0; push excluded
    adj = m["actual_margin"] + m["line"]
    m = m[~adj.isna() & ~m["mu"].isna() & ~m["line"].isna()]
    if m.empty:
        return None
    m = m[adj != 0]
    if m.empty:
        return None
    m["y_home_cover"] = (adj > 0).astype(float)

    # Market implied probs (viggy, but good baseline)
    m["p_mkt_home"] = m["home_price"].map(_american_to_prob)
    m["p_mkt_away"] = m["away_price"].map(_american_to_prob)

    # No-vig normalization (book prices usually include vig, so p_home+p_away > 1)
    s = pd.to_numeric(m["p_mkt_home"], errors="coerce") + pd.to_numeric(m["p_mkt_away"], errors="coerce")
    m["p_mkt_home_nv"] = m["p_mkt_home"] / s
    m["p_mkt_away_nv"] = m["p_mkt_away"] / s

    return m


def tune_ats_params(
    df: pd.DataFrame,
    sigmas: list[float],
    scales: list[float],
    biases: list[float],
    min_edge: float = 0.0,
) -> pd.DataFrame:
    rows = []
    y = pd.to_numeric(df["y_home_cover"], errors="coerce")
    mu = pd.to_numeric(df["mu"], errors="coerce")
    line = pd.to_numeric(df["line"], errors="coerce")
    p_mkt_home = pd.to_numeric(df.get("p_mkt_home_nv", df.get("p_mkt_home")), errors="coerce")
    p_mkt_away = pd.to_numeric(df.get("p_mkt_away_nv", df.get("p_mkt_away")), errors="coerce")
    home_price = pd.to_numeric(df["home_price"], errors="coerce")
    away_price = pd.to_numeric(df["away_price"], errors="coerce")

    base_mask = (~y.isna()) & (~mu.isna()) & (~line.isna())
    base_mask = base_mask & (~home_price.isna()) & (~away_price.isna())
    if base_mask.sum() == 0:
        return pd.DataFrame()

    y = y[base_mask]
    mu = mu[base_mask]
    line = line[base_mask]
    p_mkt_home = p_mkt_home[base_mask]
    p_mkt_away = p_mkt_away[base_mask]
    home_price = home_price[base_mask]
    away_price = away_price[base_mask]

    eps = 1e-6
    for scale in scales:
        for bias in biases:
            mu_adj = scale * mu + bias
            for s in sigmas:
                # P(home covers) = P(Margin > -line) where Margin ~ N(mu_adj, s)
                z = (-line - mu_adj) / float(s)
                p_home = 1.0 - z.map(_norm_cdf)
                p_home = pd.to_numeric(p_home, errors="coerce").clip(eps, 1 - eps)

                brier = float(((p_home - y) ** 2).mean())
                logloss = float((-(y * np.log(p_home) + (1 - y) * np.log(1 - p_home))).mean())

                # Pick a side if model edge clears threshold
                edge_home = p_home - p_mkt_home
                edge_away = (1 - p_home) - p_mkt_away
                choose_home = edge_home >= edge_away
                edge = edge_home.where(choose_home, edge_away)
                pick_home = choose_home.astype(bool)

                bet_mask = (~edge.isna()) & (edge >= float(min_edge))
                if bet_mask.sum() > 0:
                    profits = []
                    for i in edge[bet_mask].index:
                        yh = bool(y.loc[i] == 1.0)
                        if pick_home.loc[i]:
                            profits.append(_american_profit(home_price.loc[i], win=yh))
                        else:
                            profits.append(_american_profit(away_price.loc[i], win=(not yh)))
                    roi = float(pd.to_numeric(pd.Series(profits), errors="coerce").mean())
                    n_bets = int(len(profits))
                else:
                    roi = float("nan")
                    n_bets = 0

                rows.append({
                    "scale": float(scale),
                    "bias": float(bias),
                    "sigma": float(s),
                    "n_games": int(len(y)),
                    "brier": brier,
                    "logloss": logloss,
                    "min_edge": float(min_edge),
                    "n_bets": n_bets,
                    "roi": roi,
                })

    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Tune ATS cover probability via margin sigma grid-search")
    ap.add_argument("--start", type=str, required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", type=str, required=True, help="YYYY-MM-DD")
    ap.add_argument("--min-edge", type=float, default=0.02, help="Only bet when model edge over market >= this")
    ap.add_argument("--sigma-min", type=float, default=8.0)
    ap.add_argument("--sigma-max", type=float, default=18.0)
    ap.add_argument("--sigma-step", type=float, default=0.5)
    ap.add_argument("--scale-min", type=float, default=0.85)
    ap.add_argument("--scale-max", type=float, default=1.15)
    ap.add_argument("--scale-step", type=float, default=0.05)
    ap.add_argument("--bias-min", type=float, default=-1.5)
    ap.add_argument("--bias-max", type=float, default=1.5)
    ap.add_argument("--bias-step", type=float, default=0.5)
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    frames = []
    for d in daterange(start, end):
        ds = d.strftime("%Y-%m-%d")
        m = _merge_day(ds)
        if m is not None and not m.empty:
            frames.append(m)

    if not frames:
        print({"error": "No overlapping predictions/finals/odds for range"})
        return 2

    df = pd.concat(frames, ignore_index=True)
    sigmas = []
    s = float(args.sigma_min)
    while s <= float(args.sigma_max) + 1e-9:
        sigmas.append(round(s, 3))
        s += float(args.sigma_step)

    scales = []
    x = float(args.scale_min)
    while x <= float(args.scale_max) + 1e-9:
        scales.append(round(x, 3))
        x += float(args.scale_step)

    biases = []
    b = float(args.bias_min)
    while b <= float(args.bias_max) + 1e-9:
        biases.append(round(b, 3))
        b += float(args.bias_step)

    out = tune_ats_params(df, sigmas=sigmas, scales=scales, biases=biases, min_edge=float(args.min_edge))
    edge_tag = f"edge{float(args.min_edge):.2f}".replace(".", "p")
    out_path = PROCESSED / f"ats_sigma_tuning_{args.start}_{args.end}_{edge_tag}.csv"
    out.to_csv(out_path, index=False)

    best = None
    if out is not None and not out.empty:
        best = out.sort_values(["logloss", "brier"], ascending=True).head(1).to_dict("records")[0]
    print({"rows": 0 if out is None else int(len(out)), "out": str(out_path), "best": best})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
