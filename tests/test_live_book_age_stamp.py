"""Gate 3: the live-market clock, and why only venue rows may reset it.

MEASURED 2026-08-25T03:13:38Z, after every other explanation was ruled out:

  mlb  cand=1302 scored=1300 priced=1390 opps=0 lanes={'dead': 1302}
  wnba cand=1225 scored=1225 priced=1247 opps=0 lanes={'dead': 1225}
  nfl  ... lanes={'opportunity': 112, 'watchlist': 226, 'dead': 2304}

  GAME_STATE_JOIN sport=mlb  chips=25 rows_matched=816 unmatched=None
  GAME_STATE_JOIN sport=wnba chips=5  rows_matched=643 unmatched=None

The game-state join is HEALTHY. That is exactly the problem: MLB and WNBA are
correctly identified as LIVE, so they take `opportunity_gate`'s
`state == "live"` branch -- which NFL and soccer never reach -- and are held to

    LIVE_MARKET_MAX_AGE_SECONDS    =    900   (15 min)
    PREGAME_MARKET_MAX_AGE_SECONDS = 86,400   (24 hr)

a 96x tightening at first pitch, judged on `book_age_seconds`. That field is
the one age `stamp_candidate_freshness` deliberately did NOT refresh, so a
venue-priced row seconds old still carried an OddsAPI book clock measured in
hours. 100% of both live sports went dead.

THE RESTRICTION IS THE SAFETY ARGUMENT. Blanket-stamping `book_age_seconds`
would defeat the only check standing between us and a stale price on a live
game -- the most dangerous row on the board with real money armed. It is reset
ONLY for venues that quote a live market continuously, where the venue's
`fetched_at` genuinely IS the last observation of the market moving.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared.venue_quote_fanin import (
    _LIVE_QUOTING_VENUES,
    Quote,
    stamp_candidate_freshness,
)


def _quote(source: str, *, age: float = 30.0) -> Quote:
    return Quote(
        key="mlb|h2h|chicago cubs",
        source=source,
        sport="mlb",
        market="h2h",
        side="chicago cubs",
        probability=0.55,
        american=-122,
        line=None,
        fetched_at=time.time() - age,
        venue_ref="aec-mlb-chc-ari-2026-08-24",
    )


def _row(book_age: float | None = 7200.0) -> dict:
    quote_block = {} if book_age is None else {"book_age_seconds": book_age}
    return {"sport": "mlb", "market": "h2h", "side": "home", "quote": quote_block}


@pytest.mark.parametrize("source", sorted(_LIVE_QUOTING_VENUES))
def test_a_live_quoting_venue_RESETS_the_book_clock(source):
    """The fix: a row repriced 30s ago must clear the 900s live ceiling."""
    stamped = stamp_candidate_freshness(_row(book_age=7200.0), _quote(source, age=30.0))

    assert stamped["quote"]["book_age_seconds"] == pytest.approx(30.0, abs=2.0)
    assert stamped["quote"]["book_age_seconds"] < 900.0
    assert stamped["quote"]["book_age_source"] == source


def test_ODDSAPI_never_resets_the_book_clock():
    """An aggregator shard is a periodic CAPTURE, not an observation of the
    market moving. Treating its age as a book clock is the laundering
    `opportunity_gate` exists to prevent."""
    stamped = stamp_candidate_freshness(_row(book_age=7200.0), _quote("oddsapi", age=5.0))

    assert stamped["quote"]["book_age_seconds"] == 7200.0
    assert "book_age_source" not in stamped["quote"]


def test_the_clock_can_only_get_YOUNGER_never_older():
    """`min()` against the existing value. A book that really is fresher keeps
    its own number -- this may never age a row up."""
    stamped = stamp_candidate_freshness(_row(book_age=5.0), _quote("kalshi", age=600.0))

    assert stamped["quote"]["book_age_seconds"] == 5.0


def test_a_row_with_no_book_clock_GETS_one_from_the_venue():
    """`live_no_book_clock` is its own LANE_DEAD path: no clock on an
    in-progress game is not evidence of life. A venue-priced row has one."""
    stamped = stamp_candidate_freshness(_row(book_age=None), _quote("kalshi", age=42.0))

    assert stamped["quote"]["book_age_seconds"] == pytest.approx(42.0, abs=2.0)


def test_a_STALE_venue_quote_still_fails_the_live_ceiling():
    """The gate is not defeated -- it is fed a truthful number. A venue quote
    genuinely older than 900s must still read as too old."""
    stamped = stamp_candidate_freshness(_row(book_age=None), _quote("kalshi", age=1800.0))

    assert stamped["quote"]["book_age_seconds"] > 900.0


def test_an_unparseable_existing_clock_does_not_crash_or_win():
    stamped = stamp_candidate_freshness(
        {"sport": "mlb", "quote": {"book_age_seconds": "not-a-number"}},
        _quote("kalshi", age=15.0),
    )

    assert stamped["quote"]["book_age_seconds"] == pytest.approx(15.0, abs=2.0)


def test_no_quote_means_NO_stamp_at_all():
    """A missing price must never refresh a timestamp -- that laundering is
    worse than an honest stale row."""
    row = _row(book_age=7200.0)

    assert stamp_candidate_freshness(row, None)["quote"]["book_age_seconds"] == 7200.0


def test_the_other_two_gates_are_still_stamped():
    """Gate 3 is additive. Gates 1 and 2 must not regress."""
    stamped = stamp_candidate_freshness(_row(), _quote("kalshi", age=30.0))

    assert stamped["last_updated"].endswith("Z")
    assert stamped["updated_epoch"] > 0
    assert stamped["quote"]["quote_seen_age_seconds"] == pytest.approx(30.0, abs=2.0)
    assert stamped["price_source"] == "kalshi"


def test_the_venue_list_is_explicit_not_negated():
    """"anything not oddsapi" would silently admit each new source. Novig's
    public tier cannot price a named bet at all."""
    assert _LIVE_QUOTING_VENUES == {"kalshi", "polymarket_us"}
    assert "oddsapi" not in _LIVE_QUOTING_VENUES
    assert "novig" not in _LIVE_QUOTING_VENUES
