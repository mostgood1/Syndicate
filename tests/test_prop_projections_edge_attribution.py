"""Every blank `Edge` on a projected row must carry a reason.

WHY THIS FILE EXISTS. `attach_projections` had two exits that set
`edge_vs_market_pct = None`: the live-policy one, which stated a reason, and the
fallthrough, which stated nothing -- the key was ABSENT, not null. Measured on
production 2026-08-16, `/api/board/layer1?sport=mlb`: **284 of 2,843 served rows**
took the silent exit, 223 of them `batter_home_runs`, every one carrying a
`model_prob_over` and a null `market_fair_prob_over`. From the payload alone
those were indistinguishable from a broken join.

The refusal is correct and is not what changed -- `_no_vig_over_probability`
returns None rather than de-vigging a single leg (`#238`). Only the attribution
was missing, against a standard the repo had already written down in
`live_gameline_join`: "Every zero must be diagnosable by reason."

THE TESTS ARE BUILT FROM THE PRODUCTION POPULATIONS, not from invented shapes:
each case below is the served row structure of a population that was actually
counted on 2026-08-16, and the counts are in the docstrings so a future reader
can tell a fixture that models production from one that models an assumption.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.prop_projections import (
    _edge_unavailable_reason,
    _no_vig_over_probability,
)


def test_one_sided_prop_names_the_missing_leg():
    """MLB `batter_home_runs` 0.5 -- 223 of the 284 silent rows on 2026-08-16.

    One quoted side, a real `model_prob_over`, no fair. This is the population
    the whole change exists for.
    """
    row = {
        "market": "batter_home_runs",
        "line": 0.5,
        "sides": ["over"],
        "consensus": {"over": 320},
        "player_name": "Matt Olson",
    }
    assert _no_vig_over_probability(row) is None, "guard: this row must have no fair"
    assert (
        _edge_unavailable_reason(row, model_prob=0.2087, fair=None)
        == "one-sided market: no two-sided fair to price against"
    )


def test_means_only_projection_blames_the_model_not_the_book():
    """The `#263` ladder's WNBA rung: means, no distribution.

    THE DIRECTION IS THE POINT. A missing `model_prob_over` is a modelling gap;
    a missing `fair` is the market not quoting a second side. Reporting a
    means-only row as "one-sided market" would send the reader to the quote
    join for a problem the sim owns -- and this row IS two-sided, so the
    one-sided string would also be factually false.
    """
    row = {
        "market": "player_points",
        "line": 15.5,
        "sides": ["over", "under"],
        "consensus": {"over": -110, "under": -110},
    }
    reason = _edge_unavailable_reason(row, model_prob=None, fair=0.5)
    assert "mean with no distribution" in reason
    assert "one-sided" not in reason


def test_means_only_wins_even_when_the_market_is_also_one_sided():
    """Both terms missing at once -- the model reason must still lead.

    Without an explicit order this is whichever branch happens to be written
    first, and the two callers disagree about which subsystem is at fault.
    """
    row = {"market": "player_points", "sides": ["over"], "consensus": {"over": -110}}
    assert "mean with no distribution" in _edge_unavailable_reason(
        row, model_prob=None, fair=None
    )


def test_three_way_missing_draw_is_not_called_one_sided():
    """A 3-way h2h whose draw price failed to arrive.

    `soccer_projections` records why this case is separated: "one-sided market"
    would be an actively wrong description of an h2h row, and a wrong reason is
    worse than a blank one because it sends the next reader to the wrong
    subsystem.
    """
    row = {
        "market": "h2h_3_way",
        "sides": ["home", "away", "draw"],
        "consensus": {"home": 150, "away": 190},
    }
    assert _no_vig_over_probability(row) is None
    reason = _edge_unavailable_reason(row, model_prob=0.4, fair=None)
    assert reason == "3-way market: incomplete price set, no fair to price against"


def test_two_sided_but_a_side_has_no_consensus_price_says_which_side():
    """Quoted on both sides, priced on one -- a quote-join fact, not a book one."""
    row = {
        "market": "batter_hits",
        "sides": ["over", "under"],
        "consensus": {"over": -115, "under": None},
    }
    assert _no_vig_over_probability(row) is None
    reason = _edge_unavailable_reason(row, model_prob=0.55, fair=None)
    assert "no consensus price on under" in reason
    assert "one-sided" not in reason


def test_both_terms_present_reports_the_producer_not_a_missing_term():
    """3 WNBA `h2h` rows on 2026-08-16, `source: "wnba_game_cards"`.

    Both terms present and no edge served, because that producer never runs the
    edge step. The reason must NOT claim a missing term -- there isn't one.
    """
    row = {
        "market": "h2h",
        "sides": ["away", "home"],
        "consensus": {"away": 174, "home": -211},
        "away_team": "Portland Fire",
        "home_team": "Phoenix Mercury",
    }
    assert _no_vig_over_probability(row) is not None, "guard: this row HAS a fair"
    reason = _edge_unavailable_reason(row, model_prob=0.9673, fair=0.6502)
    assert "producer does not compute" in reason
    assert "one-sided" not in reason and "mean with no distribution" not in reason


@pytest.mark.parametrize(
    "row,model_prob,fair",
    [
        ({"market": "batter_home_runs", "sides": ["over"], "consensus": {"over": 320}}, 0.2, None),
        ({"market": "player_points", "sides": ["over", "under"], "consensus": {}}, None, None),
        ({"market": "h2h_3_way", "sides": ["home", "away", "draw"], "consensus": {}}, 0.4, None),
        ({"market": "h2h", "sides": ["home", "away"], "consensus": {"home": -110, "away": -110}}, 0.5, 0.5),
        ({}, None, None),
    ],
)
def test_always_returns_a_non_empty_reason(row, model_prob, fair):
    """The one property the caller depends on.

    The caller writes this straight into `edge_unavailable_reason`. An empty
    string would serve a key that reads as attributed and says nothing -- worse
    than the absent key this change removed, because it would also satisfy a
    presence check.
    """
    reason = _edge_unavailable_reason(row, model_prob=model_prob, fair=fair)
    assert isinstance(reason, str) and reason.strip()
