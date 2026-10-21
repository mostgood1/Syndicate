"""The props refreshes give their source-CLI child its data root (lane basketball-cli-data-root, todo #718).

`python -m syndicate.features.<league>.source_cli.cli export-game-cards` raised "Cannot save file into a non-existent
directory: .../source_cli/repo/data/processed" on runs whose launcher lacked <LEAGUE>_BETTING_DATA_ROOT: the CLI falls
back to its own code tree. The refresh now fills the variable from its source root -- only when unset or empty.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_cli_env_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("script, var", [("refresh_nba_oddsapi_props", "NBA_BETTING_DATA_ROOT"),
                                         ("refresh_wnba_oddsapi_props", "WNBA_BETTING_DATA_ROOT")])
def test_cli_env_fills_the_data_root_only_when_unset(script, var, monkeypatch, tmp_path):
    mod = _load(script)
    data_root = tmp_path / "src" / "data"
    monkeypatch.delenv(var, raising=False)
    assert mod._native_cli_env(data_root)[var] == str(data_root)          # unset -> filled
    monkeypatch.setenv(var, "")
    assert mod._native_cli_env(data_root)[var] == str(data_root)          # empty -> filled
    monkeypatch.setenv(var, "/already/set")
    assert mod._native_cli_env(data_root)[var] == "/already/set"          # set -> never overridden
    monkeypatch.delenv(var, raising=False)
    assert var not in mod._native_cli_env()                               # no data_root -> unchanged behaviour


@pytest.mark.parametrize("script, pkg, var", [("refresh_nba_oddsapi_props", "nba_betting", "NBA_BETTING_DATA_ROOT"),
                                              ("refresh_wnba_oddsapi_props", "wnba_betting", "WNBA_BETTING_DATA_ROOT")])
def test_both_cli_callers_pass_source_root_data(script, pkg, var, monkeypatch, tmp_path):
    """Reachability: the two production callers hand <source_root>/data down to the child's env."""
    mod = _load(script)
    monkeypatch.delenv(var, raising=False)
    seen = []
    monkeypatch.setattr(mod, "_run_to_file", lambda cmd, log, **kw: seen.append(kw["env"].get(var)) or 0)
    src = tmp_path / f"{pkg}_src"
    mod._run_source_subprocess_cli_command(source_root=src, package_name=pkg, command_parts=["export-game-cards", "--date", "2026-10-21"],
                                           log_file=tmp_path / "l.log", heartbeat_cb=None, timeout_s=1)
    mod._run_source_predict_date(source_root=src, package_name=pkg, date_str="2026-10-21", log_file=tmp_path / "l.log", heartbeat_cb=None)
    assert seen == [str(src / "data"), str(src / "data")]
