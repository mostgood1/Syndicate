"""Every same-game parlay pays +100 or better, in every sport (user 2026-10-20: "for SGPs we need these to get to +100
or better" ... "for all sports"). The floor is the legs multiplied at one book (`min_decimal`); the safer tier then
takes the likeliest ticket that clears it, the payout tier the best value."""
from __future__ import annotations

from syndicate.features.shared import sgp_hit_rate as shared


def test_every_tier_in_every_sport_pays_plus_100_or_better():
    for spec in shared.TIERS + shared.MLB_TIERS:
        assert spec["min_decimal"] >= 2.0, spec["tier"]
    assert {s["tier"]: s["min_decimal"] for s in shared.TIERS} == {"safer": 2.0, "payout": 2.5}
    assert {s["tier"]: s["min_decimal"] for s in shared.MLB_TIERS} == {"safer": 2.0, "payout": 2.5}


def test_the_safer_tier_ranks_by_hit_rate_and_the_payout_tier_by_value():
    likely = {"p_joint": 0.52, "legs_product_odds": 100}       # 0.52 x 2.00 = 1.04
    pricier = {"p_joint": 0.45, "legs_product_odds": 150}      # 0.45 x 2.50 = 1.125
    safer = next(s for s in shared.TIERS if s["tier"] == "safer")
    payout = next(s for s in shared.TIERS if s["tier"] == "payout")
    assert sorted([pricier, likely], key=shared._order(safer))[0] is likely
    assert sorted([likely, pricier], key=shared._order(payout))[0] is pricier


def test_two_legs_at_the_gate_cannot_reach_even_money_so_the_safer_tier_starts_at_three():
    # The leg gate is 75%+ (MLB 65%+); two 75% legs at a 5% margin multiply to about -128.
    assert min(next(s for s in shared.TIERS if s["tier"] == "safer")["sizes"]) == 3
    assert min(next(s for s in shared.MLB_TIERS if s["tier"] == "safer")["sizes"]) == 2
    assert shared.SWEET_SPOT == 0.80
