"""[lane wnba-vendor-deletion-prep, 2026-10-20: the native-vs-vendored comparisons are retired with the vendored app; parity was proven 2026-10-12 and the port is frozen source. What stays: the builder loads no vendored module.]
WNBA live OddsAPI period lines: Syndicate's port == the vendored app's function, on the same responses.

Lane wnba-live-period-lines-native (2026-10-12). The vendored arm is AST-extracted from
vendor/wnba_betting_repo/app.py (the function, its team-code closure and its cache), so the 46,820-line Flask app is
never imported. HTTP is mocked: no test here reaches OddsAPI.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import requests

from syndicate.features.wnba import live_period_lines as native

ROOT = Path(__file__).resolve().parents[1]
_NAMES = ("_env_int_clamped", "_CappedDict", "_load_team_maps", "_get_tricode", "_canonical_team_tri", "_espn_to_tri", "_live_oddsapi_period_totals_for_game")


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.ok = 200 <= status < 300

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return copy.deepcopy(self._payload)


def _iso(delta_hours):
    return (datetime.utcnow() + timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bk(markets):
    return {"key": "bk", "markets": markets}


GOOD_EVENTS = [
    {"id": "far", "home_team": "Las Vegas Aces", "away_team": "New York Liberty", "commence_time": _iso(240)},
    {"id": "near", "home_team": "Las Vegas Aces", "away_team": "New York Liberty", "commence_time": _iso(-1)},
    {"id": "other", "home_team": "Indiana Fever", "away_team": "Chicago Sky", "commence_time": _iso(0)},
]
ALL_KEYS = ["totals", "spreads", "h2h", "totals_h1", "spreads_h1", "totals_2h", "spreads_2nd_half", "totals_q1", "spreads_q1",
            "totals_2q", "spreads_q2", "totals_3rd_quarter", "spreads_3q", "totals_q4", "spreads_fourth_quarter"]
ODDS = {"bookmakers": [
    _bk([
        {"key": "totals", "outcomes": [{"name": "Over", "point": 165.5}, {"name": "Under", "point": 165.5}]},
        {"key": "spreads", "outcomes": [{"name": "Las Vegas Aces", "point": -4.5}, {"name": "New York Liberty", "point": 4.5}]},
        {"key": "h2h", "outcomes": [{"name": "Las Vegas Aces", "price": -180}, {"name": "New York Liberty", "price": 150}]},
        {"key": "totals_h1", "outcomes": [{"name": "Over", "point": 82.5}, {"name": "Under", "point": "bad"}]},
        {"key": "spreads_h1", "outcomes": [{"name": "Las Vegas Aces", "point": -2.5}, {"name": "New York Liberty", "point": 2.5}]},
        {"key": "totals_q1", "outcomes": [{"name": "Over", "point": 41.5}, {"name": "Under", "point": float("nan")}]},
        {"key": "totals_2q", "outcomes": [{"name": "Over", "point": 40.5}]},
        {"key": "spreads_q2", "outcomes": [{"name": "LVA", "point": -1.0}, {"name": "NYL", "point": 1.0}]},
        {"key": "totals_3rd_quarter", "outcomes": [{"name": "Over", "point": 42}]},
        {"key": "totals_q4", "outcomes": "not-a-list"},
        {"key": "unpicked_market", "outcomes": [{"name": "Over", "point": 999}]},
    ]),
    _bk([
        {"key": "totals", "outcomes": [{"name": "Over", "point": 166.5}]},
        {"key": "spreads", "outcomes": [{"name": "Las Vegas Aces", "point": -5.0}, {"name": "New York Liberty", "point": 5.0}]},
        {"key": "h2h", "outcomes": [{"name": "Las Vegas Aces", "price": -170}, {"name": "New York Liberty", "price": "x"}]},
        {"key": "totals_2h", "outcomes": [{"name": "Over", "point": 83}, {"name": "Under", "point": 83}]},
        {"key": "spreads_2nd_half", "outcomes": [{"name": "Las Vegas Aces", "point": -3}, {"name": "New York Liberty", "point": 3}]},
        {"key": "spreads_fourth_quarter", "outcomes": [{"name": "Las Vegas Aces", "point": -0.5}]},
    ]),
    "not-a-bookmaker",
]}

WNBA_NAMES = ["Atlanta Dream", "Chicago Sky", "Connecticut Sun", "Dallas Wings", "Golden State Valkyries", "Indiana Fever",
              "Los Angeles Sparks", "Las Vegas Aces", "Minnesota Lynx", "New York Liberty", "Phoenix Mercury", "Portland Fire",
              "Seattle Storm", "Toronto Tempo", "Washington Mystics"]
CODES = ["ATL", "CHI", "CON", "DAL", "GSV", "GS", "GSW", "IND", "LA", "LAS", "LV", "LVA", "MIN", "NY", "NYL", "NYK", "PHX", "PHO",
         "POR", "SEA", "TOR", "WSH", "WAS", "", None, "Over", "Under", "LAL", "BOS"]


def test_live_lines_builder_loads_no_vendored_module(tmp_path):
    """Fresh interpreter: the refresh script builds live lines for an IN-PROGRESS game through the native port, and
    neither the vendored Flask app (`syndicate_wnba_source_app`) nor any `wnba_betting` module is loaded."""
    import os
    import subprocess

    code = (
        "import sys, importlib.util, pathlib, tempfile\n"
        "spec = importlib.util.spec_from_file_location('wnba_refresh_probe', 'scripts/refresh_wnba_oddsapi_props.py')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "root = pathlib.Path(tempfile.mkdtemp()); (root / 'data' / 'processed').mkdir(parents=True)\n"
        "sink = {}\n"
        "m._build_source_live_lines_payload(source_root=root, processed_root=root / 'data' / 'processed', date_str='2026-07-15',\n"
        "    state_payload={'games': [{'event_id': '1', 'home': 'LVA', 'away': 'NYL', 'in_progress': True}]}, diagnostic_sink=sink)\n"
        "print('ATTEMPTED', sink['per_game']['1']['attempted'], sink.get('period_lines_source'))\n"
        "print('VENDORED', sorted(k for k in sys.modules if k == 'syndicate_wnba_source_app' or k.split('.')[0] == 'wnba_betting'))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("ODDS_API_KEY", "THE_ODDS_API_KEY")}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "ATTEMPTED True syndicate_native" in out.stdout, out.stdout[-1500:]
    assert "VENDORED []" in out.stdout, out.stdout[-1500:]
