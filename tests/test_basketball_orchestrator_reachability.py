"""Plan P6: production reaches Syndicate's orchestrator, and no vendored SIM module on the way.

Reachability before correctness (model engine standard). Each test here can fail; the ones that check a
switch prove off != on.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import subprocess
import sys
from pathlib import Path

import pytest

from syndicate.features.basketball_engine import orchestrator as orch_pkg
from syndicate.features.basketball_engine.orchestrator import hooks, runtime, smart_sim as native_smart_sim, view
from syndicate.features.shared import basketball_props_smart_sim as bridge

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = Path(bridge.__file__)


def test_production_worker_call_reaches_the_native_orchestrator(tmp_path, monkeypatch):
    """`_call_source_simulate_smart_game_local` (what `_smart_sim_worker_run_local` calls per game) runs the
    native `simulate_smart_game` with an `orch` for the right root and league."""
    seen = {}

    def sentinel(*, orch, date_str, home_tri, away_tri, **_):
        seen.update(orch=orch, date=date_str)
        return {"players": {"home": [], "away": []}}

    monkeypatch.setattr(orch_pkg, "simulate_smart_game", sentinel)
    bridge._call_source_simulate_smart_game_local(
        processed_root=tmp_path, league_code="wnba", kwargs={"date_str": "2026-10-09", "home_tri": "LVA", "away_tri": "GSV", "processed_root": tmp_path}
    )
    assert seen["date"] == "2026-10-09"
    assert seen["orch"].paths.data_processed == tmp_path
    assert seen["orch"].league is runtime.WNBA


def test_no_vendored_sim_module_is_imported_by_the_production_path():
    """A FRESH interpreter imports the bridge and the orchestrator, builds a module view and resolves every
    hook: no `nba_betting` / `wnba_betting` module may load. The pre-P6 bridge failed this (it imported
    `<pkg>.sim.smart_sim`, which imports `<pkg>.sim.events`)."""
    code = (
        "import sys, tempfile, pathlib\n"
        "from syndicate.features.shared import basketball_props_smart_sim as b\n"
        "from syndicate.features.basketball_engine.orchestrator import OrchestratorEnv, module_view, hooks\n"
        "for lg in ('nba', 'wnba'):\n"
        "    v = b._build_local_smart_sim_module(processed_root=pathlib.Path(tempfile.mkdtemp()), league_code=lg)\n"
        "    [getattr(v, n) for n in hooks.HOOK_NAMES]\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('nba_betting', 'wnba_betting'))\n"
        "print('VENDORED', bad)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "VENDORED []" in out.stdout, out.stdout[-2000:]


def test_bridge_source_imports_no_vendored_sim_module():
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in ("import_module", "__import__") and n.args:
                arg = ast.unparse(n.args[0])
                assert ".sim" not in arg, f"bridge:{n.lineno} imports {arg}"
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = (n.module or "") if isinstance(n, ast.ImportFrom) else ",".join(a.name for a in n.names)
            assert "betting.sim" not in mod and not mod.startswith("vendor"), f"bridge:{n.lineno} imports {mod}"
    for name in ("_import_real_smart_sim_module_local", "_simulate_smart_game_local", "_REAL_SMART_SIM_MODULE_CACHE_LOCAL"):
        assert not hasattr(bridge, name), f"{name} came back"


def test_the_wiring_checklist_fires_on_the_pre_p6_bridge(tmp_path, monkeypatch):
    """The checklist's wiring check is evidence only if it can fail: point it at the pre-P6 bridge (git)."""
    from scripts import basketball_orchestrator_input_checklist as chk
    from scripts import basketball_orchestrator_parity as par

    try:
        old = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{par.VENDORED_ARM_COMMIT}:{par.BRIDGE_REL}"]).decode("utf-8")
    except Exception:
        pytest.skip("git history for the pre-P6 bridge is not available here")
    fake_root = tmp_path / "root"
    (fake_root / "syndicate" / "features" / "shared").mkdir(parents=True)
    (fake_root / "syndicate" / "features" / "shared" / "basketball_props_smart_sim.py").write_text(old, encoding="utf-8")
    monkeypatch.setattr(chk, "ROOT", fake_root)
    problems = chk.wiring_check()
    assert any("imports a vendored sim module" in p for p in problems), problems
    assert any("still patches attributes" in p for p in problems), problems
    monkeypatch.setattr(chk, "ROOT", ROOT)
    assert chk.wiring_check() == []


