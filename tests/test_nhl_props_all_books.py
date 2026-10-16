"""NHL props ask ten books, not three, at the same credits (lane props-book-coverage, user 2026-10-16)."""
from __future__ import annotations

import pandas as pd

from syndicate import local_nhl_odds as lno


class _Client:
    calls: list[dict] = []

    def __init__(self, *a, **k):
        pass

    def list_events(self, sport, **k):
        return [{"id": "e1", "home_team": "Detroit Red Wings", "away_team": "Philadelphia Flyers",
                 "commence_time": "2026-10-16T23:00:00Z"}], {}

    def event_odds(self, sport, event_id, *, markets, regions="us", bookmakers=None):
        _Client.calls.append({"regions": regions, "bookmakers": bookmakers})
        return {"bookmakers": []}, {}


def _run(monkeypatch, **env):
    _Client.calls = []
    for key in ("PROPS_ODDSAPI_BOOKMAKERS", "PROPS_ODDSAPI_REGIONS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(lno, "OddsApiClient", _Client)
    try:
        out = lno.collect_oddsapi_props("2026-10-16")
    except Exception:  # noqa: BLE001 -- the request is what is under test, not the empty frame's shaping
        out = None
    assert out is None or isinstance(out, pd.DataFrame)
    return _Client.calls


def test_the_default_asks_ten_books_at_one_regions_price(monkeypatch):
    # Measured 2026-10-16: a list of <= 10 books from any regions bills as ONE region; this list returned 7 books on one
    # NHL event (the old default 3, regions=us 5 without Pinnacle) at 1 credit.
    calls = _run(monkeypatch)
    listed = lno.NHL_PROP_BOOKMAKERS.split(",")
    assert len(listed) == len(set(listed)) == 10 and {"pinnacle", "espnbet", "hardrockbet", "draftkings", "fanduel"} <= set(listed)
    assert calls and calls[0]["bookmakers"] == lno.NHL_PROP_BOOKMAKERS


def test_the_env_still_narrows_it(monkeypatch):
    # The control: the knob that used to be the default still works when someone sets it.
    calls = _run(monkeypatch, PROPS_ODDSAPI_BOOKMAKERS="fanduel,draftkings,pinnacle")
    assert calls and calls[0]["bookmakers"] == "fanduel,draftkings,pinnacle"
