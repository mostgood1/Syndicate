"""The WNBA props refresh's game-input bootstrap runs Syndicate's CLI, not the vendored one (lane nba-source-cli-native,
user decision 2026-10-13).

  * the package is exactly what scripts/port_basketball_source_cli.py --league wnba generates, models included;
  * nothing in it imports the vendored package or `vendor`;
  * its CLI registers exactly the six commands the refresh runs, and its models dir is the Syndicate copy;
  * the refresh launches `python -m syndicate.features.wnba.source_cli.cli` for the bootstrap steps and predict-date, and
    the vendored `daily-update` CPU retry (never fired in 30 days of logs, not ported) is gone.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "syndicate" / "features" / "wnba" / "source_cli"
SCRIPT = ROOT / "scripts" / "refresh_wnba_oddsapi_props.py"
COMMANDS = {"fetch-schedule", "fetch", "build-features", "fetch-injuries", "write-pregame-expected-minutes", "predict-date"}


def test_port_imports_nothing_vendored():
    bad = []
    for path in sorted(PKG.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            bad += [f"{path.relative_to(PKG)}:{node.lineno} {m}" for m in mods if m.split(".")[0] in {"vendor", "nba_betting", "wnba_betting"}]
    assert not bad, bad


def test_cli_registers_the_six_commands_and_uses_syndicate_models():
    from syndicate.features.wnba.source_cli import cli, config

    assert set(cli.cli.commands) == COMMANDS
    assert config.paths.models == PKG / "repo" / "models"
    assert any(config.paths.models.iterdir())
    assert "vendor" not in config.paths.root.parts


def test_refresh_launches_the_syndicate_cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("refresh_wnba_probe_cli", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []
    monkeypatch.setattr(mod, "_run_to_file", lambda cmd, log, **kw: calls.append((list(map(str, cmd)), str(kw.get("cwd")))) or 0)
    log = tmp_path / "run.log"
    mod._run_source_subprocess_cli_command(source_root=tmp_path, package_name="wnba_betting", command_parts=["fetch-schedule"],
                                           log_file=log, heartbeat_cb=None, timeout_s=1)
    mod._run_source_predict_date(source_root=tmp_path, package_name="wnba_betting", date_str="2026-10-17", log_file=log, heartbeat_cb=None)
    assert [c[0][1:3] for c in calls] == [["-m", "syndicate.features.wnba.source_cli.cli"]] * 2
    assert [c[0][3:] for c in calls] == [["fetch-schedule"], ["predict-date", "--date", "2026-10-17"]]
    assert all(Path(c[1]) == mod.REPO_ROOT for c in calls)
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'f"{package_name}.cli"' not in src and '"daily-update"' not in src
    for name in ("_run_source_daily_update_cpu_fallback", "_run_source_processed_export", "_source_worker_env"):
        assert not hasattr(mod, name), name
