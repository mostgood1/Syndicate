"""`avgPx` is quoted on the YES side; a NO order's fill is its complement.

WHY THIS FILE EXISTS. Taking `avgPx` at face value recorded the OTHER SIDE's
price on every `under`, and on 2026-08-26T00:23:37Z it halted all trading on
both venues:

    RECONCILE_COUNT_IMPLAUSIBLE key=939fb90b24300f32c760b7bb
      venue_count=2.39 requested=2.3920000000000003
    EXECUTION status=blocked reason=unreconciled_orders  (kalshi AND polymarket)

The order was `under 6.5 CLE@LAA`, +130, $1.04 -> 2.392 contracts, filled 2.39.
At the true NO price 0.435 that is $1.04, inside the $1.30 ceiling. At the YES
price 0.565 it is $1.35 -- over by 3.9%, refused, and the live path latched.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.polymarket_us_orders import venue_order_view


def _order(**kw):
    base = {"id": "o1", "state": "ORDER_STATE_FILLED", "cumQuantity": "2.39",
            "avgPx": "0.565", "side": "OUTCOME_SIDE_NO", "marketSlug": "tsc-mlb-cle-laa-2026-08-25-6pt5"}
    base.update(kw)
    return base


def test_a_NO_fill_is_recorded_as_its_complement():
    """The production case, end to end: 0.565 on the wire is 0.435 to us."""
    view = venue_order_view(_order())
    assert view["state"] == "filled"
    assert view["filled_count"] == 2.39
    assert view["fill_price"] == 0.435


def test_a_YES_fill_is_recorded_as_it_arrives():
    view = venue_order_view(_order(side="OUTCOME_SIDE_YES", avgPx="0.40"))
    assert view["fill_price"] == 0.40


def test_outcomeSide_is_read_before_side():
    """The measured key list carries BOTH. `outcomeSide` is the specific one."""
    view = venue_order_view(_order(outcomeSide="OUTCOME_SIDE_NO", side="ORDER_SIDE_BUY", avgPx="0.565"))
    assert view["fill_price"] == 0.435


def test_an_unreadable_side_withholds_the_price_rather_than_guessing(capsys):
    """Complementing a YES price inverts a correct number; not complementing a
    NO price inverts it the other way. Both are wrong and neither is visible
    downstream, so the price is withheld and reconciliation falls back to the
    price we asked for."""
    view = venue_order_view(_order(side="", outcomeSide="", avgPx="0.565"))
    assert view["fill_price"] is None
    assert "FILL_PRICE_SIDE_UNREADABLE" in capsys.readouterr().out


def test_the_raw_avgPx_is_logged(capsys):
    """This defect was diagnosed from a screenshot and arithmetic because no log
    line carried `avgPx`. The one input that would have settled it in seconds
    was the one nobody could see."""
    venue_order_view(_order())
    out = capsys.readouterr().out
    assert "FILL_PRICE " in out
    assert "avgPx='0.565'" in out
    assert "recorded=0.435" in out


@pytest.mark.parametrize("price", ["0", "1", "1.0", "0.0"])
def test_a_price_at_or_outside_the_bounds_is_never_complemented(price):
    """0 and 1 are not prices -- they are an empty side of the book. Complementing
    either manufactures a real-looking number from an absent one."""
    view = venue_order_view(_order(avgPx=price))
    assert view["fill_price"] == float(price)


def test_the_blocked_order_now_passes_the_dollar_bound():
    """The whole point, in the guard's own arithmetic.

    stake $1.04, requested +130 -> 0.434783 -> 2.392 contracts, ceiling $1.30.
    """
    view = venue_order_view(_order())
    filled_dollars = view["filled_count"] * view["fill_price"]
    assert filled_dollars == pytest.approx(1.0396, abs=1e-3)
    assert filled_dollars < 1.04 * 1.25, "must clear the ceiling that blocked it"
    # And the uncomplemented value must NOT have cleared it -- otherwise this
    # test would pass even with the bug restored.
    assert 2.39 * 0.565 > 1.04 * 1.25
