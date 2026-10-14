"""The basketball schedule fallback runs Syndicate's CLI, and the reader returns each game once
(lane basketball-schedule-adapter-native, user request 2026-10-14).

`schedule_adapter._fetch_basketball_schedule_via_cli` ran the vendored `<sport>_betting.cli fetch-schedule` from
vendor/; the NBA one cannot reach the season in play (cdn.nba.com 403), so every NBA miss rewrote last season's file
(fleet 2026-10-14: 0 rows for a 7-game preseason date). conftest replaces that function process-wide, so these tests
load a fresh copy of the module and stub `subprocess.run` -- nothing is spawned.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "syndicate" / "features" / "shared" / "schedule_adapter.py"


@pytest.fixture()
def fresh(monkeypatch):
    spec = importlib.util.spec_from_file_location("schedule_adapter_fresh_probe", ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)  # its dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("sport,module,env_key", [
    ("nba", "syndicate.features.nba.source_cli.cli", "NBA_BETTING_DATA_ROOT"),
    ("wnba", "syndicate.features.wnba.source_cli.cli", "WNBA_BETTING_DATA_ROOT"),
])
def test_the_fallback_runs_the_syndicate_cli_under_the_data_root(fresh, monkeypatch, tmp_path, sport, module, env_key):
    calls = []
    monkeypatch.setattr(fresh.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or type("R", (), {"returncode": 0})())
    monkeypatch.delenv(env_key, raising=False)
    assert fresh._fetch_basketball_schedule_via_cli(sport) is False and calls == []  # no data root: never writes in-repo
    monkeypatch.setenv(env_key, str(tmp_path))
    assert fresh._fetch_basketball_schedule_via_cli(sport) is True
    (cmd, kw), = calls
    assert cmd[1:] == ["-m", module, "fetch-schedule"]
    assert Path(kw["cwd"]) == fresh.REPO_ROOT
    assert kw["env"]["PYTHONPATH"].split(__import__("os").pathsep)[0] == str(fresh.REPO_ROOT)
    assert "vendor" not in kw["env"]["PYTHONPATH"]


def test_no_vendored_package_is_named(fresh):
    import inspect

    src = inspect.getsource(fresh._fetch_basketball_schedule_via_cli)
    assert "_betting.cli" not in src and '"vendor"' not in src
    assert not hasattr(fresh, "_BASKETBALL_VENDOR_DIR") and not hasattr(fresh, "_BASKETBALL_PACKAGE")


def test_each_game_is_returned_once_across_overlapping_roots_and_alias_files(fresh, monkeypatch, tmp_path):
    games = [
        {"game_id": "0022600001", "date_utc": "2026-10-20", "home_tricode": "DET", "away_tricode": "BOS", "datetime_utc": "2026-10-20T23:00:00Z"},
        {"game_id": "0022600002", "date_utc": "2026-10-20", "home_tricode": "NYK", "away_tricode": "PHI", "datetime_utc": "2026-10-21T00:00:00Z"},
        {"game_id": "0022600004", "date_utc": "2026-10-21", "home_tricode": "MIA", "away_tricode": "MIN", "datetime_utc": "2026-10-21T23:30:00Z"},
    ]
    for name in ("schedule_2026_27.json", "schedule_2025_26.json"):
        (tmp_path / name).write_text(json.dumps(games), encoding="utf-8")
    monkeypatch.setattr(fresh, "_basketball_processed_roots", lambda sport: [tmp_path, tmp_path])
    rows = fresh._read_basketball_schedule_rows("nba", "2026-10-20")
    assert [r["event_id"] for r in rows] == ["0022600001", "0022600002"]
    assert (rows[0]["home"], rows[0]["away"]) == ("DET", "BOS")
