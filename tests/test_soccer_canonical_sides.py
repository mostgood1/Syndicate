"""Soccer quotes its legs by TEAM NAME, and the shared de-vig cannot read that.

Measured on production 2026-09-06: soccer live spreads carried 377 ledger rows,
`model_home_win_prob` set on 354 and `market_fair_prob` set on ZERO, so 354
refused `no_two_sided_market_price`. The model had an opinion on 94% of them and
it was thrown away for want of a market side.

`_no_vig_over_probability` resolves legs by label and knows two vocabularies --
`over/under` and `home/away`. Soccer's odds artifact quotes a third: `Arsenal`,
`Sunderland`, `Crystal Palace`, with `Draw` as the third h2h leg.

NOT a three-way problem. The failing spreads are ASIAN HANDICAP -- production
lines include `0.25` and `-0.75`, quarter lines that only exist in AH, whose
split stake is exactly what removes the draw.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.prop_projections import (  # noqa: E402
    _no_vig_over_probability,
)
from syndicate.features.shared.soccer_projections import (  # noqa: E402
    _canonical_side_view,
)

TEAMS = {"sport": "soccer", "home_team": "Arsenal", "away_team": "Sunderland"}


def test_team_name_spreads_devig_NOW_RESOLVES():
    """The production case: two legs labelled by club, Asian handicap."""
    row = {**TEAMS, "sides": ["Arsenal", "Sunderland"],
           "consensus": {"Arsenal": -140, "Sunderland": 115}}
    assert _no_vig_over_probability(row) is None, "precondition: today it fails"
    fair = _no_vig_over_probability(_canonical_side_view(row))
    assert fair is not None and 0.0 < fair < 1.0, fair


def test_the_draw_leg_is_PASSED_THROUGH_and_counted():
    """Soccer's genuine three-way market is h2h. The draw must stay in the
    denominator -- omitting it makes the fair price err in the bettor's favour,
    which the shared helper calls the most dangerous direction."""
    row = {**TEAMS, "sides": ["Arsenal", "Draw", "Sunderland"],
           "consensus": {"Arsenal": -140, "Draw": 260, "Sunderland": 380}}
    view = _canonical_side_view(row)
    assert "Draw" in view["sides"]
    three = _no_vig_over_probability(view)
    two = _no_vig_over_probability({**TEAMS, "sides": ["home", "away"],
                                    "consensus": {"home": -140, "away": 380}})
    # Including the draw MUST lower the home fair probability. If these were
    # equal the draw leg would be decorative.
    assert three is not None and two is not None
    assert three < two, (three, two)


def test_an_already_canonical_row_is_UNTOUCHED():
    """Re-mapping a row the helper can already read is pure risk for no gain."""
    row = {**TEAMS, "sides": ["home", "away"],
           "consensus": {"home": -140, "away": 115}}
    assert _canonical_side_view(row) is row


def test_an_unrecognised_leg_REFUSES_rather_than_half_mapping():
    """A half-resolved market de-vigs across a leg set that does not exist.
    Refusing the whole translation keeps today's behaviour instead of acquiring
    a guessed one."""
    row = {**TEAMS, "sides": ["Arsenal", "Some Other Club"],
           "consensus": {"Arsenal": -140, "Some Other Club": 115}}
    assert _canonical_side_view(row) is row
    assert _no_vig_over_probability(_canonical_side_view(row)) is None


def test_a_row_with_no_team_names_is_UNTOUCHED():
    """Without both teams there is nothing to resolve against, and inventing a
    mapping is how a fair price becomes fiction."""
    row = {"sport": "soccer", "sides": ["Arsenal", "Sunderland"],
           "consensus": {"Arsenal": -140, "Sunderland": 115}}
    assert _canonical_side_view(row) is row


def test_off_is_not_on_the_translation_actually_changes_the_labels():
    """Guards against a version that returns the row unchanged in every case and
    passes every test above by doing nothing."""
    row = {**TEAMS, "sides": ["Arsenal", "Sunderland"],
           "consensus": {"Arsenal": -140, "Sunderland": 115}}
    view = _canonical_side_view(row)
    assert view is not row
    assert view["sides"] == ["home", "away"]
    assert set(view["consensus"]) == {"home", "away"}


# --------------------------------------------------------------------------
# REACHABILITY. Everything above tests the HELPER. My own mutation check caught
# that reverting the CALL SITE left all six green -- the helper was correct and
# provably unreachable, which is the exact "presence is not reachability"
# failure this repo keeps paying for. These go through `_price_against_market`,
# so the wiring is what is under test.
# --------------------------------------------------------------------------
from syndicate.features.shared.soccer_projections import (  # noqa: E402
    _price_against_market,
)

SPREADS_ROW = {
    **TEAMS,
    "market": "spreads",
    "sides": ["Arsenal", "Sunderland"],
    "consensus": {"Arsenal": -140, "Sunderland": 115},
}


def test_the_CALL_SITE_stamps_market_fair_prob_over_for_team_name_sides():
    """The production defect end to end: 354 of 377 spreads rows had a model
    probability and ZERO had a market fair price. This asserts the field the
    live join reads is actually stamped."""
    projection = {"model_prob_over": 0.55}
    _price_against_market(SPREADS_ROW, projection)
    fair = projection.get("market_fair_prob_over")
    assert fair is not None, (
        "market_fair_prob_over is still None -- live_gameline_join refuses this "
        "row as no_two_sided_market_price, which is the whole defect")
    assert 0.0 < float(fair) < 1.0, fair


def test_reverting_the_call_site_would_be_CAUGHT():
    """Companion to the test above, stated as its own case so the intent is
    visible: with the raw row the shared de-vig returns None, so if the call
    site stopped canonicalising, `market_fair_prob_over` would go back to None
    and the test above fails. That is what makes the wiring load-bearing."""
    assert _no_vig_over_probability(SPREADS_ROW) is None
    assert _no_vig_over_probability(_canonical_side_view(SPREADS_ROW)) is not None
