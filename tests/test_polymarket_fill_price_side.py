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


def test_a_fill_above_our_own_limit_is_WITHHELD_not_recorded(capsys):
    """THE BOS/MIA ORDER, and the check that would have caught it live.

    The complement rule above is a RULE about which side `avgPx` is quoted on.
    Nothing verified its OUTPUT, so when it was applied to a market it should
    not have been, the ledger recorded a price the order could never have
    filled at -- and said nothing.

    MEASURED 2026-08-26, `tsc-mlb-bos-mia-2026-08-26-8pt5`, real money:
        submitted  limit 0.43, quantity 9.60 ($4.13)
        venue      semi-filled 7.11 of 9.60
        recorded   fill_price 0.57 -> 7.11 x 0.57 = $4.05
        ceiling    7.11 x 0.43     =            $3.06     32% over

    This asserts the only thing provable without venue semantics: a BUY does
    not fill above the price we ourselves sent.
    """
    view = venue_order_view(_order(
        marketSlug="tsc-mlb-bos-mia-2026-08-26-8pt5",
        cumQuantity="7.11",
        avgPx="0.43",                       # complemented to 0.57 by the rule
        outcomeSide="OUTCOME_SIDE_NO",
        price={"value": "0.43", "currency": "USD"},   # our submitted limit
    ))

    # The fill is REAL and must survive -- only the price is untrustworthy.
    assert view["state"] == "filled"
    assert view["filled_count"] == 7.11
    # WITHHELD, not corrected: flipping it back would be a third guess at the
    # same convention. Reconciliation falls back to the price we asked for.
    assert view["fill_price"] is None

    out = capsys.readouterr().out
    assert "FILL_ABOVE_LIMIT" in out
    assert "submitted_limit=0.43" in out


def test_a_normal_NO_fill_is_untouched_by_the_limit_check(capsys):
    """The check must not fire on the case the complement rule exists for.

    `under 6.5 CLE@LAA`: avgPx 0.565 on the wire, 0.435 to us, against a limit
    of 0.44. 0.435 <= 0.44, so this is a normal fill and nothing is withheld.
    """
    view = venue_order_view(_order(
        avgPx="0.565",
        outcomeSide="OUTCOME_SIDE_NO",
        price={"value": "0.44", "currency": "USD"},
    ))
    assert view["fill_price"] == 0.435
    assert "FILL_ABOVE_LIMIT" not in capsys.readouterr().out


def test_a_rounding_step_over_the_limit_does_NOT_fire(capsys):
    """The venue snaps to a tick. This must catch an INVERTED price -- a whole
    complement away -- never a rounding step, or it would withhold good prices
    and reconciliation would drift onto requested prices for no reason.
    """
    view = venue_order_view(_order(
        avgPx="0.44", outcomeSide="OUTCOME_SIDE_YES",
        price={"value": "0.435", "currency": "USD"},
    ))
    assert view["fill_price"] == 0.44
    assert "FILL_ABOVE_LIMIT" not in capsys.readouterr().out


def test_an_absent_limit_cannot_withhold_anything(capsys):
    """A venue row with no readable limit must leave the price alone. The check
    is a refutation, and with nothing to refute against it has no opinion.
    """
    view = venue_order_view(_order(avgPx="0.40", outcomeSide="OUTCOME_SIDE_YES"))
    assert view["fill_price"] == 0.40
    assert "FILL_ABOVE_LIMIT" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# THE FEE. `fees_dollars` was hardcoded to None while the venue reported the
# charge on every read.
#
# MEASURED 2026-08-29: C60JWBG0WKDK filled 3.91 @ $0.47 = $1.8377; the account
# moved $1.8977. $0.06 -- ~3.3% of notional -- was recorded nowhere.
# ---------------------------------------------------------------------------


def _filled_order(**kw):
    """The real shape, from today's ORDERS_READ key list."""
    base = _order(
        id="C60JWBG0WKDK",
        marketSlug="tsc-mls-nyr-phi-2026-08-29-3pt5",
        side="OUTCOME_SIDE_YES",
        cumQuantity="3.91",
        avgPx="0.47",
        commissionNotionalTotalCollected="0.06",
        commissionsBasisPoints="150",
    )
    base.update(kw)
    return base


def test_the_commission_the_venue_collected_is_recorded():
    view = venue_order_view(_filled_order())
    assert view["fill_price"] == 0.47
    assert view["filled_count"] == 3.91
    assert view["fees_dollars"] == 0.06


def test_a_zero_commission_is_a_reading_not_a_silence():
    """0.0 and None are different claims -- "no fee" versus "never read"."""
    view = venue_order_view(_filled_order(commissionNotionalTotalCollected="0"))
    assert view["fees_dollars"] == 0.0


def test_an_absent_commission_field_stays_None():
    order = _filled_order()
    del order["commissionNotionalTotalCollected"]
    assert venue_order_view(order)["fees_dollars"] is None


def test_a_commission_exceeding_the_fill_is_refused_as_a_unit_error(capsys):
    """The 100x guard. A fee bigger than the spend is cents read as dollars.

    Withholding restores the old behaviour (None), which is visible; booking it
    would put a wrong number into the money record silently.
    """
    # $1.8377 spent, "6" would be cents-as-dollars.
    view = venue_order_view(_filled_order(commissionNotionalTotalCollected="6"))
    assert view["fees_dollars"] is None
    assert "COMMISSION_IMPLAUSIBLE" in capsys.readouterr().out


def test_a_negative_commission_is_refused():
    assert venue_order_view(_filled_order(commissionNotionalTotalCollected="-1"))["fees_dollars"] is None


def test_a_commission_wrapped_in_a_value_object_is_read():
    """`price` arrives as {'value': ..., 'currency': ...} on the submit side."""
    view = venue_order_view(
        _filled_order(commissionNotionalTotalCollected={"value": "0.06", "currency": "USD"})
    )
    assert view["fees_dollars"] == 0.06


def test_an_unparseable_commission_does_not_raise():
    assert venue_order_view(_filled_order(commissionNotionalTotalCollected="n/a"))["fees_dollars"] is None


def test_the_fee_inputs_are_logged_beside_the_charge(capsys):
    """`venue_fees.py` needs the DENOMINATOR to model a rate, not just the fee.

    Recording only `fees_dollars` would replace "no number" with "a number
    nobody can calibrate".
    """
    venue_order_view(_filled_order())
    out = capsys.readouterr().out
    assert "COMMISSION " in out
    for field in ("dollars=0.06", "fill_price=0.47", "filled=3.91", "bps='150'"):
        assert field in out, f"{field!r} missing -- the rate cannot be back-derived"
