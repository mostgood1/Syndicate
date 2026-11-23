"""Soccer quote rows file by the CENTRAL kickoff day when the switch is on.

Lane evening-utc-date-split. Measured on the fleet 2026-11-22: Real Salt Lake @
Vancouver (MLS, 7:30 PM CT = 01:30Z on the 23rd) had its 473 OddsAPI rows in
`book_grid_2026-11-23`, while its live state and live index were on 11-22. The
11-22 build held the match in its index but considered only 2 rows, so the match
had no live model and placed 0 orders.

These pin off != on, today's behaviour when the key is absent, reachability
through both real writers, and the transition-ghost drop in the UTC-day grid.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from syndicate.features.shared import odds_book_quotes
from syndicate.features.shared.book_grid_artifact import drop_events_moved_to_another_date
from syndicate.features.shared.odds_book_quotes import quote_key
from syndicate.features.shared.soccer_quote_shard import (
    SOCCER_QUOTE_SHARD_CENTRAL_ENV,
    soccer_quote_shard_date,
)

RSL_KICKOFF = "2026-11-23T01:30:00Z"  # 7:30 PM CT on 11-22
DAY_KICKOFF = "2026-11-22T20:00:00Z"  # 2:00 PM CT on 11-22
NOW = datetime(2026, 11, 22, 23, 0, tzinfo=timezone.utc)


@pytest.fixture
def switch(monkeypatch):
    def _set(value):
        if value is None:
            monkeypatch.delenv(SOCCER_QUOTE_SHARD_CENTRAL_ENV, raising=False)
        else:
            monkeypatch.setenv(SOCCER_QUOTE_SHARD_CENTRAL_ENV, value)

    return _set


def test_absent_is_todays_utc_slice(switch):
    switch(None)
    assert soccer_quote_shard_date({"commence_time": RSL_KICKOFF}, now=NOW) == "2026-11-23"
    assert soccer_quote_shard_date({"commence_time": DAY_KICKOFF}, now=NOW) == "2026-11-22"


@pytest.mark.parametrize("value", ["", "0", "off", "false", "garbage"])
def test_anything_but_on_is_off(switch, value):
    switch(value)
    assert soccer_quote_shard_date({"commence_time": RSL_KICKOFF}, now=NOW) == "2026-11-23"


def test_off_differs_from_on_for_an_after_midnight_utc_kickoff(switch):
    switch(None)
    off = soccer_quote_shard_date({"commence_time": RSL_KICKOFF}, now=NOW)
    switch("on")
    on = soccer_quote_shard_date({"commence_time": RSL_KICKOFF}, now=NOW)
    assert (off, on) == ("2026-11-23", "2026-11-22")


def test_a_daytime_kickoff_is_the_same_either_way(switch):
    switch("on")
    assert soccer_quote_shard_date({"commence_time": DAY_KICKOFF}, now=NOW) == "2026-11-22"


def test_no_kickoff_falls_back_to_today_in_each_calendar(switch):
    late = datetime(2026, 11, 23, 3, 0, tzinfo=timezone.utc)  # 9 PM CT on 11-22
    switch(None)
    assert soccer_quote_shard_date({}, now=late) == "2026-11-23"
    switch("on")
    assert soccer_quote_shard_date({}, now=late) == "2026-11-22"


def _capture_appends(monkeypatch):
    calls = []

    def _append(**kwargs):
        calls.append((kwargs["date_str"], len(kwargs["rows"])))
        return {"appended": len(kwargs["rows"])}

    def _rows(events, **_kwargs):
        return [{"commence_time": e["commence_time"], "event_id": e["id"]} for e in events]

    monkeypatch.setattr(odds_book_quotes, "append_book_quotes", _append)
    monkeypatch.setattr(odds_book_quotes, "quote_rows_from_oddsapi_events", _rows)
    return calls


EVENTS = [
    {"id": "rsl", "commence_time": RSL_KICKOFF},
    {"id": "day", "commence_time": DAY_KICKOFF},
]


@pytest.mark.parametrize(
    "value,expected",
    [(None, [("2026-11-22", 1), ("2026-11-23", 1)]), ("on", [("2026-11-22", 2)])],
)
def test_reachability_odds_writer(monkeypatch, switch, value, expected):
    """The real game-odds writer routes through the switch (off != on)."""
    module = importlib.import_module("scripts.fetch_soccer_oddsapi_odds_local")
    calls = _capture_appends(monkeypatch)
    switch(value)
    module._append_soccer_book_quotes(league="mls", events=EVENTS)
    assert sorted(calls) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(None, [("2026-11-22", 1), ("2026-11-23", 1)]), ("on", [("2026-11-22", 2)])],
)
def test_reachability_props_writer(monkeypatch, switch, value, expected):
    """The real props writer routes through the switch (off != on)."""
    module = importlib.import_module("scripts.fetch_soccer_oddsapi_props_local")
    calls = _capture_appends(monkeypatch)
    switch(value)
    module._append_soccer_prop_book_quotes(league="mls", payloads=EVENTS)
    assert sorted(calls) == expected


# --- the transition ghost in the UTC-day grid --------------------------------------

GHOST_NOW = datetime(2026, 12, 8, 12, 0, tzinfo=timezone.utc)
GHOST_KICKOFF = "2026-12-13T01:30:00Z"  # 7:30 PM CT on 12-12, UTC day 12-13


def _quote(stamp_kickoff):
    return {
        "sport": "soccer", "kind": "game", "event_id": "ev1", "segment": "full", "market": "h2h",
        "player_name": "", "selection": "home", "line": None, "price": -120, "bookmaker": "fanduel",
        "home_team": "Vancouver Whitecaps FC", "away_team": "Real Salt Lake", "commence_time": stamp_kickoff,
    }


def _ghost_call(switch_value, switch):
    switch(switch_value)
    grid = [{"event_id": "ev1", "market": "h2h", "commence_time": GHOST_KICKOFF}]
    own_seen = {quote_key(_quote(GHOST_KICKOFF)): "2026-12-08T03:00:00+00:00"}  # pre-switch, 9 h quiet
    central_seen = {"2026-12-12": {quote_key(_quote(GHOST_KICKOFF)): "2026-12-08T11:55:00+00:00"}}
    return drop_events_moved_to_another_date(
        grid, sport="soccer", date_str="2026-12-13", last_seen=own_seen, now=GHOST_NOW,
        read_last_seen=lambda sport, d: central_seen.get(d, {}),
    )


def test_off_keeps_the_old_utc_shard_rows(switch):
    kept, counters = _ghost_call(None, switch)
    assert len(kept) == 1
    assert counters["candidates"] == 0


def test_on_drops_the_old_utc_shard_rows_once_the_central_shard_is_newer(switch):
    kept, counters = _ghost_call("on", switch)
    assert kept == []
    assert counters["events_moved"] == 1
    assert counters["sample"][0]["moved_to"] == "2026-12-12"


def test_on_never_touches_another_sport(switch):
    switch("on")
    grid = [{"event_id": "ev1", "market": "h2h", "commence_time": GHOST_KICKOFF}]
    own_seen = {quote_key(_quote(GHOST_KICKOFF)): "2026-12-08T03:00:00+00:00"}
    kept, counters = drop_events_moved_to_another_date(
        grid, sport="nfl", date_str="2026-12-13", last_seen=own_seen, now=GHOST_NOW,
        read_last_seen=lambda sport, d: {},
    )
    assert kept == grid
    assert counters["candidates"] == 0
