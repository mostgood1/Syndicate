"""The pregame pace injury drag follows nba_sim_total_inputs.json skip_outs_penalties (lane
basketball-scenario-calibration, round 2 R2-d, pre-registered 42e086a1). Absent key (production today) = unchanged."""
from __future__ import annotations

import json

from syndicate.features.basketball_engine.orchestrator import smart_sim
from syndicate.features.basketball_engine.orchestrator.runtime import OrchestratorEnv


def _orch(tmp_path, league="nba"):
    return OrchestratorEnv.for_processed_root(tmp_path, league)


def test_absent_file_keeps_the_drag(tmp_path):
    assert smart_sim._pace_injury_drag(_orch(tmp_path), 5, 3) == 0.3 * 5 + 0.3 * 3


def test_skip_def_only_keeps_the_drag(tmp_path):
    (tmp_path / "nba_sim_total_inputs.json").write_text(json.dumps({"skip_def_subtraction": True}))
    assert smart_sim._pace_injury_drag(_orch(tmp_path), 5, 3) == 0.3 * 5 + 0.3 * 3


def test_skip_outs_removes_the_drag(tmp_path):
    (tmp_path / "nba_sim_total_inputs.json").write_text(json.dumps({"skip_def_subtraction": True, "skip_outs_penalties": True}))
    assert smart_sim._pace_injury_drag(_orch(tmp_path), 5, 3) == 0.0


def test_wnba_ignores_the_nba_file(tmp_path):
    (tmp_path / "nba_sim_total_inputs.json").write_text(json.dumps({"skip_outs_penalties": True}))
    assert smart_sim._pace_injury_drag(_orch(tmp_path, "wnba"), 2, 1) == 0.3 * 2 + 0.3 * 1
