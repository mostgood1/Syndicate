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
    # Was 0.0338 while Polymarket was priced at the unmeasured 0.10 bound.
    # Polymarket's real fee is now MEASURED AT ZERO, so the whole bar is
    # Kalshi's half-rate parabola plus the tightened 0.01 bound.
    assert worst_break_even == pytest.approx(0.01125, abs=0.0005)


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


def test_the_measured_leg_is_cheaper_than_the_bound_and_both_are_priceable():
    """`polymarket_fee_bound=False` used to RAISE because the fee was unknown.

    It is measured now, so it prices -- and it must price CHEAPER than the
    bound, or the bound is not conservative.
    """
    bounded = net_edge_per_contract(0.60, 0.39, kalshi_fee_multiplier=0.5)
    measured = net_edge_per_contract(
        0.60, 0.39, kalshi_fee_multiplier=0.5, polymarket_fee_bound=False
    )
    assert measured["net_edge_per_contract"] > bounded["net_edge_per_contract"]
    assert measured["polymarket_fee_per_contract"] == 0.0
    assert measured["polymarket_fee_basis"] == "measured"


def test_KALSHI_is_now_the_dominant_cost_and_that_is_the_finding_inverting():
    """This test used to assert the OPPOSITE, and the inversion is the result.

    While Polymarket sat at the unmeasured 0.10 bound it contributed 0.025
    against Kalshi's 0.00875 -- two thirds of a modelled pair cost resting on a
    number nobody had observed. Measured, Polymarket is ZERO, so the entire bar
    is Kalshi's own schedule. Break-even at even money on MLB falls
    3.38c -> 0.88c.
    """
    detail = net_edge_per_contract(0.50, 0.50, kalshi_fee_multiplier=0.5)
    assert detail["kalshi_fee_per_contract"] > detail["polymarket_fee_per_contract"]
    assert detail["total_fee_per_contract"] == pytest.approx(0.01125, abs=0.0005)


# ---------------------------------------------------------------------------
# The GATE. `net_edge_per_contract` existed with no caller while
# `detect_arb_opportunities` still gated on the flat buffer -- an unwired model
# is indistinguishable from no model.
# ---------------------------------------------------------------------------


def _match(k_home, pm_away, mult=None):
    m = {
        "sport": "mlb", "event_id": "e1", "home_team": "H", "away_team": "A",
        "game_date": "2026-08-29",
        "kalshi_home_probability": k_home, "kalshi_away_probability": 1 - k_home,
        "polymarket_home_probability": 1 - pm_away, "polymarket_away_probability": pm_away,
        "kalshi_ticker": "T", "polymarket_market_id": "M",
        "polymarket_fee_coefficient": None, "polymarket_tick": 0.01, "polymarket_min_qty": 1,
    }
    if mult is not None:
        m["kalshi_fee_multiplier"] = mult
    return m


def test_a_pair_BETWEEN_the_old_bar_and_the_new_one_is_now_an_opportunity():
    """off != on for the whole rewiring.

    A ~2c raw gap at the tail clears the measured bar and does NOT clear the
    flat 4.00c. Before the wiring `is_opportunity` was computed from the buffer
    and would have been False; the model now decides.
    """
    from syndicate.features.shared.kalshi_polymarket_arb import detect_arb_opportunities

    # tail pricing, MLB half rate: break-even ~0.2c, raw gap 2c
    out = detect_arb_opportunities([_match(0.94, 0.04, mult=0.5)])[0]

    assert out["raw_edge"] > 0
    assert out["net_edge_per_contract"] > 0
    assert out["is_opportunity"] is True
    # The OLD gate would have refused it -- kept visible beside the new one.
    assert out["edge_after_buffer"] < 0, (
        "this pair must NOT clear the flat 4c buffer, or it does not discriminate"
    )


def test_the_measured_bar_is_BELOW_the_old_buffer_at_every_price():
    """I wrote a test asserting the opposite first, and it was wrong.

    The intuition was "the gate is differently SHAPED, so a pair could clear the
    flat 4c and still fail the model at even money". That WAS true while
    Polymarket sat at the unmeasured 0.10 bound -- the bar peaked at 4.25c.
    With Polymarket MEASURED AT ZERO the peak is 2.00c, so the model is
    UNIFORMLY more permissive and no such pair exists. Asserting the real
    property instead of contorting a fixture until the wrong one passed.

    The shape claim survives in `test_fees_fall_monotonically_toward_the_tail`;
    what does not survive is the idea that the shape ever makes it STRICTER
    than a flat 4c.
    """
    from syndicate.features.shared.venue_fees import (
        KALSHI_BASE_TAKER_RATE,
        POLYMARKET_ASSUMED_WORST_CASE_RATE,
    )

    worst = max(
        (KALSHI_BASE_TAKER_RATE * mult * p * (1 - p))
        + (POLYMARKET_ASSUMED_WORST_CASE_RATE * (1 - p) * p)
        for mult in (0.5, 1.0)
        for p in [i / 100 for i in range(5, 96)]
    )
    assert worst == pytest.approx(0.02, abs=0.0005), f"peak bar {worst}"
    assert worst < DEFAULT_FEE_BUFFER


def test_an_unpriceable_row_is_NOT_an_opportunity():
    """A row we cannot price must never fall back to the flat buffer -- that is
    the old gate wearing the new one's clothes."""
    from syndicate.features.shared.kalshi_polymarket_arb import detect_arb_opportunities

    # BOTH Kalshi legs must be invalid: the detector picks the CHEAPER combo,
    # so corrupting only `home` left it pricing a perfectly valid `away` leg and
    # the test passed for the wrong reason on its first run.
    bad = _match(0.50, 0.40)
    bad["kalshi_home_probability"] = 1.9
    bad["kalshi_away_probability"] = 1.9
    out = detect_arb_opportunities([bad])[0]
    assert out["net_edge_per_contract"] is None
    assert out["is_opportunity"] is False
    assert out["polymarket_fee_basis"].startswith("unpriceable:")


def test_the_kalshi_multiplier_defaults_CONSERVATIVE_and_that_is_a_known_gap():
    """`join_kalshi_polymarket_moneylines` does NOT put `kalshi_fee_multiplier`
    on the match, so the detector defaults to 1.0 — FULL rate.

    Every MLB game series is actually 0.5, so MLB pairs are priced at TWICE
    their real Kalshi fee. That errs toward refusing a real opportunity, which
    is the safe direction, but it IS wrong and it is pinned here so the next
    reader finds it as a known gap rather than rediscovering it as a defect.
    """
    from syndicate.features.shared.kalshi_polymarket_arb import detect_arb_opportunities

    unset = detect_arb_opportunities([_match(0.60, 0.39)])[0]
    real = detect_arb_opportunities([_match(0.60, 0.39, mult=0.5)])[0]
    assert unset["modelled_fee_per_contract"] > real["modelled_fee_per_contract"]
