"""The MLB ladder must not publish an EXACT `overLineProb` beside a real line.

`#646`(d). `ladders_build._dist_stats` computes P(over the market line) straight
off the simulated histogram. A degenerate histogram -- the shape the dead
`strikeouts` field produced for months, `{0: n_sims}` -- yields exactly `0.0`,
which is the value `probability_refusal.CERTAINTY_REFUSED` exists to reject and
the sign that module's docstring calls the dangerous one: P(over) = 0 states the
UNDER is a certainty against whatever the book pays.

TWO THINGS THIS MUST NOT BREAK, both pinned below:

1. `overLineProb` was ALREADY `None` for "no market line", and `_dist_stats`'s
   docstring says a zero probability and an absent market are DIFFERENT FACTS
   the card renders differently. A bare `None` would collapse them, so the
   refusal is LABELLED the way `refuse_published_certainty` labels its own.
2. `_dist_ladder` emits `{total: 0, hitProb: 1.0}`, and that 1.0 is P(X >= 0) --
   trivially and CORRECTLY certain. It is NOT a false certainty and must survive.
"""

from __future__ import annotations

import pytest

from syndicate.features.mlb.ladders_build import _dist_ladder, _dist_stats
from syndicate.features.shared.probability_refusal import CERTAINTY_REFUSED

DEGENERATE = {"0": 1000}
HEALTHY = {"0": 264, "1": 370, "2": 249, "3": 86, "4": 31}


def test_degenerate_over_line_prob_is_refused_not_published():
    """REACHABILITY: fails on the unfixed code, which returns 0.0."""
    out = _dist_stats(DEGENERATE, 0.5)
    assert out["overLineProb"] is None, (
        "a degenerate histogram published overLineProb=%r beside a real line; "
        "an exact certainty is a statement about the SAMPLE, not the world"
        % (out["overLineProb"],)
    )


def test_the_refusal_is_labelled_so_absence_and_zero_stay_distinct():
    """A bare None would collapse 'no market line' into 'refused certainty'."""
    refused = _dist_stats(DEGENERATE, 0.5)
    no_line = _dist_stats(DEGENERATE, None)

    assert refused.get("overLineProbRefused") == "exact_certainty"
    assert refused.get("overLineProbRefusedValue") == 0.0
    # the no-line case is blank for its OWN reason and carries no refusal label
    assert no_line["overLineProb"] is None
    assert "overLineProbRefused" not in no_line
    assert refused != no_line, "refused and absent must remain distinguishable"


def test_certain_over_is_refused_too():
    """1.0 is refused as well -- CERTAINTY_REFUSED is both ends, not just 0.0."""
    out = _dist_stats({"5": 1000}, 0.5)   # every sim clears the line
    assert out["overLineProb"] is None
    assert out["overLineProbRefusedValue"] == 1.0
    assert 1.0 in CERTAINTY_REFUSED


def test_healthy_distribution_is_untouched():
    """CONTROL: a real probability must survive, or the fix is a blanket nuke."""
    out = _dist_stats(HEALTHY, 0.5)
    assert out["overLineProb"] == pytest.approx(0.736)
    assert "overLineProbRefused" not in out


def test_mode_and_simcount_survive_the_refusal():
    """Only the probability goes. The sim really did produce the rest."""
    out = _dist_stats(DEGENERATE, 0.5)
    assert out["mode"] == 0
    assert out["simCount"] == 1000


def test_absent_line_still_returns_none_without_a_label():
    out = _dist_stats(HEALTHY, None)
    assert out["overLineProb"] is None
    assert "overLineProbRefused" not in out


def test_ladder_rung_probability_of_one_is_NOT_refused():
    """`{total: 0, hitProb: 1.0}` is P(X >= 0). Correctly certain -- must stay.

    This is the value a blanket certainty refusal on this surface would
    wrongly blank, which is why the fix is scoped to `overLineProb` alone.
    """
    rungs = _dist_ladder(DEGENERATE)
    assert rungs, "a degenerate dist must still produce its one rung"
    assert rungs[0]["total"] == 0
    assert rungs[0]["hitProb"] == 1.0

    healthy_rungs = _dist_ladder(HEALTHY)
    assert healthy_rungs[0]["hitProb"] == 1.0, "P(X >= 0) is always 1.0"


def test_a_bool_in_the_histogram_is_not_silently_rewritten():
    """`False == 0.0` in Python. An empty/garbage dist must not fake a refusal."""
    out = _dist_stats({}, 0.5)
    assert out["overLineProb"] is None
    assert "overLineProbRefused" not in out, (
        "an EMPTY histogram is 'the sim said nothing', not 'the sim was certain'"
    )
