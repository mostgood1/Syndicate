import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

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


def _safe_float(x: Any) -> float | None:
    try:
        v = float(pd.to_numeric(x, errors="coerce"))
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _brier(p: float, y: float) -> float:
    return float((float(p) - float(y)) ** 2)


def _logloss(p: float, y: float) -> float:
    pp = float(np.clip(float(p), 1e-6, 1.0 - 1e-6))
    yy = float(y)
    return float(-(yy * math.log(pp) + (1.0 - yy) * math.log(1.0 - pp)))


def _team_name_to_tri_map() -> dict[str, str]:
    # This schedule is used for mapping full team names to tricodes.
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


def _iter_smart_sim_json_for_day(ds: str):
    pat = f"smart_sim_{ds}_*.json"
    for p in PROCESSED.glob(pat):
        yield p


def _load_recon_for_day(ds: str, name_to_tri: dict[str, str] | None) -> pd.DataFrame:
    fp = PROCESSED / f"recon_quarters_{ds}.csv"
    df = _load_csv(fp)
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    # Normalize ids and names
    if "game_id" in out.columns:
        out["game_id"] = out["game_id"].astype(str).str.strip()

    if "home_team" in out.columns:
        out["home_team"] = out["home_team"].astype(str).str.strip()
    if "visitor_team" in out.columns:
        out["visitor_team"] = out["visitor_team"].astype(str).str.strip()

    # If file already has tricodes, use them; otherwise map from schedule.
    if "home_tri" in out.columns:
        out["home_tri"] = out["home_tri"].astype(str).str.strip().str.upper()
    if "away_tri" in out.columns:
        out["away_tri"] = out["away_tri"].astype(str).str.strip().str.upper()

    if ("home_tri" not in out.columns or "away_tri" not in out.columns) and name_to_tri:
        try:
            out["home_tri"] = out.get("home_team", "").astype(str).str.upper().map(lambda s: name_to_tri.get(s.upper().strip(), ""))
            out["away_tri"] = out.get("visitor_team", "").astype(str).str.upper().map(lambda s: name_to_tri.get(s.upper().strip(), ""))
        except Exception:
            out["home_tri"] = ""
            out["away_tri"] = ""
    else:
        if "home_tri" not in out.columns:
            out["home_tri"] = ""
        if "away_tri" not in out.columns:
            out["away_tri"] = ""

    # Ensure numeric quarter columns
    num_cols = [
        # Schema A: per-team quarter points
        "home_q1",
        "home_q2",
        "home_q3",
        "home_q4",
        "visitor_q1",
        "visitor_q2",
        "visitor_q3",
        "visitor_q4",
        "home_h1",
        "home_h2",
        "visitor_h1",
        "visitor_h2",
        "home_pts",
        "visitor_pts",
        "total_points",
        "margin",
        # Schema B: totals-only
        "actual_q1_total",
        "actual_q2_total",
        "actual_q3_total",
        "actual_q4_total",
        "actual_h1_total",
        "actual_h2_total",
        "actual_game_total",
    ]
    for c in num_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    return out


