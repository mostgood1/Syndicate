"""WNBA raw game total: the calibration file is produced and reaches the quarters step (lane wnba-game-total-level).

The smart sim's `_apply_totals_calibration_local` read `calibration_totals_*.json` and
nothing wrote it; the raw game total carried the game model's 2026 level error (-11.6
pts). And `_simulate_quarters_local` subtracted the opponent's defense from an offensive
rating that was itself derived from predicted points.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

_SPEC = importlib.util.spec_from_file_location("build_wnba_totals_calibration", Path(__file__).resolve().parents[1] / "scripts" / "build_wnba_totals_calibration.py")
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


def _games(n: int = 30, resid: float = 10.0, start: str = "2026-08-01") -> pd.DataFrame:
    days = pd.date_range(start, periods=n, freq="D")
    teams = ["LVA", "IND", "NYL", "SEA", "MIN", "PHX"]
    rows = []
    for i, d in enumerate(days):
        h, a = teams[i % 6], teams[(i + 1) % 6]
        rows.append({"date": d, "home_team": h, "visitor_team": a, "pred_total": 162.0, "pred_margin": 2.0,
                     "home_pts": 82.0 + resid / 2, "visitor_pts": 80.0 + resid / 2})
    return pd.DataFrame(rows)


def test_global_bias_is_the_recent_residual_and_team_terms_are_shrunk():
    terms = builder.calibration_terms(_games(resid=10.0), slate_date="2026-08-31")
    assert terms["global"]["game_total_bias"] == pytest.approx(10.0)
    assert terms["meta"]["window"] == "14d" and terms["meta"]["n_window"] == 14
    # Every team scored exactly its share once the global bias is in: nothing left to attribute.
    assert all(abs(v) < 1e-9 for v in terms["team"].values())


def test_only_games_before_the_slate_count_and_thin_seasons_write_nothing():
    g = _games(resid=10.0)
    g.loc[g["date"] >= "2026-08-25", ["home_pts", "visitor_pts"]] = [200.0, 200.0]
    early = builder.calibration_terms(g, slate_date="2026-08-25")
    assert early["global"]["game_total_bias"] == pytest.approx(10.0)
    assert builder.calibration_terms(_games(n=5), slate_date="2026-09-30") == {}


def test_team_term_is_the_teams_residual_over_games_plus_prior():
    g = _games(resid=0.0)
    g.loc[g["home_team"] == "LVA", "home_pts"] += 6.0
    terms = builder.calibration_terms(g, slate_date="2026-08-31")
    lva = g[(g["home_team"] == "LVA") | (g["visitor_team"] == "LVA")]
    gb = terms["global"]["game_total_bias"]
    assert terms["team"]["LVA"] > 0.5 and terms["team"]["LVA"] > max(v for k, v in terms["team"].items() if k != "LVA")
    assert terms["team"]["LVA"] <= 6.0 * (g["home_team"] == "LVA").sum() / (len(lva) + 20.0) + 1e-6 + abs(gb)


def _inputs(date: str, from_points: bool, home_def: float = 101.5, away_def: float = 106.0) -> sim.GameInputsLocal:
    h = sim.TeamContextLocal(team="LVA", pace=84.0, off_rating=104.0, def_rating=home_def, off_rating_from_points=from_points)
    a = sim.TeamContextLocal(team="IND", pace=84.0, off_rating=100.0, def_rating=away_def, off_rating_from_points=from_points)
    return sim.GameInputsLocal(date=date, home=h, away=a)


def _raw_total(root: Path, inp: sim.GameInputsLocal) -> float:
    league = sim._league_for_code_local("wnba")
    q = sim._simulate_quarters_local(processed_root=root, inp=inp, league=league, n_samples=200, anchor_policy=sim._market_anchor_policy_local("off"))
    return float((q.market_anchor or {}).get("model_total_raw", q.final_total_mu))


def test_reachability_the_calibration_file_moves_the_raw_total(tmp_path):
    off = _raw_total(tmp_path, _inputs("2026-10-01", True))
    (tmp_path / "calibration_totals_2026-09-30.json").write_text(json.dumps({"global": {"game_total_bias": 11.0}, "team": {"LVA": 1.0, "IND": 4.0}}))
    sim._TOTALS_CALIBRATION_CACHE_LOCAL.clear()
    sim._TOTALS_CALIBRATION_INDEX_LOCAL.clear()
    on = _raw_total(tmp_path, _inputs("2026-10-01", True))
    assert on - off == pytest.approx(11.0 + 1.0 + 4.0, abs=1e-6)


def test_points_derived_rating_gets_no_second_defense_adjustment(tmp_path):
    pace = 84.0
    with_def = _raw_total(tmp_path, _inputs("2026-10-01", False))
    from_points = _raw_total(tmp_path, _inputs("2026-10-01", True))
    assert from_points == pytest.approx((104.0 + 100.0) / 100.0 * pace, abs=1e-6)
    # away def 106 vs baseline 101.5 used to cost the home side 4.5 rating points (~3.8 pts here)
    assert with_def < from_points - 3.0
    assert np.isfinite(with_def)
