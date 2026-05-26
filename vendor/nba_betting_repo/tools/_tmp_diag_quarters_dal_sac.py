import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.nba_betting.sim.quarters import (
    GameInputs,
    TeamContext,
    _adjustments,
    _apply_totals_calibration,
    _quarter_splits_for_team,
    _safe_float,
    simulate_quarters,
)
from src.nba_betting.config import paths


def main() -> None:
    print("simulate_quarters_code_location")
    try:
        c = simulate_quarters.__code__
        print({"filename": c.co_filename, "firstlineno": c.co_firstlineno})
    except Exception as e:
        print({"error": str(e)})

    obj = json.loads(
        Path("data/processed/smart_sim_2026-02-26_DAL_SAC.json").read_text(encoding="utf-8")
    )

    print("paths")
    print({"data_processed": str(paths.data_processed)})
    try:
        fps = sorted([p.name for p in paths.data_processed.glob('calibration_totals_*.json')])
        print({"calibration_totals_files": fps, "count": len(fps)})
    except Exception as e:
        print({"calibration_totals_files_error": str(e)})
    pri = obj["context"]["team_advanced_priors"]
    h = pri["home"]
    a = pri["away"]

    home = TeamContext(
        team=obj["home"],
        pace=h["pace"],
        off_rating=h["off_rtg"],
        def_rating=h["def_rtg"],
        injuries_out=obj["context"].get("home_injuries_out", 0),
        back_to_back=obj["context"].get("home_b2b", False),
    )
    away = TeamContext(
        team=obj["away"],
        pace=a["pace"],
        off_rating=a["off_rtg"],
        def_rating=a["def_rtg"],
        injuries_out=obj["context"].get("away_injuries_out", 0),
        back_to_back=obj["context"].get("away_b2b", False),
    )

    pace = float(np.mean([_safe_float(home.pace, 98.0), _safe_float(away.pace, 98.0)]))
    b2b_drag = (1.0 if home.back_to_back else 0.0) + (1.0 if away.back_to_back else 0.0)
    inj_drag = 0.3 * max(0, int(home.injuries_out or 0)) + 0.3 * max(
        0, int(away.injuries_out or 0)
    )
    pace = max(90.0, pace - b2b_drag - inj_drag)

    LEAGUE_AVG_RATING = 112.0

    def clip_rating(x: float, lo: float = 95.0, hi: float = 130.0) -> float:
        return float(max(lo, min(hi, x)))

    home_off = float(home.off_rating)
    away_off = float(away.off_rating)
    home_def = float(home.def_rating)
    away_def = float(away.def_rating)

    home_eff = clip_rating(home_off - (away_def - LEAGUE_AVG_RATING))
    away_eff = clip_rating(away_off - (home_def - LEAGUE_AVG_RATING))

    home_adj = float(_adjustments(home))
    away_adj = float(_adjustments(away))

    home_mu = max(70.0, (home_eff / 100.0) * pace) + home_adj
    away_mu = max(70.0, (away_eff / 100.0) * pace) + away_adj

    try:
        cal_home_mu, cal_away_mu, q_biases = _apply_totals_calibration(
            obj["date"], obj["home"], obj["away"], home_mu, away_mu
        )
        print("totals_calibration")
        print(
            {
                "pre_total": float(home_mu + away_mu),
                "post_total": float(cal_home_mu + cal_away_mu),
                "delta_total": float((cal_home_mu + cal_away_mu) - (home_mu + away_mu)),
                "delta_home": float(cal_home_mu - home_mu),
                "delta_away": float(cal_away_mu - away_mu),
                "q_biases": q_biases,
            }
        )
    except Exception as e:
        print("totals_calibration_error")
        print({"error": str(e)})

    home_splits = _quarter_splits_for_team(home.team, is_home=True)
    away_splits = _quarter_splits_for_team(away.team, is_home=False)
    q_means = []
    for qi in range(1, 5):
        h_mu_q = float(home_splits[qi - 1]) * float(home_mu)
        a_mu_q = float(away_splits[qi - 1]) * float(away_mu)
        q_means.append((h_mu_q, a_mu_q))
    sum_mu = float(sum((h + a) for (h, a) in q_means))
    sf_raw = float((home_mu + away_mu) / max(1e-9, sum_mu))
    sf_clamped = float(max(0.95, min(1.05, sf_raw)))

    print("inputs")
    print(
        {
            "home_pace": home.pace,
            "away_pace": away.pace,
            "pace_used": pace,
            "home_off": home_off,
            "away_off": away_off,
            "home_def": home_def,
            "away_def": away_def,
            "home_eff": home_eff,
            "away_eff": away_eff,
            "home_adj": home_adj,
            "away_adj": away_adj,
            "pre_total_mu": home_mu + away_mu,
            "home_splits": home_splits,
            "away_splits": away_splits,
            "home_splits_sum": float(sum(home_splits)),
            "away_splits_sum": float(sum(away_splits)),
            "q_means_sum_mu": sum_mu,
            "sf_raw": sf_raw,
            "sf_clamped": sf_clamped,
        }
    )

    inp = GameInputs(date=obj["date"], home=home, away=away, market_total=None, market_home_spread=None)
    out = simulate_quarters(inp, n_samples=2000)
    det_home_mu = float(sum(float(q.home_pts_mu) for q in (out.quarters or [])))
    det_away_mu = float(sum(float(q.away_pts_mu) for q in (out.quarters or [])))
    det_total_mu = float(
        sum(float(q.home_pts_mu) + float(q.away_pts_mu) for q in (out.quarters or []))
    )
    print("simulate_quarters")
    print(
        {
            "final_total_mu": out.final_total_mu,
            "det_total_mu_from_quarters": det_total_mu,
            "det_home_mu_from_quarters": det_home_mu,
            "det_away_mu_from_quarters": det_away_mu,
            "q1_corr": (float(out.quarters[0].corr) if out.quarters else None),
            "final_margin_mu": out.final_margin_mu,
            "final_total_sigma": out.final_total_sigma,
        }
    )


if __name__ == "__main__":
    main()
