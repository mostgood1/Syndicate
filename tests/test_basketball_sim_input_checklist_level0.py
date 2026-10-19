"""Level 0 of scripts/basketball_sim_input_checklist.py: the game call reaches the native orchestrator.

Until 2026-10-19 Level 0 called the deleted `_import_real_smart_sim_module_local` and raised
AttributeError, so the published basketball sim_input_report stopped on 2026-10-10. These pin the
replacement AND its ability to fail (model_engine_standard.md: reachability before correctness).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def checklist():
    spec = importlib.util.spec_from_file_location(
        "basketball_sim_input_checklist", REPO / "scripts" / "basketball_sim_input_checklist.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bridge_source(checklist) -> str:
    return checklist.BRIDGE_PATH.read_text(encoding="utf-8")


def test_level0_passes_on_this_checkout(checklist, monkeypatch):
    # In a full run another test may have imported a vendored module; the checklist itself runs in a fresh process.
    for name in checklist.vendored_modules_loaded(list(sys.modules)):
        monkeypatch.delitem(sys.modules, name)
    rows, alarms = checklist.level0_bridge_reachability()
    assert alarms == []
    assert {r["league"] for r in rows} == set(checklist.LEAGUES)
    for row in rows:
        assert row["verdict"] == "NATIVE ORCHESTRATOR"
        assert row["orchestrator_league"] == row["league"]
        assert row["vendored_modules_loaded"] == []


def test_wiring_check_passes_on_the_real_bridge(checklist):
    assert checklist.bridge_engine_problems(_bridge_source(checklist)) == []


def test_wiring_check_fails_without_the_orchestrator_import(checklist):
    src = _bridge_source(checklist).replace(
        f"from {checklist.ORCHESTRATOR_MODULE} import OrchestratorEnv, simulate_smart_game",
        f"from {checklist.ORCHESTRATOR_MODULE} import OrchestratorEnv",
    )
    problems = checklist.bridge_engine_problems(src)
    assert any("does not import simulate_smart_game" in p for p in problems)


def test_wiring_check_fails_when_the_engine_comes_from_a_vendored_module(checklist):
    src = _bridge_source(checklist).replace(
        f"from {checklist.ORCHESTRATOR_MODULE} import OrchestratorEnv, simulate_smart_game",
        "from syndicate.features.basketball_engine.orchestrator import OrchestratorEnv\n"
        "    from nba_betting.sim.smart_sim import simulate_smart_game",
    )
    assert checklist.bridge_engine_problems(src)


def test_wiring_check_fails_when_the_call_function_is_gone(checklist):
    src = _bridge_source(checklist).replace(
        f"def {checklist.BRIDGE_CALL_FN}(", "def _renamed_game_call(", 1
    )
    assert any("is gone" in p for p in checklist.bridge_engine_problems(src))


def test_vendored_module_check(checklist):
    assert checklist.vendored_modules_loaded(["nba_betting_extra", "syndicate.features.nba"]) == []
    assert checklist.vendored_modules_loaded(["wnba_betting", "nba_betting.sim.smart_sim", "json"]) == [
        "nba_betting.sim.smart_sim", "wnba_betting",
    ]


def test_level0_alarms_when_a_vendored_module_is_loaded(checklist, monkeypatch):
    monkeypatch.setitem(sys.modules, "wnba_betting", type(sys)("wnba_betting"))
    rows, alarms = checklist.level0_bridge_reachability()
    assert any(a.startswith("LEVEL 0 VENDORED") for a in alarms)
    assert all(r["verdict"] == "BROKEN" for r in rows)


def test_level0_alarms_when_a_league_falls_through_to_nba(checklist, monkeypatch):
    monkeypatch.setitem(checklist.LEAGUES, "wnbx", {})
    rows, alarms = checklist.level0_bridge_reachability()
    assert any("orchestrator_league('wnbx')" in a for a in alarms)
    assert {r["league"]: r["verdict"] for r in rows}["wnbx"] == "BROKEN"
