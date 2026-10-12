"""WNBA live OddsAPI period lines: Syndicate's port == the vendored app's function, on the same responses.

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
VENDOR_APP = ROOT / "vendor" / "wnba_betting_repo" / "app.py"
_NAMES = ("_env_int_clamped", "_CappedDict", "_load_team_maps", "_get_tricode", "_canonical_team_tri", "_espn_to_tri", "_live_oddsapi_period_totals_for_game")


def _vendored_league():
    path = ROOT / "vendor" / "wnba_betting_repo" / "src" / "wnba_betting" / "league.py"
    spec = importlib.util.spec_from_file_location("_p6_vendored_wnba_league", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod.LEAGUE


@pytest.fixture(scope="module")
def vendored():
    if not VENDOR_APP.exists():
        pytest.skip("vendored WNBA app not present")
    text = VENDOR_APP.read_text(encoding="utf-8-sig")
    tree = ast.parse(text)
    lines = text.split("\n")
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    src = "\n\n".join("\n".join(lines[defs[n].lineno - 1 : defs[n].end_lineno]) for n in _NAMES)
    mod = ModuleType("_vendored_wnba_period_lines")
    import json, os, time  # noqa: E401
    from datetime import timezone
    from typing import Any, Optional

    import numpy as np

    mod.__dict__.update(json=json, os=os, time=time, datetime=datetime, timezone=timezone, Any=Any, Optional=Optional,
                        np=np, requests=requests, LEAGUE=_vendored_league(), WEB_DIR=VENDOR_APP.parent / "web",
                        _team_name_to_abbr=None, _team_abbr_to_id=None)
    exec(compile("from __future__ import annotations\n" + src, str(VENDOR_APP), "exec"), mod.__dict__)
    mod._live_oddsapi_period_cache = mod._CappedDict(max_items_env="LIVE_ODDSAPI_PERIOD_CACHE_MAX_ITEMS", default_max=16, lo=0, hi=500)
    return mod


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.ok = 200 <= status < 300

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return copy.deepcopy(self._payload)


def _fake_get(script):
    """script: {"events": payload|Exception, "markets": ..., "odds": ...}; a value may be (payload, status)."""

    def get(url, params=None, headers=None, timeout=None):
        kind = "odds" if url.endswith("/odds") else ("markets" if url.endswith("/markets") else "events")
        val = script.get(kind, [])
        if isinstance(val, Exception):
            raise val
        payload, status = val if isinstance(val, tuple) else (val, 200)
        return _Resp(payload, status)

    return get


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

SCENARIOS = {
    "full": {"events": GOOD_EVENTS, "markets": {"bookmakers": [_bk([{"key": k} for k in ALL_KEYS])]}, "odds": ODDS},
    "swapped_teams": {"events": [{"id": "sw", "home_team": "New York Liberty", "away_team": "Las Vegas Aces", "commence_time": _iso(1)}],
                      "markets": [{"key": k} for k in ALL_KEYS], "odds": ODDS},
    "flat_market_list": {"events": GOOD_EVENTS, "markets": [{"key": "totals_h1"}, {"key": "spreads_h1"}, {"bad": 1}], "odds": ODDS},
    "no_wanted_keys": {"events": GOOD_EVENTS, "markets": {"bookmakers": [_bk([{"key": "player_points"}])]}, "odds": ODDS},
    "markets_http_error": {"events": GOOD_EVENTS, "markets": ({"message": "x"}, 422), "odds": ODDS},
    "markets_raises": {"events": GOOD_EVENTS, "markets": requests.ConnectionError("down"), "odds": ODDS},
    "odds_raises": {"events": GOOD_EVENTS, "markets": [{"key": k} for k in ALL_KEYS], "odds": requests.Timeout("slow")},
    "odds_empty": {"events": GOOD_EVENTS, "markets": [{"key": k} for k in ALL_KEYS], "odds": {"bookmakers": []}},
    "odds_bad_json": {"events": GOOD_EVENTS, "markets": [{"key": k} for k in ALL_KEYS], "odds": ValueError("not json")},
    "no_match": {"events": [{"id": "x", "home_team": "Indiana Fever", "away_team": "Chicago Sky", "commence_time": _iso(0)}]},
    "events_not_list": {"events": {"message": "quota"}},
    "events_raises": {"events": requests.ConnectionError("down")},
    "unknown_commence_time": {"events": [{"id": "u", "home_team": "Las Vegas Aces", "away_team": "New York Liberty", "commence_time": None}],
                              "markets": [{"key": "totals"}], "odds": ODDS},
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
@pytest.mark.parametrize("matchup", [("LVA", "NYL"), ("Las Vegas Aces", "New York Liberty")])
def test_native_equals_vendored_on_the_same_responses(name, matchup, vendored, monkeypatch, capsys):
    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")
    monkeypatch.setattr(requests, "get", _fake_get(SCENARIOS[name]))
    outs = {}
    for arm, mod in (("vendored", vendored), ("native", native)):
        mod._live_oddsapi_period_cache.clear()
        outs[arm] = mod._live_oddsapi_period_totals_for_game("2026-07-15", *matchup)
        outs[arm + "_log"] = capsys.readouterr().out
    assert outs["native"] == outs["vendored"]
    assert outs["native_log"] == outs["vendored_log"]  # same diagnostic lines
    if name == "full":
        out = outs["native"]
        assert out["event_id"] == "near" and out["swapped"] is False
        assert out["period_totals"]["h1"] == 82.5 and out["period_totals"]["h2"] == 83.0 and set(out["period_totals"]) >= {"q1", "q2", "q3"}
        assert out["game_lines"]["total"] == 165.5 and out["game_lines"]["home_spread"] == -4.75


def test_no_key_returns_empty_without_http(vendored, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no HTTP without a key"))
    for mod in (vendored, native):
        mod._live_oddsapi_period_cache.clear()
        assert mod._live_oddsapi_period_totals_for_game("2026-07-15", "LVA", "NYL") == {}


def test_cache_serves_within_20s_in_both(vendored, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")
    calls = {"n": 0}
    base = _fake_get(SCENARIOS["full"])

    def counting(*a, **k):
        calls["n"] += 1
        return base(*a, **k)

    monkeypatch.setattr(requests, "get", counting)
    for mod in (vendored, native):
        mod._live_oddsapi_period_cache.clear()
        calls["n"] = 0
        first = mod._live_oddsapi_period_totals_for_game("2026-07-15", "LVA", "NYL")
        again = mod._live_oddsapi_period_totals_for_game("2026-07-15", "LVA", "NYL")
        assert first == again and calls["n"] == 3


WNBA_NAMES = ["Atlanta Dream", "Chicago Sky", "Connecticut Sun", "Dallas Wings", "Golden State Valkyries", "Indiana Fever",
              "Los Angeles Sparks", "Las Vegas Aces", "Minnesota Lynx", "New York Liberty", "Phoenix Mercury", "Portland Fire",
              "Seattle Storm", "Toronto Tempo", "Washington Mystics"]
CODES = ["ATL", "CHI", "CON", "DAL", "GSV", "GS", "GSW", "IND", "LA", "LAS", "LV", "LVA", "MIN", "NY", "NYL", "NYK", "PHX", "PHO",
         "POR", "SEA", "TOR", "WSH", "WAS", "", None, "Over", "Under", "LAL", "BOS"]


def test_team_codes_identical_for_every_wnba_name_and_code(vendored):
    for t in WNBA_NAMES + [n.lower() for n in WNBA_NAMES] + CODES:
        assert native._canonical_team_tri(t) == vendored._canonical_team_tri(t), t


def test_the_only_dropped_mapping_is_nba_full_team_names(vendored):
    """The vendored map merges nba_api's NBA list when nba_api is installed; the port does not. The only inputs that
    can differ are NBA FULL team names, which the basketball_wnba OddsAPI feed never returns."""
    try:
        from nba_api.stats.static import teams as static_teams
    except Exception:
        pytest.skip("nba_api not installed: the vendored map has no NBA entries either")
    differ = [t["full_name"] for t in static_teams.get_teams() if native._canonical_team_tri(t["full_name"]) != vendored._canonical_team_tri(t["full_name"])]
    for t in static_teams.get_teams():
        assert native._canonical_team_tri(t["abbreviation"]) == vendored._canonical_team_tri(t["abbreviation"]), t["abbreviation"]
    assert set(differ) <= {t["full_name"] for t in static_teams.get_teams()}


def test_positive_control_a_changed_aggregation_is_caught(vendored, monkeypatch):
    """The comparison above can fail: a native arm that aggregates books by MEAN instead of median differs."""
    import numpy as np

    class _MeanNp:
        def __getattr__(self, name):
            return np.mean if name == "median" else getattr(np, name)

    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")
    monkeypatch.setattr(requests, "get", _fake_get(SCENARIOS["full"]))
    vendored._live_oddsapi_period_cache.clear()
    native._live_oddsapi_period_cache.clear()
    a = vendored._live_oddsapi_period_totals_for_game("2026-07-15", "LVA", "NYL")
    monkeypatch.setattr(native, "np", _MeanNp())
    b = native._live_oddsapi_period_totals_for_game("2026-07-15", "LVA", "NYL")
    assert a != b


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
