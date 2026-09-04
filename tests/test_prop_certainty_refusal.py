"""A simulated frequency of exactly 0 or 1 is not a probability. `#624` step 1.

Step 1 asks for "per-(market, line) isotonic/Platt on `model_prob_over` + HARD
REFUSAL OF p in {0.0, 1.0}". The calibration shipped 2026-09-01 (`f03ef38a`);
the refusal did not.

MEASURED ON THE SERVED BOARD 2026-09-04, 872 MLB rows carrying `model_prob_over`:

    EXACT 0.0: 0    EXACT 1.0: 1    (0, 0.01): 9    (0.99, 1.0): 0

    Lake Bachar, outs, line 6.5   model_prob_over 1.0
                                  market_fair_prob_over 0.4061

A +59.4 point edge by construction, top of any ranking. **It caused no harm only
because an unrelated guard suppressed it** -- `edge_unavailable_reason: "game is
final: the market is settled"`. A pregame row of the same shape is priced.

N sims can bound a probability and can never zero it, so the refusal is about
what the estimator is entitled to claim, not about tuning.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.prop_projections import (  # noqa: E402
    PropProjectionIndex,
    _dist_prob_over,
)


def test_every_sim_over_the_line_is_REFUSED_not_published_as_one():
    """The production row's shape: 10 of 10 sims above the line."""
    assert _dist_prob_over({str(v): 1 for v in range(10, 20)}, 6.5) is None


def test_every_sim_under_the_line_is_REFUSED_not_published_as_zero():
    """A 0.0 is the same artefact mirrored, and worse downstream: it prices the
    UNDER at a certainty."""
    assert _dist_prob_over({str(v): 1 for v in range(0, 5)}, 6.5) is None


def test_a_NEAR_certainty_still_publishes():
    """The refusal is exact, not a band. 0.9 is a real reading from a real
    distribution and must survive -- narrowing this to a clamp would discard
    signal the sim genuinely has."""
    dist = {str(v): 1 for v in range(10, 19)}
    dist["3"] = 1
    p = _dist_prob_over(dist, 6.5)
    assert p == 0.9


def test_it_REFUSES_rather_than_CLAMPS():
    """Clamping to 0.999 would keep the row and publish a number the sim did not
    produce -- the fabricated edge this file forbids elsewhere. The contract is
    None, so the row counts as unprojectable rather than as coverage."""
    assert _dist_prob_over({"9": 5}, 6.5) is None


def test_the_refusal_reaches_the_INDEX_and_keeps_the_MEAN():
    """`project()` must not hand a certainty out -- a refusal that only holds in
    the helper is a refusal the board never sees.

    IT KEEPS THE PROJECTION AND DROPS ONLY THE PROBABILITY, and that shape is
    deliberate rather than incidental. The sim genuinely has a MEAN here (14.5
    outs); what it cannot state is P(over 6.5) from a sample that never went
    below. So the row stays VISIBLE and becomes UNPRICEABLE -- the same contract
    soccer corners got: `edge_vs_market_pct` needs `model_prob_over`, so a null
    probability is what makes the row unbettable, and dropping the mean too
    would discard a number the sim did produce.
    """
    index = PropProjectionIndex()
    index.ingest_game(
        {"pitcher_props": {"111": {"outs_dist": {str(v): 1 for v in range(10, 20)},
                                   "outs_mean": 14.5}}},
        pitcher_names={"111": "Lake Bachar"},
    )
    refused = index.project(player_name="Lake Bachar", market="outs", line=6.5)
    assert refused is not None, "the mean is real and must survive"
    assert refused["model_prob_over"] is None, "the certainty must not be published"
    assert refused["projected"] == 14.5

    # ...and the same pitcher on a line the distribution straddles still works,
    # so this refuses the CERTAINTY, not the player or the market.
    straddled = index.project(player_name="Lake Bachar", market="outs", line=14.5)
    assert straddled is not None and 0.0 < straddled["model_prob_over"] < 1.0


def test_an_empty_distribution_is_still_None():
    assert _dist_prob_over({}, 6.5) is None
    assert _dist_prob_over({"5": 0}, 6.5) is None