def test_view_carries_every_name_the_ports_read():
    """Derived from the bridge's SOURCE, not from a list: every `getattr(smart_sim_module, "<name>")` and every
    `m.<name>` in `_derive_sim_minutes_local` must resolve on the view, for both leagues."""
    src = BRIDGE.read_text(encoding="utf-8")
    names = set(re.findall(r'getattr\(\s*smart_sim_module\s*,\s*"([A-Za-z_0-9]+)"', src))
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_derive_sim_minutes_local")
    names |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "m"}
    names.discard("LEAGUE")  # WNBA only, by design (test below)
    assert names, "found no names: the derivation is broken"
    for lg in ("nba", "wnba"):
        v = view.module_view(runtime.OrchestratorEnv.for_processed_root(Path("."), lg))
        missing = sorted(n for n in names if not hasattr(v, n))
        assert not missing, (lg, missing)


def test_league_only_on_the_wnba_view_as_the_forks_had_it():
    nba = view.module_view(runtime.OrchestratorEnv.for_processed_root(Path("."), "nba"))
    wnba = view.module_view(runtime.OrchestratorEnv.for_processed_root(Path("."), "wnba"))
    assert not hasattr(nba, "LEAGUE")
    assert wnba.LEAGUE.code == "wnba" and wnba.LEAGUE.regulation_team_minutes == 200.0
    # The ports then resolve the bridge's config for NBA and the fork's for WNBA.
    assert bridge._smart_sim_league_local(nba, "nba").regulation_team_minutes == 240.0
    assert bridge._smart_sim_league_local(wnba, "wnba") is wnba.LEAGUE


def test_hooks_are_the_names_the_vendored_orchestrator_called_and_smart_sim_uses_them():
    """Every hook name existed in the vendored module (so it was a real replacement) and the generated
    orchestrator binds the hook, not a body of its own."""
    wn = ast.parse((ROOT / "vendor" / "wnba_betting_repo" / "src" / "wnba_betting" / "sim" / "smart_sim.py").read_text(encoding="utf-8-sig"))
    vendored = {n.name for n in wn.body if isinstance(n, ast.FunctionDef)}
    vendored |= {a.asname or a.name for n in wn.body if isinstance(n, ast.ImportFrom) for a in n.names}
    assert set(hooks.HOOK_NAMES) <= vendored, sorted(set(hooks.HOOK_NAMES) - vendored)
    assert len(set(hooks.HOOK_NAMES)) == 29
    gen = ast.parse(Path(native_smart_sim.__file__).read_text(encoding="utf-8"))
    defined = {n.name for n in gen.body if isinstance(n, ast.FunctionDef)}
    assert not (defined & set(hooks.HOOK_NAMES)), sorted(defined & set(hooks.HOOK_NAMES))
    for name in hooks.HOOK_NAMES:
        if hasattr(native_smart_sim, name):
            assert getattr(native_smart_sim, name) is getattr(hooks, name), name


def test_league_constants_pin_to_the_engines_league_params():
    from syndicate.features.basketball_engine.league import league_params

    for code, ol in (("nba", runtime.NBA), ("wnba", runtime.WNBA)):
        lp = league_params(code)
        assert ol.regulation_period_seconds == lp.regulation_period_seconds
        assert ol.overtime_period_seconds == lp.overtime_period_seconds
        assert ol.regulation_team_minutes == lp.regulation_team_minutes


def test_wnba_constants_equal_the_forks_league_config():
    from syndicate.features.basketball_engine.orchestrator.league_config import LEAGUE

    for f in dataclasses.fields(runtime.OrchestratorLeague):
        if hasattr(LEAGUE, f.name):
            assert getattr(runtime.WNBA, f.name) == getattr(LEAGUE, f.name), f.name
    assert runtime.WNBA.poss_clip_lo == LEAGUE.baseline_pace - 8.0 and runtime.WNBA.poss_clip_hi == LEAGUE.baseline_pace + 10.0


def test_ncaab_is_a_named_refusal_not_nba_numbers():
    with pytest.raises(NotImplementedError, match="ncaab"):
        runtime.orchestrator_league("ncaab")


def test_stamp_switch_off_is_not_on():
    players = {"home": [{"player_name": "A"}], "away": [{"player_name": "B"}]}
    off = native_smart_sim._stamp_team_opponent(players, home_tri="lva", away_tri="gsv", enabled=False)
    assert off is players and "team" not in off["home"][0]
    on = native_smart_sim._stamp_team_opponent({"home": [{"player_name": "A"}], "away": []}, home_tri="lva", away_tri="gsv", enabled=True)
    assert on["home"][0]["team"] == "LVA" and on["home"][0]["opponent"] == "GSV"


def test_the_generated_modules_match_the_port_script():
    """The orchestrator is regenerated from the vendored source by scripts/port_basketball_orchestrator.py.
    Until a deliberate native edit lands (then delete this test and say so in the module header), the files
    must equal the generator's output, so every difference from the vendored code is a recorded edit."""
    out = subprocess.run([sys.executable, "scripts/port_basketball_orchestrator.py", "--check"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
