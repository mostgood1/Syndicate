"""A three-way market's other side is not the negation of the home side.

Measured on the served shortlist 2026-08-21, soccer h2h, 49 rows (23 away,
13 draw took the negation branch):

    RC Lens v Auxerre, away:  published +1.63  TRUE -1.65   SIGN INVERTED
    Orlando v Real Salt Lake: published +9.47  TRUE +6.83
    Arsenal v Coventry, draw: published +0.16  TRUE +0.18
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.layer2_board import _model_edge_for

#: A sim count large enough that the 2-sigma precision bar is ~0.07 pp, so the
#: per-side ARITHMETIC below is measured without the gate interfering. The two
#: properties are deliberately separated: these rows exist to pin the SIGN and
#: MAGNITUDE of a three-way edge, and folding a precision question into them
#: would blunt the guard on the inversion they were written for. The gate gets
#: its own block at the production sim count, at the bottom of this file.
PRECISE = 1_000_000

#: What production actually runs, measured 2026-09-06 from quantisation: all 114
#: win probabilities served by the four league card APIs are exact multiples of
#: 1/400, and no smaller n fits.
PRODUCTION_SIMS = 400


def _three_way(model_home, draw, away, fair_home, edge_home, sims=PRECISE):
    """A soccer h2h row's projection block, home-framed as production emits it.

    `sims_run` IS PART OF THE SHAPE NOW.
    `soccer_projections._probability_projection` carries it from the artifact's
    own `simulations`, and without it `price_moneyline` refuses the row by
    `REASON_UNUSABLE_SIMS` -- correctly, since a `k/n` with no `n` has no
    interval. A fixture that omitted it would exercise the refusal path while
    looking like it tested the arithmetic.
    """
    projection = {
        "basis": "win_probability",
        "side": "home",
        "model_prob_over": model_home,
        "draw_probability": draw,
        "away_probability": away,
        "market_fair_prob_over": fair_home,
        "edge_vs_market_pct": edge_home,
    }
    if sims is not None:
        projection["sims_run"] = sims
    return {"projection": projection}


# (label, model h/d/a, fair_home, edge_home, row side, this side's fair, TRUE edge)
REAL_ROWS = [
    ("RC Lens v Auxerre", 0.595, 0.25, 0.155, 0.6113, -1.63, "away", 0.1715, -1.65),
    ("Orlando v Real Salt Lake", 0.41, 0.24, 0.35, 0.5047, -9.47, "away", 0.2817, +6.83),
    ("Arsenal v Coventry", 0.79, 0.14, 0.07, 0.7916, -0.16, "draw", 0.1382, +0.18),
    ("Charlotte v DC United", 0.585, 0.23, 0.185, 0.5336, 5.14, "away", 0.2375, -5.25),
]


@pytest.mark.parametrize("label,mh,md,ma,fh,eh,side,fair,expected", REAL_ROWS)
def test_true_per_side_edge_on_real_rows(label, mh, md, ma, fh, eh, side, fair, expected):
    got = _model_edge_for(_three_way(mh, md, ma, fh, eh), side, fair)
    assert got == pytest.approx(expected, abs=0.02), label


def test_the_sign_inversion_is_gone():
    """The row that made this worth fixing: published +1.63 on a side the model
    dislikes by 1.65 points."""
    row = _three_way(0.595, 0.25, 0.155, 0.6113, -1.63)
    got = _model_edge_for(row, "away", 0.1715)
    assert got < 0, f"model dislikes this side; got {got}"
    assert got != pytest.approx(1.63, abs=0.01)


def test_home_side_is_untouched():
    """No negation branch, so the published value must pass straight through."""
    row = _three_way(0.3675, 0.225, 0.4075, 0.2552, 11.23)
    assert _model_edge_for(row, "home", 0.2548) == 11.23


def test_two_way_market_still_negates():
    """MLB/WNBA have no draw leg; there P(away) = 1 - P(home) makes the identity
    exact, and that behaviour must be bit-for-bit unchanged."""
    row = {"projection": {"side": "home", "edge_vs_market_pct": 4.2}}
    assert _model_edge_for(row, "away", 0.4) == -4.2
    assert _model_edge_for(row, "home", 0.6) == 4.2


def test_three_way_without_a_fair_is_dropped_not_negated():
    """Falling back to the two-way identity is how this bug would survive its
    own fix."""
    row = _three_way(0.595, 0.25, 0.155, 0.6113, -1.63)
    assert _model_edge_for(row, "away", None) is None


def test_unknown_side_on_a_three_way_market_is_dropped():
    row = _three_way(0.595, 0.25, 0.155, 0.6113, -1.63)
    assert _model_edge_for(row, "over", 0.1715) is None


def test_implausible_direct_edge_is_dropped_not_clamped():
    """Same rule the bound already applied to the published edge: a wrong answer
    wearing a plausible one's clothes is worse than none."""
    row = _three_way(0.99, 0.005, 0.005, 0.10, 1.0)
    assert _model_edge_for(row, "away", 0.90) is None


