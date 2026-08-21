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


def _three_way(model_home, draw, away, fair_home, edge_home):
    """A soccer h2h row's projection block, home-framed as production emits it."""
    return {
        "projection": {
            "basis": "win_probability",
            "side": "home",
            "model_prob_over": model_home,
            "draw_probability": draw,
            "away_probability": away,
            "market_fair_prob_over": fair_home,
            "edge_vs_market_pct": edge_home,
        }
    }


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