def evaluate_smart_sim_quarters_for_day(
    ds: str,
    name_to_tri: dict[str, str] | None = None,
    only_pbp: Optional[bool] = None,
) -> pd.DataFrame:
    recon = _load_recon_for_day(ds, name_to_tri)
    if recon is None or recon.empty:
        return pd.DataFrame()

    # Build a lookup by game_id (best), and fallback by (home_tri, away_tri)
    by_gid = {}
    if "game_id" in recon.columns:
        for _, r in recon.iterrows():
            gid = str(r.get("game_id") or "").strip()
            if gid:
                by_gid[gid] = r

    by_tri = {}
    try:
        for _, r in recon.iterrows():
            ht = str(r.get("home_tri") or "").strip().upper()
            at = str(r.get("away_tri") or "").strip().upper()
            if ht and at:
                by_tri[(ht, at)] = r
    except Exception:
        by_tri = {}

    rows: list[dict[str, Any]] = []

    for path in _iter_smart_sim_json_for_day(ds):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        home = str(obj.get("home") or "").strip().upper()
        away = str(obj.get("away") or "").strip().upper()
        gid = str(obj.get("game_id") or "").strip()

        mode = obj.get("mode") or {}
        use_pbp = bool(mode.get("use_pbp"))
        if only_pbp is True and not use_pbp:
            continue
        if only_pbp is False and use_pbp:
            continue

        rec = None
        if gid and gid in by_gid:
            rec = by_gid[gid]
        elif (home, away) in by_tri:
            rec = by_tri[(home, away)]

        if rec is None:
            continue

        periods = obj.get("periods") or {}

        base: dict[str, Any] = {
            "date": ds,
            "home_tri": home,
            "away_tri": away,
            "game_id": gid or str(rec.get("game_id") or "").strip(),
            "use_pbp": bool(use_pbp),
        }

        # Actuals (support both recon schemas)
        def _actual_period(rec_row: Any, per: str) -> dict[str, float | None]:
            # Schema A: per-team quarter points
            if per in ("q1", "q2", "q3", "q4") and ("home_q1" in rec_row.index):
                hh = _safe_float(rec_row.get(f"home_{per}"))
                aa = _safe_float(rec_row.get(f"visitor_{per}"))
                return {
                    "home": hh,
                    "away": aa,
                    "total": (hh + aa) if (hh is not None and aa is not None) else None,
                    "margin": (hh - aa) if (hh is not None and aa is not None) else None,
                }
            if per in ("h1", "h2") and ("home_h1" in rec_row.index):
                hh = _safe_float(rec_row.get(f"home_{per}"))
                aa = _safe_float(rec_row.get(f"visitor_{per}"))
                return {
                    "home": hh,
                    "away": aa,
                    "total": (hh + aa) if (hh is not None and aa is not None) else None,
                    "margin": (hh - aa) if (hh is not None and aa is not None) else None,
                }

            # Schema B: totals-only
            key = f"actual_{per}_total"
            tt = _safe_float(rec_row.get(key)) if key in rec_row.index else None
            return {"home": None, "away": None, "total": tt, "margin": None}

        act = {per: _actual_period(rec, per) for per in ("q1", "q2", "q3", "q4", "h1", "h2")}

        # Score each period
        row = dict(base)
        for per in ("q1", "q2", "q3", "q4", "h1", "h2"):
            p = periods.get(per) or {}
            ph = _safe_float(p.get("home_mean"))
            pa = _safe_float(p.get("away_mean"))
            pt = _safe_float(p.get("total_mean"))
            pm = _safe_float(p.get("margin_mean"))

            ah = act.get(per, {}).get("home")
            aa = act.get(per, {}).get("away")
            at = act.get(per, {}).get("total")
            am = act.get(per, {}).get("margin")

            row[f"{per}_home_pred"] = ph
            row[f"{per}_away_pred"] = pa
            row[f"{per}_total_pred"] = pt
            row[f"{per}_margin_pred"] = pm

            row[f"{per}_home_act"] = ah
            row[f"{per}_away_act"] = aa
            row[f"{per}_total_act"] = at
            row[f"{per}_margin_act"] = am

            row[f"{per}_home_abs_err"] = abs(ph - ah) if (ph is not None and ah is not None) else None
            row[f"{per}_away_abs_err"] = abs(pa - aa) if (pa is not None and aa is not None) else None
            row[f"{per}_total_abs_err"] = abs(pt - at) if (pt is not None and at is not None) else None
            row[f"{per}_margin_abs_err"] = abs(pm - am) if (pm is not None and am is not None) else None

            # Brier/logloss for totals O/U when line exists
            tline = _safe_float(p.get("market_total"))
            p_over = _safe_float(p.get("p_total_over"))
            if tline is not None and p_over is not None and at is not None:
                if float(at) != float(tline):
                    y = 1.0 if float(at) > float(tline) else 0.0
                    row[f"{per}_over_y"] = y
                    row[f"{per}_over_p"] = float(p_over)
                    row[f"{per}_over_brier"] = _brier(float(p_over), y)
                    row[f"{per}_over_logloss"] = _logloss(float(p_over), y)
                    row[f"{per}_over_n"] = 1
                else:
                    row[f"{per}_over_n"] = 0
            else:
                row[f"{per}_over_n"] = 0

            # Brier/logloss for spreads when line exists
            sline = _safe_float(p.get("market_home_spread"))
            p_cover = _safe_float(p.get("p_home_cover"))
            if sline is not None and p_cover is not None and am is not None:
                if float(am + sline) != 0.0:
                    y = 1.0 if float(am + sline) > 0.0 else 0.0
                    row[f"{per}_cover_y"] = y
                    row[f"{per}_cover_p"] = float(p_cover)
                    row[f"{per}_cover_brier"] = _brier(float(p_cover), y)
                    row[f"{per}_cover_logloss"] = _logloss(float(p_cover), y)
                    row[f"{per}_cover_n"] = 1
                else:
                    row[f"{per}_cover_n"] = 0
            else:
                row[f"{per}_cover_n"] = 0

        rows.append(row)

    return pd.DataFrame(rows)


