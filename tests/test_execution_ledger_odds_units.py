"""A fill stake must never be computed from AMERICAN ODDS.

MEASURED IN PRODUCTION 2026-08-27, and it took a venue outage to expose it.
Polymarket US began returning `http_500` on `/v1/order/{id}`, so the
reconciler's price fallback walked past the venue price and past the prior fill
price to `requested_price`, which the board stores as AMERICAN ODDS:

    contracts 3.34 x fill_price 104.0 = fill_stake_dollars $347.36
    requested_stake_dollars                                  $1.64

Converted, the same row is 3.34 x american_to_probability(104) = 3.34 x 0.4902
= $1.64 -- the requested stake exactly. That equality is what makes this a UNITS
bug and not a pricing one.

NOT MERELY A REPORTING ERROR. `spent_today` feeds `check_order`, so the guard
believed $368.97 of a $100.01 Polymarket day cap was spent when ~$23 was. The
next genuinely new Polymarket position would have been refused on a budget never
spent, and the venue would have looked quiet for a reason that was not real.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as EL


def test_american_odds_convert_rather_than_multiply():
    price = EL._price_as_probability(104.0)
    assert price == pytest.approx(0.4902, abs=1e-4)
    assert round(3.34 * price, 2) == pytest.approx(1.64, abs=0.01)


def test_a_probability_price_is_left_alone():
    assert EL._price_as_probability(0.475) == 0.475


def test_an_ambiguous_unit_refuses_rather_than_guessing():
    """A guessed unit here is a guessed cap bound."""
    assert EL._price_as_probability(42.0) is None


# ---------------------------------------------------------------------------
# The repair
# ---------------------------------------------------------------------------


def _ledger(orders):
    return {"orders": orders}


@pytest.fixture
def ledger(monkeypatch):
    state = {"orders": []}

    def install(orders):
        state["orders"] = orders
        monkeypatch.setattr(EL, "_load", lambda: {"orders": state["orders"]})
        monkeypatch.setattr(EL, "_persist", lambda s: s)
        return state

    return install


def test_the_repair_rewrites_an_impossible_price(ledger):
    ledger([{ "mode": "live", "venue": "polymarket", "status": "filled",
              "fill_price": 104.0, "contracts": 3.34, "fill_stake_dollars": 347.36}])
    out = EL.repair_odds_unit_stakes()
    assert out["status"] == "ok"
    assert out["repaired"] == 1
    assert out["before"] == pytest.approx(347.36)
    assert out["after"] == pytest.approx(1.64, abs=0.01)


def test_the_repair_keeps_the_original_value_for_audit(ledger):
    orders = [{"mode": "live", "venue": "polymarket", "status": "filled",
               "fill_price": 104.0, "contracts": 3.34, "fill_stake_dollars": 347.36}]
    ledger(orders)
    EL.repair_odds_unit_stakes()
    assert orders[0]["fill_stake_dollars_before_repair"] == 347.36
    assert orders[0]["fill_stake_dollars"] == pytest.approx(1.64, abs=0.01)
    assert 0.0 < orders[0]["fill_price"] < 1.0


def test_a_real_price_row_is_untouched(ledger):
    """The predicate is `outside (0,1)`, which is provable, not a magnitude hunch."""
    orders = [{"mode": "live", "venue": "polymarket", "status": "filled",
               "fill_price": 0.475, "contracts": 4.29, "fill_stake_dollars": 2.04}]
    ledger(orders)
    out = EL.repair_odds_unit_stakes()
    assert out["repaired"] == 0
    assert orders[0]["fill_stake_dollars"] == 2.04
    assert "fill_stake_dollars_before_repair" not in orders[0]


def test_an_ambiguous_price_is_skipped_not_guessed(ledger):
    orders = [{"mode": "live", "venue": "kalshi", "status": "filled",
               "fill_price": 42.0, "contracts": 2.0, "fill_stake_dollars": 84.0}]
    ledger(orders)
    out = EL.repair_odds_unit_stakes()
    assert out["repaired"] == 0
    assert out["skipped_ambiguous"] == 1
    assert orders[0]["fill_stake_dollars"] == 84.0


def test_a_row_without_contracts_is_skipped(ledger):
    orders = [{"mode": "live", "venue": "polymarket", "status": "filled",
               "fill_price": 104.0, "contracts": None, "fill_stake_dollars": 347.36}]
    ledger(orders)
    out = EL.repair_odds_unit_stakes()
    assert out["repaired"] == 0
    assert out["skipped_ambiguous"] == 1


def test_the_repair_is_idempotent(ledger):
    """A second pass must find nothing -- the first made the price a probability."""
    orders = [{"mode": "live", "venue": "polymarket", "status": "filled",
               "fill_price": 104.0, "contracts": 3.34, "fill_stake_dollars": 347.36}]
    ledger(orders)
    assert EL.repair_odds_unit_stakes()["repaired"] == 1
    assert EL.repair_odds_unit_stakes()["repaired"] == 0


# ---------------------------------------------------------------------------
# The repair must never touch the paper book
# ---------------------------------------------------------------------------


def test_a_paper_row_is_never_repaired_even_with_contracts(ledger):
    """The hazard this bound closes, and it is about the FUTURE not today.

    `place_order` stamps a paper fill as `fill_price=requested_price` (AMERICAN
    ODDS) and `fill_stake_dollars=requested_stake_dollars` (real dollars). The
    stake is correct and was never derived from the price, so there is nothing
    to fix.

    Today such rows are skipped anyway because `complete_order` takes no
    `contracts` argument and paper rows carry none -- an ACCIDENT of the current
    signature, not a guarantee. This test fixes the guarantee: a paper row that
    somehow HAS contracts must still be left alone, because repairing it would
    replace a correct requested stake with a derived one and rewrite the paper
    book that exists to be evidence about the live one.
    """
    orders = [{"mode": "paper", "venue": "kalshi", "status": "filled",
               "fill_price": 104.0, "contracts": 3.34, "fill_stake_dollars": 1.64}]
    ledger(orders)
    out = EL.repair_odds_unit_stakes()
    assert out["repaired"] == 0
    assert out["skipped_not_live"] == 1
    assert orders[0]["fill_stake_dollars"] == 1.64
    assert orders[0]["fill_price"] == 104.0
    assert "fill_stake_dollars_before_repair" not in orders[0]


def test_paper_rows_do_not_inflate_the_ambiguous_counter(ledger):
    """`skipped_ambiguous` must mean "could not convert", not "was paper".

    832 paper rows landed in that counter on the first production run, which
    made a benign number look like a diagnostic finding.
    """
    ledger([
        {"mode": "paper", "venue": "kalshi", "status": "filled",
         "fill_price": 104.0, "contracts": None, "fill_stake_dollars": 1.64},
        {"mode": "live", "venue": "kalshi", "status": "filled",
         "fill_price": 42.0, "contracts": 2.0, "fill_stake_dollars": 84.0},
    ])
    out = EL.repair_odds_unit_stakes()
    assert out["skipped_not_live"] == 1
    assert out["skipped_ambiguous"] == 1
