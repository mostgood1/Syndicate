"""scripts/fetch_mlb_injuries.py no longer imports the vendored MLB StatsAPI client (lane mlb-injuries-fetch-native,
user request 2026-10-15).

It imported StatsApiClient / fetch_schedule_for_date / fetch_team_roster from vendor/mlb_bettingv2's
sim_engine.data.statsapi. It now carries a copy of exactly what it used; fleet A/B old vs new on 4 dates: identical.
These tests stub `requests` -- no network.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_mlb_injuries.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("fetch_mlb_injuries_probe", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_imports_nothing_vendored():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    mods += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in mods if m.split(".")[0] in {"sim_engine", "vendor"}], mods
    assert "sys.path.insert" not in SCRIPT.read_text(encoding="utf-8")


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            err = requests.exceptions.HTTPError(f"{self.status_code}")
            err.response = self
            raise err

    def json(self):
        return self._payload


def _fake_requests(monkeypatch, responses, calls):
    import requests

    class Session:
        trust_env = True

        def get(self, url, params=None, timeout=None):
            calls.append({"url": url, "params": dict(params or {}), "timeout": timeout, "trust_env": self.trust_env})
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(sys.modules["fetch_mlb_injuries_probe"].time if "fetch_mlb_injuries_probe" in sys.modules else __import__("time"), "sleep", lambda s: None)


def test_requests_match_the_vendored_client(mod, monkeypatch):
    import requests

    calls = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    _fake_requests(monkeypatch, [_Resp({"dates": [{"games": [{"gamePk": 1}]}]}), _Resp({"roster": [{"person": {"id": 7}}]})], calls)
    monkeypatch.delenv("STATSAPI_TRUST_ENV", raising=False)
    assert mod.fetch_schedule_for_date("2026-10-15") == [{"gamePk": 1}]
    assert mod.fetch_team_roster(147, roster_type="40Man", date_str="2026-10-15") == [{"person": {"id": 7}}]
    assert calls[0] == {"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"sportId": 1, "date": "2026-10-15", "hydrate": "probablePitcher,team"},
                        "timeout": (8.0, 8.0), "trust_env": False}
    assert calls[1]["url"] == "https://statsapi.mlb.com/api/v1/teams/147/roster"
    assert calls[1]["params"] == {"rosterType": "40Man", "date": "2026-10-15"}


def test_retries_transient_failures_but_not_4xx(mod, monkeypatch):
    import requests

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    calls = []
    _fake_requests(monkeypatch, [requests.exceptions.ConnectionError("x"), _Resp({}, 503), _Resp({"ok": 1})], calls)
    assert mod._statsapi_get("/x") == {"ok": 1} and len(calls) == 3  # 1 try + 2 retries
    calls.clear()
    _fake_requests(monkeypatch, [_Resp({}, 404)], calls)
    with pytest.raises(requests.exceptions.HTTPError):
        mod._statsapi_get("/x")
    assert len(calls) == 1


def test_main_reports_injured_players_per_team(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod, "fetch_schedule_for_date", lambda d: [{"teams": {"away": {"team": {"id": 1}}, "home": {"team": {"id": 2}}}}])
    rosters = {(1, "active"): [{"person": {"id": 10, "fullName": "A"}, "status": {"code": "A"}}],
               (1, "40Man"): [{"person": {"id": 11, "fullName": "B"}, "status": {"code": "D10", "description": "10-Day IL"}}],
               (2, "active"): [], (2, "40Man"): [{"person": {"id": 12}, "status": {"description": "60-Day Injured List"}}]}
    monkeypatch.setattr(mod, "fetch_team_roster", lambda team_id, roster_type="active", date_str=None: rosters[(team_id, roster_type)])
    monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-15"])
    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["date"] == "2026-10-15"
    assert [p["player_id"] for p in out["teams"]["1"]] == [11] and [p["player_id"] for p in out["teams"]["2"]] == [12]
