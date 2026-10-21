"""CLV over a ledger column that holds two units (todo #719).

Paper fills record American odds (-110); live Kalshi/Polymarket fills record
the contract price (0.65). The CLV primitive used to read 0.65 as American +0.65
(99.4% implied), so every live `closing_mark.clv_pct` came out ~-35 pt. These
pin the conversion at the shared choke point, and that paper rows are unchanged.
"""

from __future__ import annotations

import pytest

from syndicate.features.prediction_ledger import _clv_pct_from_prices
from syndicate.features.shared.order_clv import REASON_RESOLVED, clv_for_orders


def _live_order(fill_price=0.65):
    return {
        "idempotency_key": "live1",
        "opening_key": "ok1",
        "sport": "mlb",
        "market": "h2h",
        "side": "Home",
        "book": "kalshi",
        "venue": "kalshi",
        "requested_price": fill_price,
        "fill_price": fill_price,
        "fill_stake_dollars": 6.5,
    }


def _close_row(close_price):
    return {"key": "ok1", "sport": "mlb", "market": "h2h", "close_price": close_price, "clv_pct": 0.0}


def test_a_live_contract_fill_against_its_equivalent_close_is_about_zero():
    # -186 is 65.03% implied; a 0.65 fill is 65%. Not -34.3.
    clv = _clv_pct_from_prices(0.65, -186)
    assert clv == pytest.approx(0.035, abs=0.01)


def test_the_order_clv_path_grades_a_live_row_in_probability_points():
    report = clv_for_orders([_live_order()], date="2026-10-20", clv_rows=[_close_row(-186)])
    (row,) = report["rows"]
    assert row["reason"] == REASON_RESOLVED
    assert abs(row["clv_pct"]) < 0.5, row["clv_pct"]


def test_a_live_fill_that_beat_the_close_is_positive():
    # Bought at 0.60, closed -186 (65%): we beat it by ~5 points.
    assert _clv_pct_from_prices(0.60, -186) == pytest.approx(5.03, abs=0.01)


def test_a_contract_close_is_read_as_a_contract_too():
    assert _clv_pct_from_prices(0.60, 0.65) == pytest.approx(5.0, abs=1e-6)


@pytest.mark.parametrize(
    "taken, close, expected",
    [(-110, -130, 4.14), (200, 180, 2.38), (-110, -110, 0.0), ("+150", "+120", 5.45)],
)
def test_paper_american_prices_are_unchanged(taken, close, expected):
    assert _clv_pct_from_prices(taken, close) == pytest.approx(expected, abs=0.01)


def test_prices_that_are_neither_unit_still_refuse():
    assert _clv_pct_from_prices(0, -110) is None
    assert _clv_pct_from_prices(None, -110) is None