# --------------------------------------------------------------------------
# THE PRECISION GATE, at the sim count production actually runs.
#
# These same four rows are the before/after measurement. At n=400 the 2-sigma
# bar is 3.5-4.8 pp across their range, and a soccer moneyline disagreement is
# usually smaller than that -- so most of what this branch used to publish was
# inside its own Monte-Carlo noise. Refusal is the correct outcome, not a
# regression: a withheld row falls back to EV alone, which cannot pick a side
# but also cannot invert one.
# --------------------------------------------------------------------------


PRODUCTION_VERDICTS = [
    # label, model h/d/a, fair_home, edge_home, side, this side's fair, priced?
    ("RC Lens v Auxerre", 0.595, 0.25, 0.155, 0.6113, -1.63, "away", 0.1715, False),
    ("Orlando v Real Salt Lake", 0.41, 0.24, 0.35, 0.5047, -9.47, "away", 0.2817, True),
    ("Arsenal v Coventry", 0.79, 0.14, 0.07, 0.7916, -0.16, "draw", 0.1382, False),
    ("Charlotte v DC United", 0.585, 0.23, 0.185, 0.5336, 5.14, "away", 0.2375, True),
]


@pytest.mark.parametrize("label,mh,md,ma,fh,eh,side,fair,priced", PRODUCTION_VERDICTS)
def test_the_gate_at_the_production_sim_count(label, mh, md, ma, fh, eh, side, fair, priced):
    got = _model_edge_for(_three_way(mh, md, ma, fh, eh, sims=PRODUCTION_SIMS), side, fair)
    if priced:
        assert got is not None, f"{label}: a real disagreement must survive the gate"
    else:
        assert got is None, f"{label}: {got} pp is inside the bar and must be withheld"


def test_a_leg_with_no_sim_count_is_refused_not_priced():
    """`sims_run` absent means no interval, and unknown must not take the
    permissive branch."""
    row = _three_way(0.41, 0.24, 0.35, 0.5047, -9.47, sims=None)
    assert _model_edge_for(row, "away", 0.2817) is None


def test_the_gate_is_reached_off_versus_on():
    """`off != on` on ONE row, so a vacuous branch cannot pass silently."""
    args = (0.41, 0.24, 0.35, 0.5047, -9.47)
    assert _model_edge_for(_three_way(*args, sims=None), "away", 0.2817) is None
    assert _model_edge_for(_three_way(*args, sims=PRODUCTION_SIMS), "away", 0.2817) is not None


def test_a_zero_of_four_hundred_draw_leg_is_priced_off_the_smoothed_estimate():
    """THE CASE THIS GATE EXISTS FOR.

    A draw is a narrow outcome, so `0/400` is ordinary late in a match rather
    than a tail event -- and `refuse_published_certainty` reads `model_prob_over`
    only, so it never looked at this leg. Raw, the edge against a 0.12 fair is a
    flat -12.0 pp off a stated impossibility. Smoothed it is ~-11.5 pp off
    `2/404`, and it clears a ~0.70 pp bar honestly rather than by certainty.

    THE FAIR IS 0.12 AND NOT 0.16 FOR A REASON WORTH KEEPING. At 0.16 the raw
    edge is -16.0 and the smoothed one -15.5, and BOTH exceed
    `_MODEL_EDGE_MAX_POINTS` (15.0), so the row is dropped by the cap and the
    gate never decides it. That cap has been quietly absorbing the most extreme
    certainties all along -- which is why this defect survived: its worst cases
    were invisible, and everything between the bar and the cap was published.
    """
    row = _three_way(0.70, 0.0, 0.30, 0.68, 2.0, sims=PRODUCTION_SIMS)
    got = _model_edge_for(row, "draw", 0.12)
    assert got is not None
    assert got != pytest.approx(-12.0, abs=0.01), "that would be the raw certainty"
    assert -12.0 < got < -11.0
