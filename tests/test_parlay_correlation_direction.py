"""The parlay correlation adjustment had the SIGN wrong in both directions.

    correlation_multiplier = 1.0 - min(0.25, max(0.0, avg_corr) * 0.35)
    probability = product(legs) * correlation_multiplier

For an AND of legs:

  * POSITIVE dependence makes the joint MORE likely than the product. The old
    form REDUCED it, so genuinely correlated same-game parlays -- the ones the
    simulation is uniquely able to find -- were systematically underpriced.

  * NEGATIVE dependence makes it LESS likely. `max(0.0, ...)` discarded that
    case entirely, so conflicting legs were priced as INDEPENDENT and their
    probability, and therefore their EV, was OVERSTATED. That is the half that
    loses money, and `compute_correlation` really does return negatives:
    -0.30 for the same subject in opposite directions, -0.06 for opposing teams
    in one game, and a further -0.08 for opposed directions.

`average_correlation` is a heuristic built from categorical flags, not a
measured coefficient, so the fix trusts its SIGN and caps its magnitude. The
shape is what matters: a measured same-game correlation (`#621`) drops into the
same function without changing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.intelligence_parlay_runtime import (  # noqa: E402
    _PARLAY_CORRELATION_MAX_SHIFT,
    _correlation_adjusted_probability,
    _frechet_bounds,
)


def _independent(legs):
    out = 1.0
    for p in legs:
        out *= p
    return out


# --- the two sign errors -----------------------------------------------------


def test_POSITIVE_correlation_RAISES_the_parlay():
    """The old form lowered it. Two 0.5 legs that tend to happen together are
    more likely to both land than 0.25."""
    legs = [0.5, 0.5]
    got = _correlation_adjusted_probability(legs, 0.40)
    assert got > _independent(legs), got

    old_form = _independent(legs) * (1.0 - min(0.25, max(0.0, 0.40) * 0.35))
    assert old_form < _independent(legs)      # the defect, reproduced
    assert got > old_form


def test_NEGATIVE_correlation_LOWERS_the_parlay():
    """The old form did nothing here -- `max(0.0, ...)` threw it away -- so a
    conflicting parlay was priced at the independent product. This is the half
    that overstates EV."""
    legs = [0.5, 0.5]
    got = _correlation_adjusted_probability(legs, -0.40)
    assert got < _independent(legs), got

    old_form = _independent(legs) * (1.0 - min(0.25, max(0.0, -0.40) * 0.35))
    assert old_form == pytest.approx(_independent(legs))   # the defect, reproduced
    assert got < old_form


def test_the_same_subject_opposite_direction_case_is_the_worst_one():
    """`compute_correlation` gives -0.30 for one player bet both ways. Those
    legs nearly exclude each other; independence is the wrong price and the old
    form used exactly that."""
    legs = [0.55, 0.5]
    got = _correlation_adjusted_probability(legs, -0.30)
    assert got < _independent(legs)
    lower, _ = _frechet_bounds(legs)
    assert got >= lower


# --- exactness and monotonicity ---------------------------------------------


@pytest.mark.parametrize("legs", [[0.5, 0.5], [0.2, 0.9], [0.4, 0.4, 0.4], [0.75]])
def test_zero_correlation_is_EXACTLY_independence(legs):
    assert _correlation_adjusted_probability(legs, 0.0) == pytest.approx(_independent(legs), abs=1e-12)


def test_it_is_monotone_in_the_correlation():
    legs = [0.45, 0.6]
    values = [_correlation_adjusted_probability(legs, rho)
              for rho in (-1.0, -0.5, -0.1, 0.0, 0.1, 0.5, 1.0)]
    assert values == sorted(values), values
    assert values[0] < values[-1]


# --- bounded by construction -------------------------------------------------


@pytest.mark.parametrize("rho", [-4.0, -1.0, -0.3, 0.0, 0.3, 1.0, 4.0])
@pytest.mark.parametrize("legs", [[0.5, 0.5], [0.05, 0.99], [0.9, 0.9, 0.9], [0.01, 0.02]])
def test_the_result_is_always_a_valid_probability_inside_the_frechet_bounds(legs, rho):
    """A free multiplier on the product can leave the feasible region; an
    interpolation between the bounds cannot. This is why the adjustment is
    expressed as an interpolation."""
    got = _correlation_adjusted_probability(legs, rho)
    lower, upper = _frechet_bounds(legs)
    assert 0.0 <= got <= 1.0
    assert lower - 1e-12 <= got <= upper + 1e-12, (legs, rho, got, lower, upper)


def test_a_parlay_can_never_beat_its_likeliest_leg():
    """The Frechet upper bound, and the sanity check a reader will want."""
    legs = [0.9, 0.3]
    assert _correlation_adjusted_probability(legs, 1.0) <= 0.3 + 1e-12


def test_mutually_exclusive_shaped_legs_can_reach_zero():
    legs = [0.4, 0.4]
    lower, _ = _frechet_bounds(legs)
    assert lower == 0.0
    assert _correlation_adjusted_probability(legs, -1.0) >= 0.0


# --- the heuristic's authority is capped -------------------------------------


def test_the_magnitude_is_CAPPED_because_the_score_is_not_a_coefficient():
    """`correlation_score` sums categorical flags. It is trusted for its sign
    and only partly for its size, so a large score cannot swing the price to
    the extreme."""
    legs = [0.5, 0.5]
    at_cap = _correlation_adjusted_probability(legs, _PARLAY_CORRELATION_MAX_SHIFT)
    beyond = _correlation_adjusted_probability(legs, 1.0)
    assert at_cap == pytest.approx(beyond, abs=1e-12)
    _, upper = _frechet_bounds(legs)
    assert beyond < upper, "an uncapped heuristic would reach the comonotone bound"


def test_a_single_leg_is_untouched():
    """Nothing to correlate with."""
    for rho in (-1.0, 0.0, 1.0):
        assert _correlation_adjusted_probability([0.62], rho) == pytest.approx(0.62, abs=1e-12)
