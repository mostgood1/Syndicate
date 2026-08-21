"""Soccer totals price at the line the BOOKS offer, not only at 2.5.

Measured on production 2026-08-21: Marseille v Strasbourg was priced at 3.0 and
3.5 only, so its card and both boards carried no market total at all -- while
`scoreline_probabilities` sat in the same payload with the full distribution.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import soccer_projections as sp


# The real 2026-08-21 ligue_1 scoreline distribution, truncated to its head and
# closed with the residual so it still sums to 1.0.
def _real_scorelines():
    head = {
        "1-1": 0.1375, "2-0": 0.0925, "2-1": 0.08, "1-2": 0.0775,
        "1-0": 0.0725, "3-0": 0.055, "3-1": 0.045, "0-1": 0.0425,
    }
    head["0-0"] = round(1.0 - sum(head.values()), 4)
    return head


def test_out_of_support_line_refuses_rather_than_claiming_zero():
    """A line past everything the sim produced would sum to a hard 0.0, which
    reads as certainty the model never expressed. That is sim granularity, not
    knowledge, so it must fall through to the mean instead."""
    assert sp._total_prob_from_scorelines(_real_scorelines(), 99) is None


@pytest.mark.parametrize("bad", [None, {}, "3-1", 17])
def test_unusable_distribution_returns_none(bad):
    assert sp._total_prob_from_scorelines(bad, 2.5) is None


def test_non_normalised_distribution_is_refused():
    """A partial dict would silently price against missing mass."""
    assert sp._total_prob_from_scorelines({"1-0": 0.2, "0-0": 0.3}, 2.5) is None


def test_integer_line_reports_push_mass_separately():
    """At 3.0 a 3-goal match is void, not a loss. P(over) and P(under) do not
    sum to 1 and the push must be visible, not swallowed."""
    scorelines = _real_scorelines()
    over, push = sp._total_prob_from_scorelines(scorelines, 3.0)
    # 2-1, 1-2 and 3-0 are the three-goal scorelines in this head.
    assert push == pytest.approx(0.08 + 0.0775 + 0.055, abs=1e-9)
    # Derived independently of the implementation, so the test can fail.
    expected_over = sum(
        v for k, v in scorelines.items() if sum(int(x) for x in k.split("-")) > 3
    )
    assert over == pytest.approx(expected_over, abs=1e-9)


def test_half_line_has_no_push():
    _, push = sp._total_prob_from_scorelines(_real_scorelines(), 3.5)
    assert push == 0.0


def test_derivation_reproduces_the_published_2_5_number():
    """The transformation is exact, not an approximation: summing the arm above
    2.5 must equal what the sim published as `over_2_5_probability`. If these
    ever diverge, one of the two is not describing the same simulation."""
    full = {
        "1-1": 0.1375, "2-0": 0.0925, "2-1": 0.08, "1-2": 0.0775, "1-0": 0.0725,
        "3-0": 0.055, "3-1": 0.045, "0-1": 0.0425, "0-0": 0.0425, "2-2": 0.06,
        "3-2": 0.03, "4-0": 0.025, "4-1": 0.02, "0-2": 0.03, "1-3": 0.025,
        "2-3": 0.02, "5-0": 0.01, "4-2": 0.0125, "0-3": 0.0125, "3-3": 0.01,
        "5-1": 0.0075, "1-4": 0.0075, "2-4": 0.005, "6-0": 0.0025,
    }
    total = sum(full.values())
    full["7-0"] = round(1.0 - total, 6)
    over, push = sp._total_prob_from_scorelines(full, 2.5)
    assert push == 0.0
    expected = sum(v for k, v in full.items() if sum(int(x) for x in k.split("-")) > 2.5)
    assert over == pytest.approx(expected, abs=1e-9)


def test_2_5_still_comes_from_the_published_summary_not_the_derivation():
    """A fix that silently restates every EXISTING row has a blast radius nobody
    can bound. 2.5 must keep returning the summary's own number, so the
    published value wins even when the two disagree."""
    match = {
        "total_distribution": {"mean": 3.08, "over_2_5_probability": 0.5775},
        # Deliberately inconsistent with the summary above.
        "scoreline_probabilities": {"0-0": 0.5, "9-9": 0.5},
    }
    index = sp.SoccerProjectionIndex()
    index.by_teams[("marseille", "strasbourg")] = match
    index.matches = 1
    row = {
        "market": "totals", "line": 2.5, "sport": "soccer",
        "home_team": "Marseille", "away_team": "Strasbourg",
    }
    sp.attach_soccer_projections([row], index)
    assert row["projection"]["basis"] == "over_2_5_probability"
    assert row["projection"]["model_prob_over"] == 0.5775
