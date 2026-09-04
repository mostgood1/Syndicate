"""Phase 3 (`#622`), the consumer seam: the probability a bet is priced on.

`ev_pct` is `expected_value_pct(price, market_fair)`, and for a normally-priced
market that is exactly `1/overround - 1` -- so `ev_pct == -hold_pct`, a property
of MARKET STRUCTURE with no view of the bet in it. The simulation reaches the
board only through `blended_score`'s capped additive term, which can reorder
rows but cannot make one exist. Production 2026-09-04:
`positions_where_sim_picked_the_side` was 0 of 13 positions, while
`sim_share_of_staked` was 0.798 -- the sim owned four fifths of the money and
selected none of it.

`staked_probability` is the seam that lets the model into the number itself.

THE LOAD-BEARING TEST HERE IS `test_beta_zero_is_a_bit_for_bit_passthrough`.
Everything else is arithmetic; that one is the deployment argument. It is what
lets the consumer ship, be proven reachable in production, and move nothing --
so the fitted coefficient later lands in a seam already known to work. The
opposite order is how this codebase accumulated `calibration_profile_store`
("nothing calls this yet from a live sim path") and soccer's fitted temperature
scaler, which Phase 3 gives an ultimatum: "a consumer or gets deleted".
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.opportunity_signals import (  # noqa: E402
    _BLEND_MAX_ABS_LOGIT,
    expected_value_pct,
    staked_probability,
)


# --- the deployment argument -------------------------------------------------


@pytest.mark.parametrize("market", [0.001, 0.05, 0.2837, 0.5, 0.5001, 0.75, 0.999])
def test_beta_zero_is_a_bit_for_bit_passthrough(market):
    """NOT `approx`. Exact identity, deliberately.

    A logit round-trip at beta=0 would return `market` to within ~1e-16 and
    perturb every EV on the board by float noise, for nothing. Shipping the
    seam has to be a provable no-op or it is not safe to ship ahead of the fit.
    """
    assert staked_probability(market, 0.9, beta=0.0) is market or \
        staked_probability(market, 0.9, beta=0.0) == market
    assert staked_probability(market, None, beta=0.0) == market


def test_beta_zero_leaves_ev_identical():
    """The property one layer up, where it actually matters."""
    for price in (-110, +250, +100, -1400):
        base = expected_value_pct(price, 0.2837)
        through_seam = expected_value_pct(price, staked_probability(0.2837, 0.61, beta=0.0))
        assert base == through_seam


# --- off != on ---------------------------------------------------------------


def test_a_non_zero_beta_actually_moves_the_probability():
    """Reachability. A seam that cannot change anything is not a seam."""
    market = 0.2837
    moved = staked_probability(market, 0.61, beta=0.5)
    assert moved is not None
    assert abs(moved - market) > 0.05, moved


def test_beta_one_is_the_model_alone():
    """The other endpoint, which the repo already runs as `_model_value_ev`."""
    got = staked_probability(0.2837, 0.61, beta=1.0)
    assert got == pytest.approx(0.61, abs=1e-9)


# --- the convexity guarantee -------------------------------------------------


@pytest.mark.parametrize("beta", [0.05, 0.25, 0.5, 0.75, 0.95])
def test_the_default_blend_lands_BETWEEN_its_inputs(beta):
    """`alpha` defaults to `1 - beta`, so the result cannot be more extreme than
    both inputs. That is the guarantee that stops a fit from manufacturing a
    confidence neither source had."""
    for market, model in ((0.28, 0.61), (0.61, 0.28), (0.5, 0.9), (0.02, 0.15)):
        got = staked_probability(market, model, beta=beta)
        assert min(market, model) <= got <= max(market, model), (market, model, beta, got)


def test_it_is_a_LOGIT_blend_not_a_linear_one():
    """Pins the estimator. A linear blend of probabilities is a different (and
    worse) thing near the tails -- it is not invariant to which side of the
    market you quote, so the two sides of one market would not stay coherent."""
    market, model, beta = 0.2, 0.8, 0.5
    linear = (1 - beta) * market + beta * model
    got = staked_probability(market, model, beta=beta)
    assert got == pytest.approx(0.5, abs=1e-9)   # logit blend of symmetric odds
    assert got == pytest.approx(linear, abs=1e-9)  # coincides only by symmetry

    market, model = 0.1, 0.5
    linear = (1 - beta) * market + beta * model
    got = staked_probability(market, model, beta=beta)
    assert abs(got - linear) > 0.02, (got, linear)


def test_explicit_alpha_is_honoured():
    """The plan's spec is two free coefficients, not a convex weight."""
    got = staked_probability(0.5, 0.5, beta=0.4, alpha=0.4)
    assert got == pytest.approx(0.5, abs=1e-9)  # logit(0.5) == 0
    shrunk = staked_probability(0.8, 0.8, beta=0.25, alpha=0.25)
    assert 0.5 < shrunk < 0.8, shrunk  # half the total weight pulls toward even


# --- refusals, which are the safety half -------------------------------------


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5, None, "", "abc", float("nan")])
def test_an_unusable_MARKET_probability_returns_None(bad):
    """Same condition under which `expected_value_pct` already returns None, so
    the seam cannot widen the set of rows that carry an EV."""
    assert staked_probability(bad, 0.5, beta=0.5) is None


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, None, "", float("nan")])
def test_a_DEGENERATE_MODEL_probability_falls_back_to_the_market(bad):
    """Refused, not clamped, and NOT propagated as None.

    `#624` step 1 established that 0.0 is the dangerous sign -- it says the
    outcome is impossible and prices the other side at 100% confidence. Clamping
    it would launder that into a merely-extreme number; returning None would
    delete the row's EV. Falling back to the market says the honest thing: this
    row has no usable model view.
    """
    assert staked_probability(0.3, bad, beta=0.5) == 0.3


def test_a_missing_model_view_keeps_the_row_priced():
    """Most rows have no model probability. A blend that blanked them would
    delete EV from the majority of the board."""
    assert staked_probability(0.42, None, beta=0.9) == 0.42


def test_a_percent_scaled_model_probability_is_normalised():
    """Matches `model_edge_pct`'s existing tolerance -- sports modules are
    inconsistent about percent vs fraction, and this must not read 61 as
    certainty."""
    assert staked_probability(0.3, 61.0, beta=1.0) == pytest.approx(0.61, abs=1e-9)


# --- the tail clamp ----------------------------------------------------------


def test_the_blend_cannot_reach_certainty():
    """`logit` diverges at 0 and 1, so an unclamped blend of two confident
    inputs prices a bet at effectively infinite EV. This is `#624` step 1's
    certainty refusal surviving one arithmetic layer further down."""
    extreme = staked_probability(0.9999, 0.9999, beta=0.5, alpha=0.5)
    assert 0.0 < extreme < 1.0
    ceiling = 1.0 / (1.0 + math.exp(-_BLEND_MAX_ABS_LOGIT))
    assert extreme <= ceiling + 1e-12

    amplified = staked_probability(0.999, 0.999, beta=8.0, alpha=8.0)
    assert amplified is not None and amplified < 1.0
    assert expected_value_pct(+100, amplified) is not None


def test_the_clamp_binds_symmetrically():
    low = staked_probability(0.0001, 0.0001, beta=8.0, alpha=8.0)
    high = staked_probability(0.9999, 0.9999, beta=8.0, alpha=8.0)
    assert low is not None and high is not None
    assert low == pytest.approx(1.0 - high, abs=1e-9)
