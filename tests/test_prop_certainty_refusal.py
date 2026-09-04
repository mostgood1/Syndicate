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

from syndicate.features.shared.prop_projections import (
    _refuse_published_certainty,  # noqa: E402
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


# ---------------------------------------------------------------------------
# THE CHOKE POINT. `_dist_prob_over` is one of FOUR producers of
# `model_prob_over`; a refusal sited there caught 1 of the 17 certainties on the
# 2026-09-04T04:28:48Z board. These pin the other three.
# ---------------------------------------------------------------------------


def _hr_rung_index(prob):
    """An index whose HR-rung probability is whatever the artifact stored.

    This path NEVER touches a distribution -- it reads `p_hr_2plus` straight
    off `hitter_hr_likelihood_all` -- so `_dist_prob_over` cannot see it.
    """
    index = PropProjectionIndex()
    index.ingest_game({
        "hitter_hr_likelihood_all": {"overall": [
            {"name": "Andrew Vaughn", "hr_mean": 0.21,
             "p_hr_1plus": 0.19, "p_hr_2plus": prob, "p_hr_3plus": prob},
        ]},
    })
    return index


def test_the_hr_RUNG_producer_is_refused_too():
    """16 of the 17 certainties on the real board came from here."""
    got = _hr_rung_index(0.0).project(
        player_name="Andrew Vaughn", market="batter_home_runs", line=1.5)
    assert got is not None, "the mean is real; only the certainty goes"
    assert got["model_prob_over"] is None
    assert got["projected"] == 0.21


def test_a_real_rung_probability_still_passes():
    """Off != on in the other direction: this refuses 0.0, not small."""
    got = _hr_rung_index(0.004).project(
        player_name="Andrew Vaughn", market="batter_home_runs", line=1.5)
    assert got is not None and got["model_prob_over"] == 0.004


def test_zero_is_refused_not_only_one():
    """`model_prob_over = 0.0` is the DANGEROUS sign -- it says the over is
    impossible, making the under a 100%-confidence bet against any price."""
    assert _refuse_published_certainty({"model_prob_over": 0.0})["model_prob_over"] is None
    assert _refuse_published_certainty({"model_prob_over": 1.0})["model_prob_over"] is None


def test_it_does_not_touch_anything_else():
    payload = {"model_prob_over": 0.0, "projected": 4.2, "source": "x", "basis": "hr_2plus"}
    out = _refuse_published_certainty(payload)
    assert out["projected"] == 4.2 and out["source"] == "x" and out["basis"] == "hr_2plus"


def test_None_passes_through_as_None():
    """`None` is the honest 'no projection' and must not become a dict."""
    assert _refuse_published_certainty(None) is None


def test_booleans_are_not_probabilities():
    """`False == 0.0` and `True == 1.0` in Python. A bool in this field is a
    different bug, and silently rewriting it to None would hide it."""
    out = _refuse_published_certainty({"model_prob_over": False})
    assert out["model_prob_over"] is False


def test_the_uncensored_path_still_produces_the_certainty():
    """OFF != ON. If `_project_uncensored` had stopped producing 1.0 for its own
    reasons, every test above would pass while the censor did nothing."""
    index = PropProjectionIndex()
    index.ingest_game(
        {"pitcher_props": {"111": {"outs_dist": {str(v): 1 for v in range(10, 20)},
                                   "outs_mean": 14.5}}},
        pitcher_names={"111": "Lake Bachar"},
    )
    raw = index._project_uncensored(player_name="Lake Bachar", market="outs", line=6.5)
    assert raw is not None and raw["model_prob_over"] is None, (
        "the helper-level refusal is the FIRST line of defence and still holds")
    rung = _hr_rung_index(0.0)
    raw_rung = rung._project_uncensored(
        player_name="Andrew Vaughn", market="batter_home_runs", line=1.5)
    assert raw_rung["model_prob_over"] == 0.0, (
        "the rung producer DOES emit an exact 0.0 -- if this ever stops being "
        "true, the censor test above proves nothing")
