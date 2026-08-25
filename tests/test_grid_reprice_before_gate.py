"""The venue reprice must run BEFORE the lane gate, not after it.

MEASURED 2026-08-25, five consecutive builds:

    VENUE_REPRICE sports=['nfl','soccer']  rows_in=4296   (never moved)
    03:13:38  mlb(...priced=1390, opps=0, lanes={'dead': 1302})
    03:34:16  mlb(...priced=1390, opps=0, lanes={'dead': 1302})

Byte-identical across a fix to the book clock, because of the ORDERING:

    line 498   build_layer2_rows(grid, ...)      <- opportunity_gate runs here
    line 634   apply_venue_quotes(opportunities) <- reprice ran here

`build_layer2_rows` returns only the gate's SURVIVORS as `opportunities`, so a
row the gate had already killed could never be rescued by a venue price. The
lane was decided before the venue quote was stamped -- which is why the reprice
only ever saw the two PREGAME sports, and why the live ones stayed at zero no
matter what was stamped downstream.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid


def _quote(source, side, american, *, age=30.0, market="h2h", line=None):
    return Quote(
        key=quote_key("mlb", market, side, line),
        source=source, sport="mlb", market=market, side=side,
        probability=0.55, american=american, line=line,
        fetched_at=time.time() - age, venue_ref=f"{source}-ref",
    )


def _grid(price=-110, age=7200.0, book="draftkings"):
    return [{
        "sport": "mlb", "market": "h2h", "line": None, "sides": ["home"],
        "best": {"home": {"price": price, "bookmaker": book, "age_seconds": age}},
    }]


def _collected(*quotes):
    return {"quotes": {q.key: q for q in quotes}, "by_source": {}}


def test_a_venue_quote_REPLACES_price_book_and_age_together():
    grid = _grid()
    result = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("kalshi", "home", -122, age=30.0)),
    )

    side = grid[0]["best"]["home"]
    assert result["repriced"] == 1
    assert side["price"] == -122
    assert side["bookmaker"] == "kalshi"
    assert side["age_seconds"] == pytest.approx(30.0, abs=2.0)
    assert side["price_source"] == "kalshi"


def test_polymarket_us_maps_to_the_BETTABLE_book_name():
    """`book_shortlist.DEFAULT_BOOKS` carries "polymarket", the adapter source
    is "polymarket_us", and a row whose bookmaker is not in that list is
    dropped as `no_bettable_book`."""
    from syndicate.features.shared import book_shortlist

    grid = _grid()
    apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("polymarket_us", "home", 150, age=20.0)),
    )

    assert grid[0]["best"]["home"]["bookmaker"] == "polymarket"
    assert book_shortlist.is_bettable(grid[0]["best"]["home"]["bookmaker"])


def test_price_and_age_move_TOGETHER_never_age_alone():
    """A stale price wearing a fresh timestamp is the laundering the live
    clock exists to catch. A quote with no price must not touch the clock."""
    grid = _grid(age=7200.0)
    apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("kalshi", "home", None, age=5.0)),
    )

    side = grid[0]["best"]["home"]
    assert side["age_seconds"] == 7200.0
    assert side["price"] == -110
    assert side["bookmaker"] == "draftkings"


def test_a_FRESHER_book_price_is_left_entirely_alone():
    """This may never age a side up or replace a fresher book with an older
    venue quote."""
    grid = _grid(price=-105, age=10.0, book="pinnacle")
    result = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("kalshi", "home", -122, age=600.0)),
    )

    side = grid[0]["best"]["home"]
    assert result["repriced"] == 0
    assert side["price"] == -105
    assert side["bookmaker"] == "pinnacle"
    assert side["age_seconds"] == 10.0


def test_ODDSAPI_never_reprices_the_grid():
    """An aggregator shard is a periodic capture, not an observation of the
    market moving."""
    grid = _grid(age=7200.0)
    result = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("oddsapi", "home", -122, age=5.0)),
    )

    assert result["repriced"] == 0
    assert grid[0]["best"]["home"]["price"] == -110
    assert grid[0]["best"]["home"]["age_seconds"] == 7200.0


def test_a_side_the_venue_does_not_quote_is_untouched():
    grid = _grid(age=7200.0)
    result = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("kalshi", "away", -122, age=5.0)),
    )

    assert result["repriced"] == 0
    assert grid[0]["best"]["home"]["age_seconds"] == 7200.0


def test_the_repriced_side_now_CLEARS_the_live_market_ceiling():
    """The whole point: 900s is the live ceiling, and an OddsAPI book clock of
    7200s put 100% of MLB rows in `dead`."""
    from syndicate.features.shared.opportunity_gate import LIVE_MARKET_MAX_AGE_SECONDS

    grid = _grid(age=7200.0)
    apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24",
        collected=_collected(_quote("kalshi", "home", -122, age=45.0)),
    )

    assert grid[0]["best"]["home"]["age_seconds"] < LIVE_MARKET_MAX_AGE_SECONDS


def test_a_malformed_grid_row_does_not_raise():
    result = apply_venue_quotes_to_grid(
        [None, {}, {"best": "not-a-dict"}, {"best": {}, "sides": ["home"]}],
        "mlb", "2026-08-24", collected=_collected(),
    )
    assert result["repriced"] == 0
