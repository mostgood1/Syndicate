"""The MLB live-game helper uses Syndicate's StatsAPI module, not the vendored client (lane mlb-live-game-pks-native,
user request 2026-10-15).

scripts/fetch_mlb_live_game_pks_for_date.py (the live loop's "is an MLB game live" signal) imported StatsApiClient /
fetch_schedule_for_date from vendor/mlb_bettingv2's sim_engine.data.statsapi. It now uses
syndicate.features.mlb.statsapi_http; the live-state test is unchanged. Network is stubbed.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

from syndicate.features.mlb import statsapi_http as http

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_mlb_live_game_pks_for_date.py"


def test_imports_nothing_vendored():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    mods += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in mods if m.split(".")[0] in {"sim_engine", "vendor"}], mods


def test_live_state_rule_is_unchanged(monkeypatch, capsys):
    games = [
        {"gamePk": 1, "status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
        {"gamePk": 2, "status": {"abstractGameState": "Preview", "detailedState": "In Progress"}},
        {"gamePk": 3, "status": {"abstractGameState": "Live", "detailedState": "Warmup"}},
        {"gamePk": 4, "status": {"abstractGameState": "Final", "detailedState": "Final"}},
        {"gamePk": "x", "status": {"abstractGameState": "Live"}},
        "not a dict",
    ]
    seen = []
    monkeypatch.setattr(http, "fetch_schedule_for_date", lambda d: seen.append(d) or games)
    spec = importlib.util.spec_from_file_location("fetch_mlb_live_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-15"])
    assert mod.main() == 0
    assert seen == ["2026-10-15"]
    assert json.loads(capsys.readouterr().out) == {"live_game_pks": [1, 2, 3]}
