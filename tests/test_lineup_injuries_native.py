"""The live loop's lineup-check injuries fetch runs Syndicate's CLI, not the vendored one
(lane basketball-lineup-injuries-native, user request 2026-10-14).

`_fetch_injuries` ran `<sport>_betting.cli fetch-injuries` from vendor/<sport>_betting_repo with its src on
PYTHONPATH, for NBA and WNBA, every lineup-check interval. It now runs `syndicate.features.<sport>.source_cli.cli`
(whose fetch-injuries is parity-proven in the bootstrap parity runs) from this repo. `subprocess.run` is stubbed:
nothing is spawned.
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap
from pathlib import Path

import pytest

from syndicate.features.shared import live_refresh_loop as loop


@pytest.mark.parametrize("sport,module,env_key", [
    ("nba", "syndicate.features.nba.source_cli.cli", "NBA_BETTING_DATA_ROOT"),
    ("wnba", "syndicate.features.wnba.source_cli.cli", "WNBA_BETTING_DATA_ROOT"),
])
def test_each_sport_runs_its_syndicate_cli_under_its_data_root(monkeypatch, tmp_path, sport, module, env_key):
    assert loop._LINEUP_INJURY_FETCH_PACKAGES[sport] == module
    calls = []
    monkeypatch.setattr(loop.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or type("R", (), {"returncode": 0})())
    monkeypatch.delenv(env_key, raising=False)
    assert loop._fetch_injuries(sport, "2026-10-17", cli_module=module) is False and calls == []  # never writes in-repo
    monkeypatch.setenv(env_key, str(tmp_path))
    assert loop._fetch_injuries(sport, "2026-10-17", cli_module=module) is True
    (cmd, kw), = calls
    assert cmd[1:] == ["-m", module, "fetch-injuries", "--date", "2026-10-17"]
    assert Path(kw["cwd"]) == loop.REPO_ROOT
    assert kw["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(loop.REPO_ROOT)
    assert "vendor" not in kw["env"]["PYTHONPATH"]


def test_the_lineup_check_passes_each_sports_module(monkeypatch):
    seen = []
    monkeypatch.setattr(loop, "_fetch_injuries", lambda sport, date_str, **kw: seen.append((sport, kw)) or True)
    monkeypatch.setattr(loop, "_read_last_lineup_check", lambda: {})
    monkeypatch.setattr(loop, "_any_gated_sport_event_within_force_window", lambda *a, **k: False)
    monkeypatch.setattr(loop, "_record_lineup_check", lambda *a, **k: None)
    monkeypatch.setattr(loop, "_record_lineup_injury_change_epochs", lambda *a, **k: None)
    monkeypatch.setattr(loop, "_basketball_lineup_injury_fingerprint", lambda *a, **k: None)
    monkeypatch.setattr(loop, "_wnba_lineup_injury_fingerprint_by_game", lambda *a, **k: {})
    monkeypatch.setattr(loop, "_record_wnba_matchup_lineup_check", lambda *a, **k: None)
    monkeypatch.setattr(loop, "_read_last_wnba_matchup_lineup_check", lambda: {})
    loop._should_force_sim_rerun(now_epoch=1_800_000_000.0, date_str="2026-10-17")
    assert seen == [("nba", {"cli_module": "syndicate.features.nba.source_cli.cli"}),
                    ("wnba", {"cli_module": "syndicate.features.wnba.source_cli.cli"})]


def test_nothing_vendored_is_launched():
    code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(loop._fetch_injuries))))  # code only, not comments
    assert "vendor" not in code and "_betting.cli" not in code
    assert not hasattr(loop, "_vendor_source_root") and not hasattr(loop, "_vendor_worker_env")
