import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def daterange(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def brier_score(probs: pd.Series, outcomes: pd.Series) -> float:
    p = pd.to_numeric(probs, errors="coerce")
    y = pd.to_numeric(outcomes, errors="coerce")
    m = (~p.isna()) & (~y.isna())
    if m.sum() == 0:
        return float("nan")
    return float(((p[m] - y[m]) ** 2).mean())


def log_loss(probs: pd.Series, outcomes: pd.Series, eps: float = 1e-6) -> float:
    p = pd.to_numeric(probs, errors="coerce").clip(eps, 1 - eps)
    y = pd.to_numeric(outcomes, errors="coerce")
    m = (~p.isna()) & (~y.isna())
    if m.sum() == 0:
        return float("nan")
    return float(-(y[m] * np.log(p[m]) + (1 - y[m]) * np.log(1 - p[m])).mean())


def mae(a: pd.Series, b: pd.Series) -> float:
    x = pd.to_numeric(a, errors="coerce")
    y = pd.to_numeric(b, errors="coerce")
    m = (~x.isna()) & (~y.isna())
    if m.sum() == 0:
        return float("nan")
    return float((x[m] - y[m]).abs().mean())


def rmse(a: pd.Series, b: pd.Series) -> float:
    x = pd.to_numeric(a, errors="coerce")
    y = pd.to_numeric(b, errors="coerce")
    m = (~x.isna()) & (~y.isna())
    if m.sum() == 0:
        return float("nan")
    return float(np.sqrt(((x[m] - y[m]) ** 2).mean()))


def acc_from_scores(pred_side: pd.Series, actual_side: pd.Series) -> float:
    """Accuracy for binary 0/1 labels, ignoring NaNs."""
    p = pd.to_numeric(pred_side, errors="coerce")
    y = pd.to_numeric(actual_side, errors="coerce")
    m = (~p.isna()) & (~y.isna())
    if m.sum() == 0:
        return float("nan")
    return float((p[m].astype(int) == y[m].astype(int)).mean())


def _safe_float(x) -> float | None:
    try:
        v = float(pd.to_numeric(x, errors="coerce"))
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _team_name_to_tri_map() -> dict[str, str]:
    sched_path = PROCESSED / "schedule_2025_26.csv"
    df = _load_csv(sched_path)
    if df is None or df.empty:
        return {}

    def full_name(city, name) -> str:
        return f"{str(city or '').strip()} {str(name or '').strip()}".strip().upper()

    m: dict[str, str] = {}
    for _, r in df.iterrows():
        ht = full_name(r.get("home_city"), r.get("home_name"))
        at = full_name(r.get("away_city"), r.get("away_name"))
        htri = str(r.get("home_tricode") or "").strip().upper()
        atri = str(r.get("away_tricode") or "").strip().upper()
        if ht and len(htri) == 3:
            m.setdefault(ht, htri)
        if at and len(atri) == 3:
            m.setdefault(at, atri)
    return m


def _pick_prob_col(pred: pd.DataFrame) -> str | None:
    for c in ("home_win_prob_cal", "home_win_prob", "prob_home_win", "win_prob"):
        if c in pred.columns:
            return c
    return None


def _merge_predictions_finals(ds: str, name_to_tri: dict[str, str]) -> pd.DataFrame | None:
    pred = _load_csv(PROCESSED / f"predictions_{ds}.csv")
    fin = _load_csv(PROCESSED / f"finals_{ds}.csv")
    if pred is None or pred.empty or fin is None or fin.empty:
        return None

    p = pred.copy()
    if "home_team" not in p.columns or "visitor_team" not in p.columns:
        return None
    p["home_team_u"] = p["home_team"].astype(str).str.strip().str.upper()
    p["away_team_u"] = p["visitor_team"].astype(str).str.strip().str.upper()
    p["home_tri"] = p["home_team_u"].map(name_to_tri)
    p["away_tri"] = p["away_team_u"].map(name_to_tri)
    p["home_tri"] = p["home_tri"].fillna("").astype(str).str.strip().str.upper()
    p["away_tri"] = p["away_tri"].fillna("").astype(str).str.strip().str.upper()
    p = p[(p["home_tri"].str.len() == 3) & (p["away_tri"].str.len() == 3)].copy()
    if p.empty:
        return None

    f = fin.copy()
    if "home_tri" in f.columns:
        f["home_tri"] = f["home_tri"].astype(str).str.strip().str.upper()
    else:
        f["home_tri"] = np.nan
    if "away_tri" in f.columns:
        f["away_tri"] = f["away_tri"].astype(str).str.strip().str.upper()
    else:
        f["away_tri"] = np.nan
    f["home_tri"] = f["home_tri"].fillna("").astype(str).str.strip().str.upper()
    f["away_tri"] = f["away_tri"].fillna("").astype(str).str.strip().str.upper()
    f = f[(f["home_tri"].str.len() == 3) & (f["away_tri"].str.len() == 3)].copy()
    if f.empty:
        return None

    m = p.merge(f, on=["home_tri", "away_tri"], how="inner", suffixes=("", "_act"))
    if m.empty:
        return None
    return m


def evaluate_games_for_day(ds: str, name_to_tri: dict[str, str]) -> dict:
    m = _merge_predictions_finals(ds, name_to_tri)
    if m is None or m.empty:
        return {"n_games": 0}

    pcol = _pick_prob_col(m)

    m["act_margin"] = pd.to_numeric(m.get("home_pts"), errors="coerce") - pd.to_numeric(m.get("visitor_pts"), errors="coerce")
    m["act_total"] = pd.to_numeric(m.get("home_pts"), errors="coerce") + pd.to_numeric(m.get("visitor_pts"), errors="coerce")
    m["act_home_win"] = (m["act_margin"] > 0).astype(int)

    # Market lines: prefer columns inside predictions; fallback to game_odds_<date>.csv
    def _col_or_nan(col: str) -> pd.Series:
        if col in m.columns:
            return pd.to_numeric(m[col], errors="coerce")
        return pd.Series([np.nan] * len(m))

    market_total = _col_or_nan("total")
    market_spread = _col_or_nan("home_spread")

    if market_total.isna().all() or market_spread.isna().all():
        odds = _load_csv(PROCESSED / f"game_odds_{ds}.csv")
        if odds is not None and not odds.empty:
            o = odds.copy()
            o["home_team_u"] = o.get("home_team", "").astype(str).str.strip().str.upper()
            o["away_team_u"] = o.get("visitor_team", "").astype(str).str.strip().str.upper()
            o["home_tri"] = o["home_team_u"].map(name_to_tri)
            o["away_tri"] = o["away_team_u"].map(name_to_tri)
            o = o[["home_tri", "away_tri"] + [c for c in ("total", "home_spread") if c in o.columns]].copy()
            m2 = m.merge(o, on=["home_tri", "away_tri"], how="left", suffixes=("", "_odds"))
            if "total_odds" in m2.columns:
                market_total = market_total.fillna(pd.to_numeric(m2["total_odds"], errors="coerce"))
            if "home_spread_odds" in m2.columns:
                market_spread = market_spread.fillna(pd.to_numeric(m2["home_spread_odds"], errors="coerce"))

    out: dict[str, object] = {"n_games": int(len(m))}

    if pcol is not None:
        out["home_win_brier"] = brier_score(m[pcol], m["act_home_win"])
        out["home_win_logloss"] = log_loss(m[pcol], m["act_home_win"])

    if "spread_margin" in m.columns:
        out["margin_mae"] = mae(m["spread_margin"], m["act_margin"])
        out["margin_rmse"] = rmse(m["spread_margin"], m["act_margin"])

    if "totals" in m.columns:
        out["total_mae"] = mae(m["totals"], m["act_total"])
        out["total_rmse"] = rmse(m["totals"], m["act_total"])

    # ATS / O-U classification using market lines (exclude pushes)
    if ("spread_margin" in m.columns) and (not market_spread.isna().all()):
        pm = pd.to_numeric(m["spread_margin"], errors="coerce")
        am = pd.to_numeric(m["act_margin"], errors="coerce")
        line = pd.to_numeric(market_spread, errors="coerce")
        actual_cover = (am + line > 0).astype(float)
        push = (am + line == 0)
        pred_cover = (pm + line > 0).astype(float)
        mask = (~push) & (~pm.isna()) & (~am.isna()) & (~line.isna())
        if mask.sum() > 0:
            out["ats_acc"] = float((pred_cover[mask].astype(int) == actual_cover[mask].astype(int)).mean())
            out["n_ats"] = int(mask.sum())

    if ("totals" in m.columns) and (not market_total.isna().all()):
        pt = pd.to_numeric(m["totals"], errors="coerce")
        at = pd.to_numeric(m["act_total"], errors="coerce")
        tline = pd.to_numeric(market_total, errors="coerce")
        actual_over = (at - tline > 0).astype(float)
        push = (at - tline == 0)
        pred_over = (pt - tline > 0).astype(float)
        mask = (~push) & (~pt.isna()) & (~at.isna()) & (~tline.isna())
        if mask.sum() > 0:
            out["ou_acc"] = float((pred_over[mask].astype(int) == actual_over[mask].astype(int)).mean())
            out["n_ou"] = int(mask.sum())

    return out


def evaluate_quarter_totals_for_day(ds: str) -> dict:
    rq = _load_csv(PROCESSED / f"recon_quarters_{ds}.csv")
    if rq is None or rq.empty:
        return {"n_games": 0}

    df = rq.copy()

    # Treat 0 totals as missing when game totals are positive (0 is almost surely "not captured")
    for c in [
        "actual_q1_total",
        "actual_q2_total",
        "actual_q3_total",
        "actual_q4_total",
        "actual_h1_total",
        "actual_h2_total",
        "actual_game_total",
    ]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            df.loc[df[c] == 0, c] = np.nan

    # If any component quarter is missing, treat derived half/game totals as missing too.
    if {"actual_q1_total", "actual_q2_total", "actual_h1_total"}.issubset(df.columns):
        df.loc[df["actual_q1_total"].isna() | df["actual_q2_total"].isna(), "actual_h1_total"] = np.nan
    if {"actual_q3_total", "actual_q4_total", "actual_h2_total"}.issubset(df.columns):
        df.loc[df["actual_q3_total"].isna() | df["actual_q4_total"].isna(), "actual_h2_total"] = np.nan
    if {"actual_q1_total", "actual_q2_total", "actual_q3_total", "actual_q4_total", "actual_game_total"}.issubset(df.columns):
        df.loc[
            df["actual_q1_total"].isna() | df["actual_q2_total"].isna() | df["actual_q3_total"].isna() | df["actual_q4_total"].isna(),
            "actual_game_total",
        ] = np.nan

    out: dict[str, object] = {"n_games": int(len(df))}

    def _metric_pair(actual_col: str, pred_col: str, key_prefix: str):
        if actual_col not in df.columns or pred_col not in df.columns:
            return
        out[f"{key_prefix}_mae"] = mae(df[pred_col], df[actual_col])
        out[f"{key_prefix}_rmse"] = rmse(df[pred_col], df[actual_col])

    _metric_pair("actual_q1_total", "pred_q1_total", "q1_total")
    _metric_pair("actual_q2_total", "pred_q2_total", "q2_total")
    _metric_pair("actual_q3_total", "pred_q3_total", "q3_total")
    _metric_pair("actual_q4_total", "pred_q4_total", "q4_total")
    _metric_pair("actual_h1_total", "pred_h1_total", "h1_total")
    _metric_pair("actual_h2_total", "pred_h2_total", "h2_total")
    _metric_pair("actual_game_total", "pred_game_total", "game_total")

    return out


def evaluate_props_for_day(ds: str) -> dict:
    pp = _load_csv(PROCESSED / f"props_predictions_{ds}.csv")
    pa = _load_csv(PROCESSED / f"props_actuals_{ds}.csv")
    if pp is None or pp.empty or pa is None or pa.empty:
        return {"n_rows": 0}

    p = pp.copy()
    a = pa.copy()

    # Filter to players we intended to score for the slate
    if "team_on_slate" in p.columns:
        p = p[p["team_on_slate"].astype(str).str.lower().isin(["true", "1", "t", "yes"])].copy()
    if "playing_today" in p.columns:
        p = p[p["playing_today"].astype(str).str.lower().isin(["true", "1", "t", "yes"])].copy()

    p["player_id"] = pd.to_numeric(p.get("player_id"), errors="coerce")
    a["player_id"] = pd.to_numeric(a.get("player_id"), errors="coerce")

    m = p.merge(a, on=["player_id"], how="inner", suffixes=("_pred", "_act"))
    if m.empty:
        return {"n_rows": 0}

    out: dict[str, object] = {"n_rows": int(len(m))}

    # Evaluate the core stats we have actuals for
    pairs = [
        ("pred_pts", "pts", "pts"),
        ("pred_reb", "reb", "reb"),
        ("pred_ast", "ast", "ast"),
        ("pred_threes", "threes", "threes"),
        ("pred_pra", "pra", "pra"),
    ]

    for pred_col, act_col, key in pairs:
        if pred_col in m.columns and act_col in m.columns:
            out[f"{key}_mae"] = mae(m[pred_col], m[act_col])
            out[f"{key}_rmse"] = rmse(m[pred_col], m[act_col])

    return out


def _iter_smart_sim_json_for_day(ds: str):
    pat = f"smart_sim_{ds}_*.json"
    for p in PROCESSED.glob(pat):
        yield p


def evaluate_smart_sim_for_day(ds: str, name_to_tri: dict[str, str] | None = None) -> dict:
    fin = _load_csv(PROCESSED / f"finals_{ds}.csv")
    if fin is None or fin.empty:
        return {"n_games": 0}

    finals = fin.copy()

    # Support multiple finals schemas:
    # - Current: home_tri/away_tri + home_pts/visitor_pts
    # - Older: home_team/visitor_team + home_score/visitor_score
    if "home_tri" in finals.columns:
        finals["home_tri"] = finals["home_tri"].astype(str).str.strip().str.upper()
    elif "home_team" in finals.columns and name_to_tri:
        finals["home_tri"] = finals["home_team"].astype(str).str.strip().map(name_to_tri)
    else:
        finals["home_tri"] = np.nan

    if "away_tri" in finals.columns:
        finals["away_tri"] = finals["away_tri"].astype(str).str.strip().str.upper()
    elif "visitor_team" in finals.columns and name_to_tri:
        finals["away_tri"] = finals["visitor_team"].astype(str).str.strip().map(name_to_tri)
    else:
        finals["away_tri"] = np.nan

    if "home_pts" in finals.columns:
        finals["home_pts"] = pd.to_numeric(finals["home_pts"], errors="coerce")
    elif "home_score" in finals.columns:
        finals["home_pts"] = pd.to_numeric(finals["home_score"], errors="coerce")
    else:
        finals["home_pts"] = np.nan

    if "visitor_pts" in finals.columns:
        finals["visitor_pts"] = pd.to_numeric(finals["visitor_pts"], errors="coerce")
    elif "visitor_score" in finals.columns:
        finals["visitor_pts"] = pd.to_numeric(finals["visitor_score"], errors="coerce")
    else:
        finals["visitor_pts"] = np.nan

    rows = []
    for path in _iter_smart_sim_json_for_day(ds):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        home = str(obj.get("home") or "").strip().upper()
        away = str(obj.get("away") or "").strip().upper()
        score = obj.get("score") or {}
        market = obj.get("market") or {}

        rows.append(
            {
                "home_tri": home,
                "away_tri": away,
                "p_home_win": _safe_float(score.get("p_home_win")),
                "p_home_cover": _safe_float(score.get("p_home_cover")),
                "p_total_over": _safe_float(score.get("p_total_over")),
                "sim_margin_mean": _safe_float(score.get("margin_mean")),
                "sim_total_mean": _safe_float(score.get("total_mean")),
                "market_home_spread": _safe_float(market.get("market_home_spread")),
                "market_total": _safe_float(market.get("market_total")),
            }
        )

    if not rows:
        return {"n_games": 0}

    sim = pd.DataFrame(rows)
    sim["home_tri"] = sim["home_tri"].astype(str).str.strip().str.upper()
    sim["away_tri"] = sim["away_tri"].astype(str).str.strip().str.upper()
    sim = sim[(sim["home_tri"] != "") & (sim["away_tri"] != "")]

    finals["home_tri"] = finals["home_tri"].astype(str).str.strip().str.upper()
    finals["away_tri"] = finals["away_tri"].astype(str).str.strip().str.upper()
    finals = finals[(finals["home_tri"] != "") & (finals["away_tri"] != "")]

    m = sim.merge(finals, on=["home_tri", "away_tri"], how="inner")
    if m.empty:
        return {"n_games": 0}

    m["act_margin"] = m["home_pts"] - m["visitor_pts"]
    m["act_total"] = m["home_pts"] + m["visitor_pts"]
    m["act_home_win"] = (m["act_margin"] > 0).astype(int)

    out: dict[str, object] = {"n_games": int(len(m))}

    out["home_win_brier"] = brier_score(m["p_home_win"], m["act_home_win"])
    out["home_win_logloss"] = log_loss(m["p_home_win"], m["act_home_win"])

    # Spread/Total probabilities if lines exist
    line = pd.to_numeric(m["market_home_spread"], errors="coerce")
    if not line.isna().all():
        cover_y = (m["act_margin"] + line > 0).astype(float)
        push = (m["act_margin"] + line == 0)
        mask = (~push) & (~m["p_home_cover"].isna()) & (~line.isna())
        if mask.sum() > 0:
            out["home_cover_brier"] = brier_score(m.loc[mask, "p_home_cover"], cover_y.loc[mask])
            out["home_cover_logloss"] = log_loss(m.loc[mask, "p_home_cover"], cover_y.loc[mask])
            out["n_cover"] = int(mask.sum())

    tline = pd.to_numeric(m["market_total"], errors="coerce")
    if not tline.isna().all():
        over_y = (m["act_total"] - tline > 0).astype(float)
        push = (m["act_total"] - tline == 0)
        mask = (~push) & (~m["p_total_over"].isna()) & (~tline.isna())
        if mask.sum() > 0:
            out["total_over_brier"] = brier_score(m.loc[mask, "p_total_over"], over_y.loc[mask])
            out["total_over_logloss"] = log_loss(m.loc[mask, "p_total_over"], over_y.loc[mask])
            out["n_over"] = int(mask.sum())

    out["margin_mae"] = mae(m["sim_margin_mean"], m["act_margin"])
    out["margin_rmse"] = rmse(m["sim_margin_mean"], m["act_margin"])
    out["total_mae"] = mae(m["sim_total_mean"], m["act_total"])
    out["total_rmse"] = rmse(m["sim_total_mean"], m["act_total"])

    return out


@dataclass
class SeasonEvalConfig:
    start: datetime
    end: datetime
    out_json: Path
    out_csv: Path
    include_quarters: bool = True
    include_props: bool = True
    include_smart_sim: bool = True


def run(cfg: SeasonEvalConfig) -> dict:
    name_to_tri = _team_name_to_tri_map()

    daily_rows: list[dict] = []

    for d in daterange(cfg.start, cfg.end):
        ds = d.strftime("%Y-%m-%d")
        row: dict[str, object] = {"date": ds}

        g = evaluate_games_for_day(ds, name_to_tri)
        row.update({f"games_{k}": v for k, v in g.items()})

        if cfg.include_quarters:
            q = evaluate_quarter_totals_for_day(ds)
            row.update({f"quarters_{k}": v for k, v in q.items()})

        if cfg.include_props:
            p = evaluate_props_for_day(ds)
            row.update({f"props_{k}": v for k, v in p.items()})

        if cfg.include_smart_sim:
            s = evaluate_smart_sim_for_day(ds, name_to_tri=name_to_tri)
            row.update({f"smart_sim_{k}": v for k, v in s.items()})

        daily_rows.append(row)

    daily = pd.DataFrame(daily_rows)
    cfg.out_csv.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(cfg.out_csv, index=False)

    def _weighted_avg(metric_col: str, weight_col: str) -> float:
        if metric_col not in daily.columns or weight_col not in daily.columns:
            return float("nan")
        x = pd.to_numeric(daily[metric_col], errors="coerce")
        w = pd.to_numeric(daily[weight_col], errors="coerce")
        m = (~x.isna()) & (~w.isna()) & (w > 0)
        if m.sum() == 0:
            return float("nan")
        return float((x[m] * w[m]).sum() / w[m].sum())

    summary = {
        "range": {"start": cfg.start.strftime("%Y-%m-%d"), "end": cfg.end.strftime("%Y-%m-%d")},
        "outputs": {"daily_csv": str(cfg.out_csv)},
        "games": {
            "n_games": int(pd.to_numeric(daily.get("games_n_games"), errors="coerce").fillna(0).sum()),
            "home_win_brier": _weighted_avg("games_home_win_brier", "games_n_games"),
            "home_win_logloss": _weighted_avg("games_home_win_logloss", "games_n_games"),
            "margin_mae": _weighted_avg("games_margin_mae", "games_n_games"),
            "total_mae": _weighted_avg("games_total_mae", "games_n_games"),
            "ats_acc": _weighted_avg("games_ats_acc", "games_n_ats"),
            "ou_acc": _weighted_avg("games_ou_acc", "games_n_ou"),
        },
    }

    if cfg.include_quarters:
        summary["quarters"] = {
            "n_games": int(pd.to_numeric(daily.get("quarters_n_games"), errors="coerce").fillna(0).sum()),
            "q1_total_mae": _weighted_avg("quarters_q1_total_mae", "quarters_n_games"),
            "q2_total_mae": _weighted_avg("quarters_q2_total_mae", "quarters_n_games"),
            "q3_total_mae": _weighted_avg("quarters_q3_total_mae", "quarters_n_games"),
            "q4_total_mae": _weighted_avg("quarters_q4_total_mae", "quarters_n_games"),
            "h1_total_mae": _weighted_avg("quarters_h1_total_mae", "quarters_n_games"),
            "h2_total_mae": _weighted_avg("quarters_h2_total_mae", "quarters_n_games"),
            "game_total_mae": _weighted_avg("quarters_game_total_mae", "quarters_n_games"),
        }

    if cfg.include_props:
        summary["props"] = {
            "n_rows": int(pd.to_numeric(daily.get("props_n_rows"), errors="coerce").fillna(0).sum()),
            "pts_mae": _weighted_avg("props_pts_mae", "props_n_rows"),
            "reb_mae": _weighted_avg("props_reb_mae", "props_n_rows"),
            "ast_mae": _weighted_avg("props_ast_mae", "props_n_rows"),
            "threes_mae": _weighted_avg("props_threes_mae", "props_n_rows"),
            "pra_mae": _weighted_avg("props_pra_mae", "props_n_rows"),
        }

    if cfg.include_smart_sim:
        summary["smart_sim"] = {
            "n_games": int(pd.to_numeric(daily.get("smart_sim_n_games"), errors="coerce").fillna(0).sum()),
            "home_win_brier": _weighted_avg("smart_sim_home_win_brier", "smart_sim_n_games"),
            "home_win_logloss": _weighted_avg("smart_sim_home_win_logloss", "smart_sim_n_games"),
            "home_cover_brier": _weighted_avg("smart_sim_home_cover_brier", "smart_sim_n_cover"),
            "total_over_brier": _weighted_avg("smart_sim_total_over_brier", "smart_sim_n_over"),
            "margin_mae": _weighted_avg("smart_sim_margin_mae", "smart_sim_n_games"),
            "total_mae": _weighted_avg("smart_sim_total_mae", "smart_sim_n_games"),
        }

    cfg.out_json.parent.mkdir(parents=True, exist_ok=True)
    cfg.out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["outputs"]["summary_json"] = str(cfg.out_json)

    return summary


def main():
    ap = argparse.ArgumentParser(description="Season-to-date evaluator (games + quarter totals + props + SmartSim)")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--no-quarters", action="store_true", help="Skip quarter/half totals evaluation")
    ap.add_argument("--no-props", action="store_true", help="Skip props evaluation")
    ap.add_argument("--no-smart-sim", action="store_true", help="Skip SmartSim JSON evaluation")
    ap.add_argument("--out-json", default=None, help="Output JSON summary path")
    ap.add_argument("--out-csv", default=None, help="Output daily CSV path")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    out_json = Path(args.out_json) if args.out_json else (PROCESSED / f"eval_season_to_date_{args.start}_{args.end}.json")
    out_csv = Path(args.out_csv) if args.out_csv else (PROCESSED / f"eval_season_daily_{args.start}_{args.end}.csv")

    cfg = SeasonEvalConfig(
        start=start,
        end=end,
        out_json=out_json,
        out_csv=out_csv,
        include_quarters=(not args.no_quarters),
        include_props=(not args.no_props),
        include_smart_sim=(not args.no_smart_sim),
    )

    summary = run(cfg)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
