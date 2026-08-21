"""Guards for the NFL/NCAAF player-prop odds capture path.

These exist because the defect they cover was TOTAL and SILENT for months:
every requested market 422'd (wrong endpoint, plus two market keys that do not
exist), the fetcher swallowed each 422 as a WARNING and returned [], and the
run wrote a header-only CSV that is indistinguishable from "the books have not
posted props today".

Measured on production 2026-08-20 before the fix: 13 of 14 weekly NFL prop CSVs
were 5-byte stubs, and 101MB of NFL book_quotes held zero player rows.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


nfl = _load("_test_fetch_nfl_props", "scripts/fetch_nfl_oddsapi_props_local.py")
ncaaf = _load("_test_fetch_ncaaf_props", "scripts/fetch_ncaaf_oddsapi_props_local.py")


# The keys OddsAPI actually accepts, verified live 2026-08-20 against both
# americanfootball_nfl and americanfootball_ncaaf. `player_rec_yds` and
# `player_interceptions` are NOT among them -- each 422s INVALID_MARKET.
VALID_ODDSAPI_MARKETS = {
    "player_reception_yds",
    "player_receptions",
    "player_rush_yds",
    "player_rush_attempts",
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_attempts",
    "player_pass_interceptions",
    "player_anytime_td",
}

KNOWN_INVALID_MARKETS = {"player_rec_yds", "player_interceptions"}


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_requested_markets_are_keys_the_api_accepts(module):
    requested = set(module.DEFAULT_PLAYER_MARKETS)
    assert requested <= VALID_ODDSAPI_MARKETS, (
        f"unknown OddsAPI market key(s): {sorted(requested - VALID_ODDSAPI_MARKETS)}"
    )
    assert not (requested & KNOWN_INVALID_MARKETS), (
        "these keys 422 INVALID_MARKET and produce a silent zero-row capture"
    )
    assert set(module.MARKET_STD_MAP) == requested


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_standard_market_names_are_unchanged(module):
    """The CSV/board contract. Fixing an API key must not rename a market."""
    assert set(module.MARKET_STD_MAP.values()) == {
        "Receiving Yards",
        "Receptions",
        "Rushing Yards",
        "Rushing Attempts",
        "Passing Yards",
        "Passing TDs",
        "Passing Attempts",
        "Interceptions",
        "Anytime TD",
    }


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_props_are_fetched_per_event_not_from_the_bulk_odds_endpoint(module, monkeypatch):
    """Bulk /sports/{key}/odds serves featured markets only; player props are
    per-event. Calling the bulk route is the original defect."""
    called: list[str] = []

    class _Response:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""
        url = "https://example.invalid/"

        def json(self):
            return []

        def raise_for_status(self):
            return None

    def _fake_get(url, params=None, timeout=None):
        called.append(url)
        return _Response()

    monkeypatch.setattr(module.requests, "get", _fake_get)
    monkeypatch.setattr(module, "record_oddsapi_quota", lambda *a, **k: None)
    module.fetch_player_props("key")

    assert called, "no request was made"
    assert not any(u.endswith("/odds") and "/events/" not in u for u in called), (
        f"bulk odds endpoint used: {called}"
    )


def test_events_in_scope_keeps_one_slate_not_the_whole_season():
    """/events returns the whole season (272 NFL events, measured). Props are
    billed per event, so an unbounded sweep pays for games weeks away that
    have no props posted."""
    now = datetime.now(tz=timezone.utc)
    events = [
        {"id": "past", "commence_time": (now - timedelta(days=2)).isoformat()},
        {"id": "wk1a", "commence_time": (now + timedelta(days=1)).isoformat()},
        {"id": "wk1b", "commence_time": (now + timedelta(days=4)).isoformat()},
        {"id": "wk2", "commence_time": (now + timedelta(days=12)).isoformat()},
        {"id": "wk9", "commence_time": (now + timedelta(days=60)).isoformat()},
    ]
    kept = {e["id"] for e in nfl.events_in_scope(events, window_days=8)}
    assert kept == {"wk1a", "wk1b"}, kept


def test_events_in_scope_handles_an_empty_schedule():
    assert nfl.events_in_scope([]) == []
    assert nfl.events_in_scope([{"id": "x"}]) == []


@pytest.mark.parametrize("module", [nfl, ncaaf], ids=["nfl", "ncaaf"])
def test_all_markets_invalid_raises_instead_of_returning_empty(module, monkeypatch):
    """THE anti-regression guard. A bad market key must not look like a quiet
    market: returning [] here is what let the caller write a header-only CSV
    and report success."""
    now = datetime.now(tz=timezone.utc)

    class _Resp422:
        status_code = 422
        headers: dict[str, str] = {}
        text = '{"error_code":"INVALID_MARKET"}'
        url = "https://example.invalid/"

        def json(self):
            return {}

        def raise_for_status(self):
            return None

    class _EventsResp:
        status_code = 200
        headers: dict[str, str] = {}
        text = ""
        url = "https://example.invalid/"

        def json(self):
            return [{"id": "e1", "commence_time": (now + timedelta(days=1)).isoformat()}]

        def raise_for_status(self):
            return None

    def _fake_get(url, params=None, timeout=None):
        return _EventsResp() if url.endswith("/events") else _Resp422()

    monkeypatch.setattr(module.requests, "get", _fake_get)
    monkeypatch.setattr(module, "record_oddsapi_quota", lambda *a, **k: None)

    with pytest.raises(module.InvalidMarketError):
        module.fetch_player_props("key")
