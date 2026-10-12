"""The NBA live-lens tick is Syndicate's own (lane nba-live-tick-native, 2026-10-12).

Static checks, cheap and network-free:
  * the generated package is exactly what scripts/port_nba_live_tick.py produces (a hand edit fails here);
  * nothing in it imports the vendored app, the vendored `nba_betting` package or the vendored tools dir;
  * the `#626`(e) klass gate still WRAPS the klass re-derivation inside the ported tick (the vendored-side test,
    tests/test_live_lens_tick_klass_gate.py, only reads the vendor files);
  * the four routes the tick calls through `app.test_client()` are registered on the port's private app;
  * `syndicate/features/nba/live_lens.py` calls the port, not the vendored app.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "syndicate" / "features" / "nba" / "live_tick"


def test_generated_package_matches_generator():
    if not (ROOT / "vendor" / "nba_betting_repo" / "app.py").exists():
        pytest.skip("vendor tree removed: nothing to regenerate from")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "port_nba_live_tick.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_port_imports_nothing_vendored():
    bad = []
    for path in sorted(PKG_DIR.glob("*.py")):
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


def test_klass_gate_wraps_the_rederivation_in_the_port():
    tree = ast.parse((PKG_DIR / "tick.py").read_text(encoding="utf-8"))
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


def test_test_client_routes_are_registered_on_the_private_app():
    from syndicate.features.nba.live_tick import tick

    rules = {r.rule for r in tick.app.url_map.iter_rules()}
    called = set()
    for node in ast.walk(ast.parse((PKG_DIR / "tick.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == "_live_lens_tick_payload":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.startswith("/api/"):
                    called.add(sub.value.split("?")[0])
                if isinstance(sub, ast.JoinedStr) and sub.values and isinstance(sub.values[0], ast.Constant) and str(sub.values[0].value).startswith("/api/"):
                    called.add(str(sub.values[0].value).split("?")[0])
    assert called == {"/api/live_lens_tuning", "/api/live_lines", "/api/live_pbp_stats", "/api/live_player_lens"}, called
    assert called <= rules, called - rules


def test_live_lens_calls_the_port_not_the_vendored_app(monkeypatch):
    from syndicate.features.nba import live_lens
    from syndicate.features.nba.live_tick import tick

    src = Path(live_lens.__file__).read_text(encoding="utf-8")
    assert "vendor.nba_betting_repo" not in src
    seen = []
    monkeypatch.setattr(tick, "_live_lens_tick_payload", lambda d: seen.append(d) or {"ok": True, "date": d})
    assert live_lens._run_nba_live_lens_tick("2026-10-12") == {"ok": True, "date": "2026-10-12"}
    assert seen == ["2026-10-12"]
