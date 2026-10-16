"""Prop calls ask ten named books at one region's price (lane props-book-coverage, user 2026-10-16: "as long as we dont
increase expense lets go ahead"). OddsAPI bills a bookmakers list of up to 10 as one region -- an 11th is a second
region -- so the line held here is the expense line."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from syndicate.features.shared import odds_regions as orx

REPO = Path(__file__).resolve().parents[1]
# What each sport's props got from regions=us, 10-01..10-16 (props shards on the fleet).
SEEN_US = {"nfl": {"draftkings", "bovada", "betonlineag", "fanduel", "betrivers", "betmgm", "fanatics", "williamhill_us"},
           "ncaaf": {"betonlineag", "fanduel", "bovada", "draftkings", "betrivers", "betmgm"},
           # soccer prop-call shards 10-01..10-16, 573,710 rows (lane soccer-uefa-competitions)
           "soccer": {"betrivers", "fanduel", "draftkings", "betmgm", "mybookieag", "bovada", "fanatics", "williamhill_us"}}


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("sport", ["nfl", "ncaaf", "mlb", "nba"])
def test_ten_books_never_eleven(sport):
    books = orx.prop_bookmakers(sport, env={}).split(",")
    assert len(books) == len(set(books)) <= 10                        # an 11th book bills a second region
    assert {"espnbet", "hardrockbet"} <= set(books)                   # the us2 books the region never reached
    assert SEEN_US.get(sport, set()) <= set(books)                    # nothing NFL / NCAAF props had is dropped


def test_the_knobs():
    assert orx.prop_bookmakers("nfl", env={"SYNDICATE_NFL_PROP_BOOKMAKERS": ""}) is None              # back to the region
    assert orx.prop_bookmakers("nfl", env={"SYNDICATE_NFL_PROP_BOOKMAKERS": "fanduel"}) == "fanduel"
    assert orx.prop_bookmakers("nfl", env={"SYNDICATE_NFL_PROP_REGIONS": "eu"}) is None   # a widened region keeps its meaning
    assert orx.prop_bookmakers("wnba", env={}) is None                                              # not listed
    assert orx.prop_bookmakers("soccer", env={"SYNDICATE_SOCCER_PROP_REGIONS": "us,eu"}) is None      # widened soccer keeps its meaning


def test_soccer_ten_keep_every_book_soccer_props_had():
    books = orx.prop_bookmakers("soccer", env={}).split(",")
    assert len(books) == len(set(books)) <= 10
    assert SEEN_US["soccer"] <= set(books)                            # MyBookie included: the shared list would drop it


def test_the_basketball_fetcher_defaults_to_the_league_list(monkeypatch):
    # No --bookmakers -> NBA asks its ten; WNBA (widened to the exchanges by its own refresh) asks the region as before.
    m = _script("fetch_basketball_oddsapi_props_local")
    for key in ("SYNDICATE_NBA_PROP_BOOKMAKERS", "SYNDICATE_NBA_PROP_REGIONS", "SYNDICATE_WNBA_PROP_BOOKMAKERS"):
        monkeypatch.delenv(key, raising=False)
    assert m._league_prop_bookmakers("nba") == orx.PROP_BOOKMAKERS["nba"]
    assert m._league_prop_bookmakers("wnba") is None


class _Resp:
    headers: dict = {}
    url = "https://api.the-odds-api.com/v4/x"
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"bookmakers": []}


@pytest.mark.parametrize("name,sport", [("fetch_nfl_oddsapi_props_local", "nfl"), ("fetch_ncaaf_oddsapi_props_local", "ncaaf")])
def test_the_football_prop_request_carries_the_list(monkeypatch, name, sport):
    m = _script(name)
    seen = []
    monkeypatch.setattr(m.requests, "get", lambda url, params=None, timeout=None: seen.append(dict(params or {})) or _Resp())
    monkeypatch.setattr(m, "record_oddsapi_quota", lambda *a, **k: None, raising=False)
    for key in ("SYNDICATE_NFL_PROP_BOOKMAKERS", "SYNDICATE_NCAAF_PROP_BOOKMAKERS", "SYNDICATE_NFL_PROP_REGIONS",
                "SYNDICATE_NCAAF_PROP_REGIONS"):
        monkeypatch.delenv(key, raising=False)
    try:
        m.fetch_event_odds("k", "e1", region="us", markets=["player_receptions"])
    except Exception:  # noqa: BLE001 -- the request is under test, not the empty payload's shaping
        pass
    assert seen and seen[0]["bookmakers"] == orx.PROP_BOOKMAKERS[sport] and seen[0]["regions"] == "us"


def test_mlb_props_get_the_list_and_game_lines_do_not(monkeypatch, tmp_path):
    m = _script("fetch_mlb_oddsapi_local")
    calls = {}
    monkeypatch.setenv("ODDS_API_KEY", "k")
    for key in ("SYNDICATE_MLB_PROP_BOOKMAKERS", "SYNDICATE_MLB_PROP_REGIONS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m, "diagnose_odds_history_provenance", lambda *a, **k: None)
    monkeypatch.setattr(m, "_fetch_live_events_for_date", lambda *a, **k: [])
    for fn in ("fetch_live_game_lines_for_date", "fetch_live_pitcher_props_for_date", "fetch_live_hitter_props_for_date"):
        monkeypatch.setattr(m, fn, (lambda name: lambda *a, **k: calls.setdefault(name, k.get("bookmakers")) or {})(fn))
    try:
        m.fetch_and_write_live_odds_for_date("2026-10-16", out_dir=tmp_path)
    except Exception:  # noqa: BLE001 -- the three calls are under test, not what is written after them
        pass
    assert calls.get("fetch_live_game_lines_for_date", "unset") is None          # game lines: their regions, no list
    assert calls["fetch_live_pitcher_props_for_date"] == calls["fetch_live_hitter_props_for_date"] == orx.PROP_BOOKMAKERS["mlb"]
