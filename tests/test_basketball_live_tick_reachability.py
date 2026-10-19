"""The NBA and WNBA live-lens ticks are Syndicate's own (lane nba-live-tick-native, 2026-10-12).

Static checks, cheap and network-free, per league:
  * the generated package is exactly what scripts/port_basketball_live_tick.py produces (a hand edit fails here);
  * nothing in it imports the vendored app, the vendored `<league>_betting` package or the vendored tools dir;
  * the `#626`(e) klass gate still WRAPS the klass re-derivation inside the ported tick (the vendored-side test,
    tests/test_live_lens_tick_klass_gate.py, only reads the vendor files);
  * the four routes the tick calls through `app.test_client()` are registered on the port's private app;
  * `syndicate/features/<league>/live_lens.py` calls the port, not the vendored app.
"""
from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEAGUES = ("nba", "wnba")
ROUTES = {"/api/live_lens_tuning", "/api/live_lines", "/api/live_pbp_stats", "/api/live_player_lens"}


def _pkg_dir(league: str) -> Path:
    return ROOT / "syndicate" / "features" / league / "live_tick"


def test_generated_packages_match_generator():
    # WNBA only: the NBA package is frozen source (lane nba-vendor-deletion-prep).
    if not (ROOT / "vendor" / "wnba_betting_repo" / "app.py").exists():
        pytest.skip("vendor tree removed: nothing to regenerate from")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "port_basketball_live_tick.py"), "--league", "wnba", "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("league", LEAGUES)
def test_port_imports_nothing_vendored(league):
    bad = []
    files = sorted(_pkg_dir(league).glob("*.py"))
    assert len(files) >= 6, files
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module or ""]
            for m in mods:
                if m.split(".")[0] in {"vendor", "nba_betting", "wnba_betting", "daily_live_lens_audit"}:
                    bad.append(f"{path.name}:{node.lineno} {m}")
    assert not bad, bad


@pytest.mark.parametrize("league", LEAGUES)
def test_klass_gate_wraps_the_rederivation_in_the_port(league):
    tree = ast.parse((_pkg_dir(league) / "tick.py").read_text(encoding="utf-8"))
    tick = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_live_lens_tick_payload")
    gate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_tick_prop_klass_line_gate")
    ns: dict = {}
    exec(compile(ast.Module(body=[gate], type_ignores=[]), "gate", "exec"), ns)  # noqa: S102 -- own repo source
    assert ns["_tick_prop_klass_line_gate"]("BET", "model") == "NONE"
    assert ns["_tick_prop_klass_line_gate"]("BET", "oddsapi") == "BET"
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_tick_prop_klass_line_gate"
        and n.args and isinstance(n.args[0], ast.Call) and isinstance(n.args[0].func, ast.Name) and n.args[0].func.id == "_klass"
        for n in ast.walk(tick)
    )


@pytest.mark.parametrize("league", LEAGUES)
def test_test_client_routes_are_registered_on_the_private_app(league):
    tick = importlib.import_module(f"syndicate.features.{league}.live_tick.tick")
    rules = {r.rule for r in tick.app.url_map.iter_rules()}
    called = set()
    for node in ast.walk(ast.parse((_pkg_dir(league) / "tick.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == "_live_lens_tick_payload":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.startswith("/api/"):
                    called.add(sub.value.split("?")[0])
                if isinstance(sub, ast.JoinedStr) and sub.values and isinstance(sub.values[0], ast.Constant) and str(sub.values[0].value).startswith("/api/"):
                    called.add(str(sub.values[0].value).split("?")[0])
    assert called == ROUTES, called
    assert called <= rules, called - rules


@pytest.mark.parametrize("league", LEAGUES)
def test_live_lens_calls_the_port_not_the_vendored_app(league, monkeypatch):
    live_lens = importlib.import_module(f"syndicate.features.{league}.live_lens")
    tick = importlib.import_module(f"syndicate.features.{league}.live_tick.tick")
    src = Path(live_lens.__file__).read_text(encoding="utf-8")
    assert f"vendor.{league}_betting_repo" not in src
    seen = []
    monkeypatch.setattr(tick, "_live_lens_tick_payload", lambda d: seen.append(d) or {"ok": True, "date": d})
    run = getattr(live_lens, f"_run_{league}_live_lens_tick")
    assert run("2026-10-12") == {"ok": True, "date": "2026-10-12"}
    assert seen == ["2026-10-12"]
