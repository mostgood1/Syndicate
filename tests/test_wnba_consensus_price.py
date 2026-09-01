"""Consensus book prices are averaged in probability space, not on the odds scale.

MEASURED 2026-08-31 on production WNBA cards (lane `wnba-accuracy-assessment`):
**55 of 128 priced card fields -- 43.0% -- were strictly between -100 and +100**
(`-89.125`, `-94.375`, `-62.25`, `-59.14`). No such American price exists. They
were arithmetic means of American odds taken across books, and every EV computed
from one was wrong.

`test_arithmetic_mean_produces_an_impossible_price` is the REACHABILITY test: it
pins what the old rule did to the very inputs that produced those numbers, so a
regression cannot quietly restore it.
"""
from __future__ import annotations

import pytest

from scripts.refresh_wnba_oddsapi_props import (
    _american_to_probability,
    _consensus_price_or_none,
    _mean_or_none,
    _probability_to_american,
)


# --------------------------------------------------------------- reachability
def test_arithmetic_mean_produces_an_impossible_price():
    """Two real, valid book prices; the old rule returns a value that is not a price."""
    books = [-110.0, 105.0]
    old = _mean_or_none(books)
    assert -100.0 < old < 100.0, "fixture must reproduce the defect"
    assert _american_to_probability(old) is None, (
        "the old rule's output is not an American price at all"
    )


def test_consensus_of_the_same_books_is_a_real_price():
    price = _consensus_price_or_none([-110.0, 105.0])
    assert price is not None
    assert not (-100.0 < price < 100.0)


# ------------------------------------------------------------------ behaviour
def test_single_book_round_trips_exactly():
    for odds in (-110.0, -250.0, 100.0, 145.0, 2500.0, -10000.0):
        result = _consensus_price_or_none([odds])
        assert result == pytest.approx(odds, rel=1e-9), odds


def test_even_money_is_canonicalised_to_plus_100():
    """`+100` and `-100` are the same probability; one spelling has to win.

    `+100` is chosen because `-100` reads as a favourite at a glance.
    """
    assert _consensus_price_or_none([100.0]) == pytest.approx(100.0)
    assert _consensus_price_or_none([-100.0]) == pytest.approx(100.0)
    assert _american_to_probability(100.0) == pytest.approx(0.5)
    assert _american_to_probability(-100.0) == pytest.approx(0.5)


def test_consensus_sits_between_the_books_in_probability_space():
    books = [-130.0, -110.0]
    price = _consensus_price_or_none(books)
    probability = _american_to_probability(price)
    low = _american_to_probability(-110.0)
    high = _american_to_probability(-130.0)
    assert low < probability < high
    # The returned price is rounded to 2dp to kill float round-trip noise, so
    # the implied probability matches the midpoint to within that rounding, not
    # exactly.
    assert probability == pytest.approx((low + high) / 2, abs=1e-4)


def test_impossible_inputs_are_rejected_not_coerced():
    """A price inside the hole is a parse error; coercing it invents a probability."""
    assert _american_to_probability(-50.0) is None
    assert _american_to_probability(0.0) is None
    assert _american_to_probability(99.9) is None
    assert _consensus_price_or_none([-89.125, -94.375]) is None
    # One good book among bad ones still yields that book's price.
    assert _consensus_price_or_none([-89.125, -110.0]) == pytest.approx(-110.0, rel=1e-9)


def test_empty_and_all_none_yield_none():
    assert _consensus_price_or_none([]) is None
    assert _consensus_price_or_none([None, None]) is None  # type: ignore[list-item]


def test_favourite_and_underdog_stay_on_their_own_side_of_even():
    assert _consensus_price_or_none([-200.0, -180.0]) < -100.0
    assert _consensus_price_or_none([180.0, 200.0]) > 100.0


def test_lines_still_use_the_arithmetic_mean():
    """Spreads and totals ARE linear -- this fix must not touch them."""
    assert _mean_or_none([185.5, 186.5]) == pytest.approx(186.0)
    assert _mean_or_none([-7.5, -6.5]) == pytest.approx(-7.0)


def test_probability_to_american_rejects_degenerate_probabilities():
    assert _probability_to_american(0.0) is None
    assert _probability_to_american(1.0) is None


def test_game_aggregate_emits_only_real_prices():
    """The wiring, end to end -- a correct helper nobody calls is inert."""
    from scripts.refresh_wnba_oddsapi_props import _aggregate_game_odds_from_market_rows

    rows = [
        {"market": "h2h", "outcome_name": "Home Team", "price": -110.0},
        {"market": "h2h", "outcome_name": "Home Team", "price": 105.0},
        {"market": "h2h", "outcome_name": "Away Team", "price": -105.0},
        {"market": "spreads", "outcome_name": "Home Team", "point": -3.5, "price": -110.0},
        {"market": "spreads", "outcome_name": "Home Team", "point": -3.5, "price": 100.0},
        {"market": "spreads", "outcome_name": "Away Team", "point": 3.5, "price": -110.0},
        {"market": "totals", "outcome_name": "Over", "point": 165.5, "price": -115.0},
        {"market": "totals", "outcome_name": "Under", "point": 165.5, "price": 102.0},
    ]
    out = _aggregate_game_odds_from_market_rows(rows, home_name="Home Team", away_name="Away Team")
    for field in ("home_ml", "away_ml", "home_spread_price", "away_spread_price",
                  "total_over_price", "total_under_price"):
        value = out[field]
        assert value is not None, field
        assert not (-100.0 < value < 100.0), f"{field}={value} is not an American price"
    # Lines are unchanged by the fix.
    assert out["home_spread"] == pytest.approx(-3.5)
    assert out["total"] == pytest.approx(165.5)
