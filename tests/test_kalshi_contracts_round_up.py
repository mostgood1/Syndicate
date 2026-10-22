"""Round Kalshi contracts up to the dollar minimum [user 2026-10-22, "Yes, round up",
lane live-min-stake-five].

`contracts_for_stake` floors, so the $5 band orders of 10-22 filled $4.45-$4.76. With
`SYNDICATE_KALSHI_ROUND_UP_MIN_DOLLARS` set, a stake of at least that minimum whose floored
count costs less than it gains exactly one contract. Absent = floored, as before.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_orders import OrderBuildError, contracts_for_stake

_ENV = "SYNDICATE_KALSHI_ROUND_UP_MIN_DOLLARS"


# The measured 10-22 fills: (stake, price) -> floored count, rounded-up count.
_MEASURED = [
    (5.0, 0.89, 5, 6),   # filled $4.45 -> $5.34
    (5.0, 0.79, 6, 7),   # filled $4.74 -> $5.53
    (5.0, 0.68, 7, 8),   # filled $4.76 -> $5.44
    (5.0, 0.77, 6, 7),   # filled $4.62 -> $5.39
]


@pytest.mark.parametrize("stake,price,floored,_up", _MEASURED)
def test_off_the_count_is_floored(monkeypatch, stake, price, floored, _up):
    """Reachability, off side: absent switch is today's floor."""
    monkeypatch.delenv(_ENV, raising=False)
    assert contracts_for_stake(stake, price) == floored


@pytest.mark.parametrize("stake,price,_floored,up", _MEASURED)
def test_on_a_short_five_dollar_order_gains_one_contract(monkeypatch, stake, price, _floored, up):
    """Reachability, on side: the same orders reach at least $5."""
    monkeypatch.setenv(_ENV, "5")
    count = contracts_for_stake(stake, price)
    assert count == up
    assert count * price >= 5.0


def test_never_more_than_one_contract_over(monkeypatch):
    monkeypatch.setenv(_ENV, "5")
    for price in (0.05, 0.31, 0.5, 0.64, 0.97):
        for stake in (5.0, 5.66, 7.3, 10.0):
            floored = int(stake // price)
            assert contracts_for_stake(stake, price) - floored in (0, 1), (stake, price)


def test_an_order_already_at_the_minimum_is_unchanged(monkeypatch):
    """$5.66 at 0.49 floors to 11 contracts = $5.39 >= $5: no extra contract."""
    monkeypatch.setenv(_ENV, "5")
    assert contracts_for_stake(5.66, 0.49) == 11


def test_a_stake_under_the_minimum_stays_floored(monkeypatch):
    """A cash-trimmed $4.48 stake is not lifted past what the plan sized."""
    monkeypatch.setenv(_ENV, "5")
    assert contracts_for_stake(4.48, 0.64) == 7


def test_a_stake_below_one_contract_still_refuses(monkeypatch):
    monkeypatch.setenv(_ENV, "5")
    with pytest.raises(OrderBuildError, match="stake_below_one_contract"):
        contracts_for_stake(0.40, 0.48)


def test_an_unusable_minimum_is_off(monkeypatch):
    for raw in ("abc", "0", "-5", "inf"):
        monkeypatch.setenv(_ENV, raw)
        assert contracts_for_stake(5.0, 0.89) == 5, raw
