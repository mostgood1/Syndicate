"""ESPN 5xx on a date RANGE splits into single dates (lane soccer-espn-range-5xx).

Measured 2026-10-02: bel.1 `20270410-20270430` -> 502 in 0.17 s, every time, while
the single dates inside it -> 200. Only a 400 used to split, so the 502 failed
`build_soccer_schedule --league belgian_pro_league` and soccer ok=false in every
pregame run from 18:33Z.
"""
from __future__ import annotations

import pytest
import requests

from syndicate.features.soccer.ingestion import espn_lineups


class _Resp:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._payload


def _fake_get(range_status: int, day_status: int = 200):
    calls = []

    def get(url, params=None, timeout=None):
        dates = (params or {}).get("dates", "")
        calls.append(dates)
        if "-" in dates:
            return _Resp(range_status)
        return _Resp(day_status, {"events": [{"id": dates}]})

    return get, calls


@pytest.mark.parametrize("status", [502, 500, 503])
def test_a_5xx_on_a_range_falls_back_to_single_dates(monkeypatch, status):
    get, calls = _fake_get(status)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    payloads = espn_lineups._scoreboard_payloads("belgian_pro_league", "20270410-20270412", 20)
    assert [p["events"][0]["id"] for p in payloads] == ["20270410", "20270411", "20270412"]
    assert calls == ["20270410-20270412", "20270410", "20270411", "20270412"]


def test_the_400_fallback_is_unchanged(monkeypatch):
    get, _calls = _fake_get(400)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    assert len(espn_lineups._scoreboard_payloads("epl", "20261001-20261002", 20)) == 2


def test_a_5xx_on_a_single_date_still_raises(monkeypatch):
    get, _calls = _fake_get(200, day_status=502)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        espn_lineups._scoreboard_payloads("belgian_pro_league", "20270410", 20)


def test_a_5xx_on_a_one_day_range_still_raises(monkeypatch):
    """A one-day range is sent as a bare date, so there is nothing narrower to retry."""
    get, _calls = _fake_get(200, day_status=502)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        espn_lineups._scoreboard_payloads("belgian_pro_league", "20270410-20270410", 20)


def test_other_statuses_on_a_range_still_raise(monkeypatch):
    get, _calls = _fake_get(404)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        espn_lineups._scoreboard_payloads("belgian_pro_league", "20270410-20270430", 20)


def test_a_5xx_on_an_unparseable_window_still_raises(monkeypatch):
    get, _calls = _fake_get(502)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        espn_lineups._scoreboard_payloads("belgian_pro_league", "2027-04-10-bad", 20)


def test_a_failing_single_date_inside_a_split_range_still_raises(monkeypatch):
    """The fallback does not swallow errors on its own retries."""
    get, _calls = _fake_get(502, day_status=502)
    monkeypatch.setattr(espn_lineups.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        espn_lineups._scoreboard_payloads("belgian_pro_league", "20270410-20270412", 20)
