"""NBA raw-total input switches (lane basketball-scenario-calibration, Phase 2 #1f): `nba_sim_total_inputs.json`.

Absent = today's behaviour exactly; skip_def_subtraction = the WNBA points-derived rule; skip_outs_penalties = no
injury-count pace drag and no -0.5/out adjustment. NBA only; never raises."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

PACE = 100.0


def _inputs(outs: int = 4) -> sim.GameInputsLocal:
    h = sim.TeamContextLocal(team="BOS", pace=PACE, off_rating=116.0, def_rating=114.0, injuries_out=outs)
    a = sim.TeamContextLocal(team="NYK", pace=PACE, off_rating=112.0, def_rating=115.0, injuries_out=outs)
    return sim.GameInputsLocal(date="2026-01-10", home=h, away=a)


def _anchor(root: Path, league_code: str = "nba", outs: int = 4) -> dict:
    sim._TOTALS_CALIBRATION_CACHE_LOCAL.clear()
    sim._TOTALS_CALIBRATION_INDEX_LOCAL.clear()
    q = sim._simulate_quarters_local(processed_root=root, inp=_inputs(outs), league=sim._league_for_code_local(league_code),
                                     n_samples=200, anchor_policy=sim._market_anchor_policy_local("off"))
    return dict(q.market_anchor or {})


def _switch(root: Path, **kw) -> None:
    (root / sim.NBA_TOTAL_INPUTS_FILE_LOCAL).write_text(json.dumps(kw), encoding="utf-8")


def _expected(*, def_sub: bool, outs_pen: bool, outs: int = 4) -> float:
    base = 110.6
    pace = max(PACE - 8.0, PACE - (0.6 * outs if outs_pen else 0.0))
    he = 116.0 - ((115.0 - base) if def_sub else 0.0)
    ae = 112.0 - ((114.0 - base) if def_sub else 0.0)
    adj = -0.5 * outs * 2 if outs_pen else 0.0
    return he / 100.0 * pace + ae / 100.0 * pace + adj


def test_absent_file_is_todays_formula_and_records_nothing(tmp_path):
    a = _anchor(tmp_path)
    assert a["model_total_raw"] == pytest.approx(_expected(def_sub=True, outs_pen=True), abs=1e-9)
    assert "nba_total_inputs" not in a


def test_each_switch_is_reachable_and_does_what_it_says(tmp_path):
    _switch(tmp_path, skip_def_subtraction=True)
    a = _anchor(tmp_path)
    assert a["model_total_raw"] == pytest.approx(_expected(def_sub=False, outs_pen=True), abs=1e-9)
    assert a["nba_total_inputs"] == {"skip_def_subtraction": True, "skip_outs_penalties": False}
    _switch(tmp_path, skip_outs_penalties=True)
    assert _anchor(tmp_path)["model_total_raw"] == pytest.approx(_expected(def_sub=True, outs_pen=False), abs=1e-9)
    _switch(tmp_path, skip_def_subtraction=True, skip_outs_penalties=True)
    both = _anchor(tmp_path)["model_total_raw"]
    assert both == pytest.approx((116.0 + 112.0) / 100.0 * PACE, abs=1e-9)   # = the points-derived prediction
    assert both > _expected(def_sub=True, outs_pen=True) + 9.0


def test_wnba_ignores_the_nba_file_and_a_broken_file_is_absent(tmp_path):
    _switch(tmp_path, skip_def_subtraction=True, skip_outs_penalties=True)
    wnba_on = _anchor(tmp_path, "wnba")
    (tmp_path / sim.NBA_TOTAL_INPUTS_FILE_LOCAL).unlink()
    assert _anchor(tmp_path, "wnba")["model_total_raw"] == pytest.approx(wnba_on["model_total_raw"], abs=1e-12)
    (tmp_path / sim.NBA_TOTAL_INPUTS_FILE_LOCAL).write_text("{not json", encoding="utf-8")
    a = _anchor(tmp_path)
    assert a["model_total_raw"] == pytest.approx(_expected(def_sub=True, outs_pen=True), abs=1e-9)
    assert "nba_total_inputs" not in a
