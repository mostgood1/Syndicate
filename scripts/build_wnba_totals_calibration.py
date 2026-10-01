"""Write `calibration_totals_<anchor>.json` for the WNBA smart sim's game-total model.

WHY THIS EXISTS. `basketball_props_smart_sim._apply_totals_calibration_local` reads
`calibration_totals_*.json` (a global game-total bias, clamped +/-15, and per-team terms,
clamped +/-4) and NOTHING in Syndicate wrote it -- the vendor's `calibrate-totals` command
was never wired in. The input was consumed and never populated, so the raw game total
was the vendored game model's level uncorrected. That model predicts ~162 every season
(2024 bias -0.4, 2025 -1.3) and 2026 scoring rose to ~174: bias -11.6 over 344 games, and
the live LVA-IND 2026-10-01 raw total was 157.0 against a 181.5 market.

WHAT IT COMPUTES (lane `wnba-game-total-level`). One feature build over the history before
`--date` -- the same `build_features_enhanced` + `NPUGamePredictor` that `predict-date`
runs that morning -- predicting every completed game this season. Then:
  global.game_total_bias = winsorized(5/95%) mean(actual - predicted total) over the last
      14 days (season-to-date when fewer than 8 games), clipped to +/-15;
  team[TRI] = sum(team points residual after the global bias) / (games + 20), clipped +/-4.
Walk-forward 2026, 299 games, this exact recipe: raw-total MAE 19.81 -> 15.39, bias -13.66
-> +0.09 (with the quarters step's def double count removed); vs production -3.87 per game
[CI -5.40, -2.26]. Older games are predicted with today's team stats (a mild leak the
clean per-date walk-forward showed costs nothing: -0.06 [CI -0.39, +0.30]).

The anchor is `--date` minus one day: the reader takes the newest file dated on or before
the day before the slate, so a missed run falls back to the previous day's file.

Usage: python scripts/build_wnba_totals_calibration.py --date 2026-10-01 [--force]
       (WNBA_BETTING_DATA_ROOT selects the data tree, as for every vendor command)
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOW_DAYS = 14
MIN_GAMES = 8
TEAM_PRIOR_GAMES = 20.0
GLOBAL_CLIP = 15.0
TEAM_CLIP = 4.0


def _winsor_mean(values) -> float:
    import pandas as pd

    s = pd.Series(values, dtype=float).dropna()
    if s.empty:
        return 0.0
    return float(s.clip(s.quantile(0.05), s.quantile(0.95)).mean())


def calibration_terms(games, *, slate_date) -> dict:
    """Terms from completed games with columns date, home_team, visitor_team, home_pts, visitor_pts, pred_total, pred_margin.

    `home_team` / `visitor_team` must already be tricodes. Pure: no I/O.
    """
    import numpy as np
    import pandas as pd

    g = games.copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    slate = pd.Timestamp(slate_date).normalize()
    g = g[g["date"] < slate]
    if len(g) < MIN_GAMES:
        return {}
    recent = g[g["date"] >= slate - pd.Timedelta(days=WINDOW_DAYS)]
    window = "14d"
    if len(recent) < MIN_GAMES:
        recent, window = g, "season_to_date"
    resid = recent["home_pts"] + recent["visitor_pts"] - recent["pred_total"]
    gb = float(np.clip(_winsor_mean(resid), -GLOBAL_CLIP, GLOBAL_CLIP))
    home_mu = (g["pred_total"] + gb + g["pred_margin"]) / 2.0
    away_mu = (g["pred_total"] + gb - g["pred_margin"]) / 2.0
    rr = pd.concat([
        pd.DataFrame({"team": g["home_team"], "r": g["home_pts"] - home_mu}),
        pd.DataFrame({"team": g["visitor_team"], "r": g["visitor_pts"] - away_mu}),
    ])
    team = {str(t): round(float(np.clip(x["r"].sum() / (len(x) + TEAM_PRIOR_GAMES), -TEAM_CLIP, TEAM_CLIP)), 3) for t, x in rr.groupby("team")}
    return {
        "global": {"game_total_bias": round(gb, 3)},
        "team": team,
        "meta": {
            "source": "scripts/build_wnba_totals_calibration.py",
            "method": "winsorized mean(actual - model total); team residual / (n + prior)",
            "window": window, "window_days": WINDOW_DAYS, "n_window": int(len(recent)), "n_season": int(len(g)),
            "team_prior_games": TEAM_PRIOR_GAMES, "slate_date": str(slate.date()),
            "model_mean_total": round(float(recent["pred_total"].mean()), 2),
            "actual_mean_total": round(float((recent["home_pts"] + recent["visitor_pts"]).mean()), 2),
        },
    }


def _season_predictions(slate_date: str):
    """One feature build over history before `slate_date`; predictions for this season's completed games."""
    import numpy as np
    import pandas as pd

    src = REPO_ROOT / "vendor" / "wnba_betting_repo" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import joblib
    from wnba_betting import cli
    from wnba_betting.config import paths
    from wnba_betting.features_enhanced import build_features_enhanced
    from wnba_betting.games_npu import NPUGamePredictor

    slate = pd.Timestamp(slate_date).normalize()
    hist = cli._load_prediction_feature_history()
    hist["date"] = pd.to_datetime(hist["date"]).dt.normalize()
    hist = hist[hist["home_pts"].notna() & hist["visitor_pts"].notna() & (hist["date"] < slate)].sort_values("date")
    feat_cols = joblib.load(paths.models / "feature_columns_enhanced.joblib")
    with contextlib.redirect_stdout(io.StringIO()):
        fdf = build_features_enhanced(hist, include_advanced_stats=True, include_injuries=True)
        predictor = NPUGamePredictor()
    fdf["date"] = pd.to_datetime(fdf["date"]).dt.normalize()
    part = fdf[(fdf["date"].dt.year == slate.year) & fdf["home_pts"].notna()].copy()
    if part.empty:
        return part, paths.data_processed
    for col in feat_cols:
        if col not in part.columns:
            part[col] = 0.0
    with contextlib.redirect_stdout(io.StringIO()):
        res = predictor.predict_batch(part[feat_cols].fillna(0).values.astype(np.float32), include_periods=False)
    part["pred_total"] = [float(r["totals"]) for r in res]
    part["pred_margin"] = [float(r["spread_margin"]) for r in res]
    # The reader looks teams up by the smart sim's own tricodes, so key them the same way.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local as tri
    part["home_team"] = part["home_team"].astype(str).map(tri)
    part["visitor_team"] = part["visitor_team"].astype(str).map(tri)
    return part[["date", "home_team", "visitor_team", "home_pts", "visitor_pts", "pred_total", "pred_margin"]], paths.data_processed


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--date", required=True, help="Slate date YYYY-MM-DD; the file is anchored on the day before")
    ap.add_argument("--force", action="store_true", help="Rebuild even if the anchor file already exists")
    args = ap.parse_args(argv)
    anchor = (pd.Timestamp(args.date) - pd.Timedelta(days=1)).date().isoformat()
    src = REPO_ROOT / "vendor" / "wnba_betting_repo" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from wnba_betting.config import paths

    out = Path(paths.data_processed) / f"calibration_totals_{anchor}.json"
    if out.is_file() and out.stat().st_size > 0 and not args.force:
        print(json.dumps({"status": "exists", "path": str(out)}), flush=True)
        return 0
    games, _processed = _season_predictions(args.date)
    terms = calibration_terms(games, slate_date=args.date)
    if not terms:
        print(json.dumps({"status": "skipped", "reason": "fewer than %d completed games this season" % MIN_GAMES, "n": int(len(games))}), flush=True)
        return 0
    terms["meta"]["anchor"] = anchor
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(terms, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out)
    print(json.dumps({"status": "wrote", "path": str(out), "game_total_bias": terms["global"]["game_total_bias"], **{k: terms["meta"][k] for k in ("window", "n_window", "n_season")}}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
