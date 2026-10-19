"""The NBA props refresh's game-input bootstrap runs Syndicate's CLI, not the vendored one (lane nba-source-cli-native).

Static and cheap:
  * the package is exactly what scripts/port_basketball_source_cli.py generates (a hand edit fails here), models included;
  * nothing in it imports the vendored package (`nba_betting`) or `vendor`;
  * its CLI registers exactly the six commands the refresh runs, and its models dir resolves to the Syndicate copy;
  * the refresh launches `python -m syndicate.features.nba.source_cli.cli` for every bootstrap step and predict-date.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "syndicate" / "features" / "nba" / "source_cli"
COMMANDS = {"fetch-schedule", "fetch", "build-features", "fetch-injuries", "export-game-cards", "predict-date"}


def test_port_imports_nothing_vendored():
    bad = []
    for path in sorted(PKG.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            bad += [f"{path.relative_to(PKG)}:{node.lineno} {m}" for m in mods if m.split(".")[0] in {"vendor", "nba_betting", "wnba_betting"}]
    assert not bad, bad


def test_cli_registers_the_six_commands_and_uses_syndicate_models():
    from syndicate.features.nba.source_cli import cli, config

    assert set(cli.cli.commands) == COMMANDS
    assert config.paths.models == PKG / "repo" / "models"
    assert (config.paths.models / "win_prob.joblib").is_file()
    assert "vendor" not in config.paths.root.parts


def test_refresh_launches_the_syndicate_cli(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("refresh_nba_probe_cli", ROOT / "scripts" / "refresh_nba_oddsapi_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []
    monkeypatch.setattr(mod, "_run_to_file", lambda cmd, log, **kw: calls.append((list(map(str, cmd)), str(kw.get("cwd")))) or 0)
    log = tmp_path / "run.log"
    mod._run_source_subprocess_cli_command(source_root=tmp_path, package_name="nba_betting", command_parts=["fetch-schedule"],
                                           log_file=log, heartbeat_cb=None, timeout_s=1)
    mod._run_source_predict_date(source_root=tmp_path, package_name="nba_betting", date_str="2026-10-13", log_file=log, heartbeat_cb=None)
    assert [c[0][1:3] for c in calls] == [["-m", "syndicate.features.nba.source_cli.cli"]] * 2
    assert [c[0][3:] for c in calls] == [["fetch-schedule"], ["predict-date", "--date", "2026-10-13"]]
    assert all(Path(c[1]) == mod.REPO_ROOT for c in calls)
    src = (ROOT / "scripts" / "refresh_nba_oddsapi_props.py").read_text(encoding="utf-8")
    assert 'f"{package_name}.cli"' not in src
