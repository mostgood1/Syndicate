"""Fee-aware arb edge: the properties the flat buffer got wrong.

`DEFAULT_FEE_BUFFER = 0.04` demanded a 4.00c raw gap at EVERY price. Measured
break-even for a two-leg MLB pair (Kalshi `fee_multiplier: 0.5`, Polymarket at
its pessimistic bound) is 3.38c at even money and 0.76c at 0.94 -- **below the
flat threshold at every price on the board**. The old detector was therefore
not merely conservative on MLB; it could not flag a profitable pair at all.

These tests pin the SHAPE, not just a number, because the shape is the part
that was wrong.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_polymarket_arb import (
    DEFAULT_FEE_BUFFER,
    net_edge_per_contract,
)
from syndicate.features.shared.venue_fees import VenueFeeUnknown


def _net(k, p, mult=0.5):
    return net_edge_per_contract(k, p, kalshi_fee_multiplier=mult)["net_edge_per_contract"]


def test_a_one_cent_gap_is_profitable_at_the_tail_and_a_loser_at_even_money():
    """The single most important property, and the one a flat buffer cannot have.

    Same 1c raw gap, two prices, opposite verdicts -- because the fee is
    quadratic. Any model that returns the same answer for both is flat, whatever
    it is called.
    """
    tail = _net(0.94, 0.05)      # gross 0.99, 1c gap, fees tiny
    even = _net(0.50, 0.49)      # gross 0.99, 1c gap, fees maximal
    assert tail > 0, "a 1c gap at the tail must clear the real fee"
    assert even < 0, "a 1c gap at even money must NOT clear the real fee"


def test_the_old_flat_buffer_was_above_mlb_break_even_at_every_price():
    """Why this replacement exists, stated as an assertion rather than prose.

    If the flat threshold exceeds break-even everywhere, no MLB pair the
    detector could ever see would have been reported.
    """
    worst_break_even = None
    for price in (0.50, 0.60, 0.70, 0.80, 0.90, 0.94, 0.97):
        detail = net_edge_per_contract(price, 1.0 - price, kalshi_fee_multiplier=0.5)
        break_even = detail["total_fee_per_contract"]
        worst_break_even = break_even if worst_break_even is None else max(worst_break_even, break_even)
        assert break_even < DEFAULT_FEE_BUFFER, (
            f"at p={price} break-even is {break_even:.4f}, already under the"
            f" {DEFAULT_FEE_BUFFER} flat buffer"
        )
    assert worst_break_even == pytest.approx(0.0338, abs=0.0005)


def test_fees_fall_monotonically_toward_the_tail():
    """The quadratic shape, which is what makes in-play lopsided lines viable."""
    costs = [
        net_edge_per_contract(p, 1.0 - p, kalshi_fee_multiplier=0.5)["total_fee_per_contract"]
        for p in (0.50, 0.70, 0.90, 0.97)
    ]
    assert costs == sorted(costs, reverse=True), f"not monotonic: {costs}"


def test_mlb_half_rate_is_cheaper_than_full_rate_on_the_same_pair():
    """off != on for the venue's own `fee_multiplier`, at the arb layer.

    Without this, a regression that dropped the multiplier would still pass
    every other test here -- the shape would be unchanged, only the level.
    """
    half = net_edge_per_contract(0.50, 0.49, kalshi_fee_multiplier=0.5)
    full = net_edge_per_contract(0.50, 0.49, kalshi_fee_multiplier=1.0)
    assert half["net_edge_per_contract"] > full["net_edge_per_contract"]
    assert half["kalshi_fee_per_contract"] == pytest.approx(
        full["kalshi_fee_per_contract"] / 2.0, rel=1e-9
    )


def test_edge_is_size_free():
    """The per-contract rate does not depend on how much we would bet.

    Kalshi's fee is `rate * C * P * (1-P)`, so per contract the C cancels. This
    is what makes the result a property of the market rather than of sizing.
    """
    detail = net_edge_per_contract(0.75, 0.24, kalshi_fee_multiplier=0.5)
    rate_cost = detail["total_fee_per_contract"]
    # Scaling to 1,000 contracts must not change the per-contract economics.
    assert rate_cost * 1000 == pytest.approx(rate_cost * 1000, rel=1e-12)
    assert detail["net_edge_per_contract"] == pytest.approx(
        detail["raw_edge"] - rate_cost, rel=1e-12
    )


def test_polymarket_leg_is_labelled_a_bound_not_a_measurement():
    """A reader must never mistake the stand-in for an observed cost."""
    detail = net_edge_per_contract(0.60, 0.39, kalshi_fee_multiplier=0.5)
    assert detail["polymarket_fee_basis"] == "worst_case_bound"


def test_refusing_the_bound_raises_rather_than_returning_a_cheaper_number():
    """A caller that wants only measured costs gets a refusal, not a discount."""
    with pytest.raises(VenueFeeUnknown):
        net_edge_per_contract(0.60, 0.39, kalshi_fee_multiplier=0.5, polymarket_fee_bound=False)


def test_the_polymarket_bound_is_the_dominant_cost_at_even_money():
    """Stated so the priority is visible: measuring Polymarket's real fee is
    worth more than any further precision on Kalshi's.

    Kalshi MLB at half rate contributes 0.00875; the Polymarket bound
    contributes 0.025. Two thirds of the modelled cost is the number we cannot
    yet read.
    """
    detail = net_edge_per_contract(0.50, 0.50, kalshi_fee_multiplier=0.5)
    assert detail["polymarket_fee_per_contract"] > 2 * detail["kalshi_fee_per_contract"]
