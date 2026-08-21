"""The live totals lens: price any line off the resumed sim's own shape.

The live projection previously published `over_2_5_probability` and nothing
else, so the live board could answer 2.5 and no other line -- least useful
exactly when the live tier matters most, since a 2-0 at 60' is quoted at 3.5
and 4.5.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.soccer.features.live_lens import LiveMatchProjection


def _dist():
    # 2-0 at 60': the remaining-goals mass sits at 2 and 3 total.
    return {"2-0": 0.40, "3-0": 0.25, "2-1": 0.20, "3-1": 0.10, "4-1": 0.05}


def test_totals_histogram_sums_scorelines_that_share_a_total():
    totals, _ = src._histograms_from_scorelines(_dist())
    # 3-0 and 2-1 are both three goals.
    assert totals[3.0] == pytest.approx(0.45)
    assert totals[2.0] == pytest.approx(0.40)
    assert sum(totals.values()) == pytest.approx(1.0)


def test_margin_histogram_is_home_positive():
    """`price_distribution_market` documents that the pregame spread rule only
    transfers under a home-positive frame; backwards produced 19-28 point
    phantom edges on 2026-08-08."""
    _, margins = src._histograms_from_scorelines(_dist())
    assert margins[2.0] == pytest.approx(0.40 + 0.10)   # 2-0, 3-1
    assert margins[3.0] == pytest.approx(0.25 + 0.05)   # 3-0, 4-1
    assert margins[1.0] == pytest.approx(0.20)          # 2-1
    assert all(m >= 0 for m in margins), "no away-positive key in this fixture"


def test_any_line_is_now_priceable_not_just_2_5():
    """The point of the lens. Over 3.5 must be answerable."""
    from syndicate.features.shared.prop_projections import _dist_prob_over
    totals, _ = src._histograms_from_scorelines(_dist())
    assert _dist_prob_over(totals, 3.5) == pytest.approx(0.15)   # 4-1 only
    assert _dist_prob_over(totals, 2.5) == pytest.approx(0.60)   # 3+ goals


def test_a_non_normalised_distribution_is_refused_not_priced():
    totals, margins = src._histograms_from_scorelines({"1-0": 0.2, "2-0": 0.3})
    assert totals == {} and margins == {}


@pytest.mark.parametrize("bad", [None, {}, "2-0", 7])
def test_unusable_input_yields_no_shape(bad):
    assert src._histograms_from_scorelines(bad) == ({}, {})


def test_projection_publishes_the_scoreline_distribution():
    """Reachability: the field must survive to_dict(), or the board sees {}."""
    p = LiveMatchProjection(
        simulations=100, home_win_probability=0.5, draw_probability=0.3,
        away_win_probability=0.2, projected_final_home_goals=1.5,
        projected_final_away_goals=1.0, projected_final_total=2.5,
        over_2_5_probability=0.5, both_teams_scored_probability=0.6,
        projected_home_corners=5.0, projected_away_corners=4.0,
        projected_total_corners=9.0, home_red_card_applied=False,
        away_red_card_applied=False, scoreline_probabilities={"2-0": 1.0},
    )
    assert p.to_dict()["scoreline_probabilities"] == {"2-0": 1.0}


def test_absent_distribution_degrades_to_no_shape_not_a_wrong_number():
    """An older lens written before this field existed must refuse, not guess."""
    totals, margins = src._histograms_from_scorelines(None)
    assert totals == {} and margins == {}
