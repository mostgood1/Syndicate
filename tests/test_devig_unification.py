"""Audit §7 ranked #5, as it turned out to actually be.

The audit said two de-vig orderings were live and asked for them to be
collapsed. That premise is false: `book_grid` never de-vigs at all, and the one
real ordering (`devig` -> `fair_probability_by_book` -> `consensus_fair_probability`)
already had both of its consumers. What WAS duplicated is the *vigged* consensus
-- a mean of implied probabilities converted back to a price -- hand-rolled
identically in `book_grid` and `odds_book_quotes`, and disagreeing with the
owning converter at the boundary.

These tests pin three things:
  1. the two statistics are DIFFERENT and must not converge (the anti-collapse
     test -- if someone later "unifies" them, this goes red),
  2. the boundary behaviour the copies got wrong,
  3. that neither call site hand-rolls the conversion any more.

Mutation-pinned: restoring `>=` for `>` at the even-money branch turns
`test_even_money_is_plus_100` red; restoring the raw arithmetic at either call
site turns `test_no_call_site_hand_rolls_the_conversion` red.
"""

from __future__ import annotations

import inspect

import pytest

from syndicate.features.shared import book_grid, odds_book_quotes
from syndicate.features.shared.opportunity_signals import (
    consensus_fair_probability,
    consensus_vigged_price,
    implied_probability,
)


# --------------------------------------------------------------------------
# 1. The two statistics are different, and that is the point.
# --------------------------------------------------------------------------


def test_vigged_consensus_is_not_the_fair_probability():
    """A -110/-110 market: the vigged sides sum to the overround, the fair to 1.

    This is the test that stops a future reader from "finishing" #5 by pointing
    `consensus_vigged_price` at `consensus_fair_probability`. They measure
    different things and the margin is exactly the gap.
    """
    vigged_home = consensus_vigged_price([-110])
    vigged_away = consensus_vigged_price([-110])
    summed = implied_probability(vigged_home) + implied_probability(vigged_away)
    assert summed > 1.0
    assert round(summed, 4) == 1.0476  # the -110/-110 overround

    fair = consensus_fair_probability({"book": {"home": -110, "away": -110}})
    assert fair is not None
    assert round(sum(fair.values()), 10) == 1.0
    # The fair is strictly cheaper than the quoted average on both sides.
    assert fair["home"] < implied_probability(vigged_home)


def test_vigged_consensus_carries_the_hold_it_should_not_be_read_as_value():
    """Documented consequence: reading it as value overstates by ~the hold."""
    prices = [-110, -105, -115]
    consensus = consensus_vigged_price(prices)
    fair = consensus_fair_probability({"b": {"home": -110, "away": -110}})
    assert implied_probability(consensus) > fair["home"]


# --------------------------------------------------------------------------
# 2. The boundary. This is where both hand-rolled copies were wrong.
# --------------------------------------------------------------------------


def test_even_money_is_plus_100_not_minus_100():
    """MUTATION PIN. The copies used `>= 0.5` and returned -100 here.

    +100 and -100 are the same probability, so nothing derived moves -- but the
    displayed price did, and the round trip through `implied_probability`
    failed for no reason.
    """
    assert consensus_vigged_price([100]) == 100
    assert consensus_vigged_price([100, -100]) == 100


def test_boundary_refuses_instead_of_raising():
    """MUTATION PIN. The copies raised ZeroDivisionError on a 0 or 1 mean.

    Reachable: `odds_book_quotes._implied_probability(0)` returns 0.0 rather
    than refusing, so an all-zero-price side crashed the board build.
    """
    assert consensus_vigged_price([0]) is None
    assert consensus_vigged_price([]) is None
    assert consensus_vigged_price([None]) is None
    assert consensus_vigged_price(["not a price"]) is None


def test_one_unusable_price_refuses_the_whole_side():
    """Follows `overround`: a partial average is a smaller sample, not the market."""
    assert consensus_vigged_price([-110, None]) is None
    assert consensus_vigged_price([-110, -105]) is not None


def test_valid_prices_are_unchanged_by_the_cutover():
    """The whole point: this must be a boundary-only change.

    Reproduces the old arithmetic on valid inputs and requires an exact match,
    so the cutover cannot have moved a production number.
    """
    for prices in ([-110, -105, -115], [150, 140], [-200], [+300, +250, +280]):
        mean_implied = sum(implied_probability(p) for p in prices) / len(prices)
        legacy = (
            int(round(-100.0 * mean_implied / (1.0 - mean_implied)))
            if mean_implied >= 0.5
            else int(round(100.0 * (1.0 - mean_implied) / mean_implied))
        )
        assert consensus_vigged_price(prices) == legacy, prices


# --------------------------------------------------------------------------
# 3. Neither call site hand-rolls it any more.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module", [book_grid, odds_book_quotes])
def test_no_call_site_hand_rolls_the_conversion(module):
    """MUTATION PIN. Restoring either copy's arithmetic turns this red."""
    source = inspect.getsource(module)
    # The conversion's signature: the -100/(1-p) form outside the owner module.
    assert "-100.0 * mean_implied" not in source
    assert "mean_implied = sum(" not in source
    assert "consensus_vigged_price" in source


def test_edge_vs_consensus_is_absent_not_zero_when_consensus_refuses():
    """A 0.0 would read as 'best price IS consensus' -- the opposite of absent."""
    row = odds_book_quotes.quote_ref(
        [{"price": 0, "bookmaker": "b", "selection": "home"}],
    )
    assert row is not None
    assert row["consensus_price"] is None
    assert row["edge_vs_consensus_pct"] is None