@dataclass
class RangeEvalConfig:
    start: datetime
    end: datetime
    out_csv: Path
    out_json: Path
    only_pbp: Optional[bool] = None


def run(cfg: RangeEvalConfig) -> dict[str, Any]:
    name_to_tri = _team_name_to_tri_map()

    all_rows: list[pd.DataFrame] = []
    for d in daterange(cfg.start, cfg.end):
        ds = d.strftime("%Y-%m-%d")
        df = evaluate_smart_sim_quarters_for_day(ds, name_to_tri=name_to_tri, only_pbp=cfg.only_pbp)
        if df is not None and not df.empty:
            all_rows.append(df)

    out_df = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    cfg.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(cfg.out_csv, index=False)

    def _mean(col: str) -> float:
        if out_df.empty or col not in out_df.columns:
            return float("nan")
        x = pd.to_numeric(out_df[col], errors="coerce")
        if x.isna().all():
            return float("nan")
        return float(x.mean(skipna=True))

    def _weighted_avg(metric_col: str, weight_col: str) -> float:
        if out_df.empty or metric_col not in out_df.columns or weight_col not in out_df.columns:
            return float("nan")
        x = pd.to_numeric(out_df[metric_col], errors="coerce")
        w = pd.to_numeric(out_df[weight_col], errors="coerce")
        m = (~x.isna()) & (~w.isna()) & (w > 0)
        if m.sum() == 0:
            return float("nan")
        return float((x[m] * w[m]).sum() / w[m].sum())

    summary: dict[str, Any] = {
        "range": {"start": cfg.start.strftime("%Y-%m-%d"), "end": cfg.end.strftime("%Y-%m-%d")},
        "outputs": {"csv": str(cfg.out_csv), "summary_json": str(cfg.out_json)},
        "n_games": int(len(out_df)) if not out_df.empty else 0,
        "filters": {"only_pbp": cfg.only_pbp},
        "periods": {},
    }

    for per in ("q1", "q2", "q3", "q4", "h1", "h2"):
        summary["periods"][per] = {
            "total_mae": _mean(f"{per}_total_abs_err"),
            "home_mae": _mean(f"{per}_home_abs_err"),
            "away_mae": _mean(f"{per}_away_abs_err"),
            "margin_mae": _mean(f"{per}_margin_abs_err"),
            "total_over_brier": _weighted_avg(f"{per}_over_brier", f"{per}_over_n"),
            "total_over_logloss": _weighted_avg(f"{per}_over_logloss", f"{per}_over_n"),
            "n_total_over": int(pd.to_numeric(out_df.get(f"{per}_over_n"), errors="coerce").fillna(0).sum()) if not out_df.empty else 0,
            "cover_brier": _weighted_avg(f"{per}_cover_brier", f"{per}_cover_n"),
            "cover_logloss": _weighted_avg(f"{per}_cover_logloss", f"{per}_cover_n"),
            "n_cover": int(pd.to_numeric(out_df.get(f"{per}_cover_n"), errors="coerce").fillna(0).sum()) if not out_df.empty else 0,
        }

    cfg.out_json.parent.mkdir(parents=True, exist_ok=True)
    cfg.out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest SmartSim quarter/half outputs vs recon_quarters actuals")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out-csv", default=None, help="Output CSV path")
    ap.add_argument("--out-json", default=None, help="Output JSON summary path")

    g = ap.add_mutually_exclusive_group()
    g.add_argument("--only-pbp", action="store_true", help="Only include SmartSim runs with use_pbp=true")
    g.add_argument("--only-legacy", action="store_true", help="Only include legacy SmartSim runs (use_pbp=false)")

    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    only_pbp: Optional[bool] = None
    if args.only_pbp:
        only_pbp = True
    if args.only_legacy:
        only_pbp = False

    out_csv = Path(args.out_csv) if args.out_csv else (PROCESSED / f"eval_smart_sim_quarters_{args.start}_{args.end}.csv")
    out_json = Path(args.out_json) if args.out_json else (PROCESSED / f"eval_smart_sim_quarters_{args.start}_{args.end}.json")

    cfg = RangeEvalConfig(start=start, end=end, out_csv=out_csv, out_json=out_json, only_pbp=only_pbp)
    summary = run(cfg)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
