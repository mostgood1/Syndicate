"""The MLB schedule helper uses Syndicate's StatsAPI module, not the vendored client (lane mlb-schedule-fetch-native,
user request 2026-10-15).

scripts/fetch_mlb_schedule_for_date.py (the schedule adapter's MLB source) imported StatsApiClient /
fetch_schedule_for_date from vendor/mlb_bettingv2's sim_engine.data.statsapi. It now uses
syndicate.features.mlb.statsapi_http, a faithful copy of that slice. Fleet A/B old vs new on 6 dates: identical.
Network is stubbed throughout.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import requests

from syndicate.features.mlb import statsapi_http as http

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_mlb_schedule_for_date.py"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(str(self.status_code))
            err.response = self
            raise err

    def json(self):
        return self._payload


@pytest.fixture()
def fake(monkeypatch):
    calls, responses = [], []

    class Session:
        trust_env = True

        def get(self, url, params=None, timeout=None):
            calls.append({"url": url, "params": dict(params or {}), "timeout": timeout, "trust_env": self.trust_env})
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    monkeypatch.delenv("STATSAPI_TRUST_ENV", raising=False)
    return calls, responses


def test_schedule_request_matches_the_vendored_client(fake):
    calls, responses = fake
    responses.append(_Resp({"dates": [{"games": [{"gamePk": 1}, {"gamePk": 2}]}, {"games": [{"gamePk": 3}]}]}))
    assert [g["gamePk"] for g in http.fetch_schedule_for_date("2026-10-15")] == [1, 2, 3]
    assert calls == [{"url": "https://statsapi.mlb.com/api/v1/schedule",
                      "params": {"sportId": 1, "date": "2026-10-15", "hydrate": "probablePitcher,team"},
                      "timeout": (8.0, 8.0), "trust_env": False}]


def test_roster_request_and_trust_env(fake, monkeypatch):
    calls, responses = fake
    monkeypatch.setenv("STATSAPI_TRUST_ENV", "yes")
    responses.append(_Resp({"roster": [{"person": {"id": 7}}]}))
    assert http.fetch_team_roster(147, roster_type="40Man", date_str="2026-10-15") == [{"person": {"id": 7}}]
    assert calls[0]["url"].endswith("/teams/147/roster") and calls[0]["params"] == {"rosterType": "40Man", "date": "2026-10-15"}
    assert calls[0]["trust_env"] is True


def test_retries_transient_failures_but_not_4xx(fake):
    calls, responses = fake
    responses.extend([requests.exceptions.Timeout("t"), _Resp({}, 502), _Resp({"ok": 1})])
    assert http.statsapi_get("/x") == {"ok": 1} and len(calls) == 3
    calls.clear()
    responses.append(_Resp({}, 404))
    with pytest.raises(requests.exceptions.HTTPError):
        http.statsapi_get("/x")
    assert len(calls) == 1


def test_script_imports_nothing_vendored_and_keeps_its_output(monkeypatch, capsys):
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    mods += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in mods if m.split(".")[0] in {"sim_engine", "vendor"}], mods
    monkeypatch.setattr(http, "fetch_schedule_for_date", lambda d: [
        {"gamePk": 776, "gameDate": "2026-10-15T17:00:00Z", "status": {"detailedState": "Scheduled"},
         "teams": {"home": {"team": {"id": 1, "name": "Home"}}, "away": {"team": {"id": 2, "name": "Away"}}}},
        {"gamePk": 777, "status": {"detailedState": "Postponed"}, "teams": {}},
    ])
    spec = importlib.util.spec_from_file_location("fetch_mlb_schedule_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["x", "--date", "2026-10-15"])
    assert mod.main() == 0
    assert json.loads(capsys.readouterr().out) == [{"event_id": "776", "home": "Home", "away": "Away",
                                                     "start_time_utc": "2026-10-15T17:00:00Z", "home_team_id": 1, "away_team_id": 2}]
