"""Pinnacle reaches NBA / NFL / soccer odds (user 2026-10-25 "Add it now", via the coordinator; lane live-cell-scorecard).

NBA: Pinnacle takes betonlineag's slot in NBA's ten-book per-event list (no extra credits). NFL / soccer: the game-line
call's regions widen by `SYNDICATE_<SPORT>_GAME_LINE_REGIONS` (unset = today's `us`). Each test checks the REQUEST the
fetcher would send, not just the helper -- an unread knob is the failure this file exists to catch."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from syndicate.features.shared import odds_regions as orx

REPO = Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Resp:
    headers: dict = {}
    url = "https://example.invalid/odds"

    def raise_for_status(self):
        return None

    def json(self):
        return []


def _capture(monkeypatch, module):
    sent = []
    monkeypatch.setattr(module.requests, "get", lambda url, params=None, **kw: sent.append(dict(params or {})) or _Resp())
    monkeypatch.setattr(module, "record_oddsapi_quota", lambda *a, **k: None, raising=False)
    return sent


def test_the_per_sport_knob_widens_and_never_narrows():
    assert orx.sport_game_line_regions("nfl", "us", env={}) == "us"
    assert orx.sport_game_line_regions("nfl", "us", env={"SYNDICATE_NFL_GAME_LINE_REGIONS": "eu"}) == "us,eu"
    assert orx.sport_game_line_regions("soccer", "us", env={"SYNDICATE_SOCCER_GAME_LINE_REGIONS": " EU,us "}) == "us,eu"
    # another sport's knob does not leak
    assert orx.sport_game_line_regions("nfl", "us", env={"SYNDICATE_SOCCER_GAME_LINE_REGIONS": "eu"}) == "us"


@pytest.mark.parametrize("knob", [None, "eu"])
def test_nfl_game_line_request_reads_the_knob(monkeypatch, knob):
    m = _script("fetch_nfl_team_odds_local")
    sent = _capture(monkeypatch, m)
    if knob is None:
        monkeypatch.delenv("SYNDICATE_NFL_GAME_LINE_REGIONS", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_NFL_GAME_LINE_REGIONS", knob)
    m.fetch_odds(api_key="k", region="us")
    assert sent and sent[0]["regions"] == ("us" if knob is None else "us,eu")


@pytest.mark.parametrize("knob", [None, "eu"])
def test_soccer_game_line_request_reads_the_knob(monkeypatch, knob):
    m = _script("fetch_soccer_oddsapi_odds_local")
    sent = _capture(monkeypatch, m)
    if knob is None:
        monkeypatch.delenv("SYNDICATE_SOCCER_GAME_LINE_REGIONS", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_SOCCER_GAME_LINE_REGIONS", knob)
    m.fetch_game_odds("k", sport_key="soccer_epl", region="us", markets=["h2h", "totals", "spreads"])
    assert sent and sent[0]["regions"] == ("us" if knob is None else "us,eu")


def test_nba_per_event_list_carries_pinnacle_at_one_regions_price(monkeypatch):
    for key in ("SYNDICATE_NBA_PROP_BOOKMAKERS", "SYNDICATE_NBA_PROP_REGIONS"):
        monkeypatch.delenv(key, raising=False)
    books = orx.prop_bookmakers("nba").split(",")
    assert "pinnacle" in books and "betonlineag" not in books
    assert len(books) == len(set(books)) <= 10                    # an 11th book bills a second region per event
    # the other sports' lists are untouched
    assert "pinnacle" not in orx.prop_bookmakers("nfl").split(",")
    # and the NBA fetcher actually asks for it
    assert "pinnacle" in _script("fetch_basketball_oddsapi_props_local")._league_prop_bookmakers("nba").split(",")
