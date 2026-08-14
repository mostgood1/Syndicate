"""`#429` — HRR is Hits+Runs+RBIs, so its mean is derivable when the sim's is dead.

THE DEFECT. The sim writes `hrr_mean: 0.0` for every hitter while writing real
per-player probabilities and real `pa_mean`/`ab_mean`. Measured on
`daily_summary_2026_07_09.json`: `hrr_mean` present on 936 of 936 rows, nonzero
on 0. On the served board the same day, `model_prob_over` carried 75 DISTINCT
values across 88 rows while `projected` was a flat 0.0 — so the row is real and
exactly one field is dead.

WHY DERIVING IS EXACT. Expectation is linear, so E[H+R+RBI] = E[H]+E[R]+E[RBI]
regardless of correlation between the three. They are heavily correlated (a home
run is 1 hit + 1 run + 1 RBI), which would wreck a variance or a probability
derived this way and leaves the mean untouched. Hence the tests below pin that
probabilities are NEVER composed — only means.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.prop_projections import PropProjectionIndex


def _index_with(means: dict, *, bucket="hits_runs_rbis_2plus", row_extra=None):
    """Build an index the way ingest_game would: component means arrive on
    OTHER buckets and are folded into _hitter_means, while the hrr row itself
    carries only its probability and a dead hrr_mean."""
    index = PropProjectionIndex()
    name = "test player"
    row = {"name": "Test Player", "p_hrr_2plus": 0.67, "hrr_mean": 0.0}
    if row_extra:
        row.update(row_extra)
    index._hitters[(name, bucket)] = row
    index._hitter_means[name] = dict(means)
    return index


COMPLETE = {"h_mean": 1.279, "r_mean": 0.53, "rbi_mean": 0.456}   # -> 2.265


def _score(index, *, market="batter_hits_runs_rbis", line=1.5):
    return index.project(player_name="Test Player", market=market, line=line)


# --------------------------------------------------------------------------
# the derivation
# --------------------------------------------------------------------------


def test_dead_hrr_mean_is_replaced_by_the_component_sum():
    out = _score(_index_with(COMPLETE))
    assert out["projected"] == 2.265
    assert out["projected_derived_from"] == "h_mean+r_mean+rbi_mean"


def test_the_derived_value_is_labelled_as_derived():
    """A consumer must be able to tell a reconstructed number from a simulated
    one. An unlabelled derived value is the same class of problem as the 0.0."""
    out = _score(_index_with(COMPLETE))
    assert "projected_derived_from" in out


def test_a_real_hrr_mean_is_never_overridden():
    """If the producer is ever fixed, this code must get out of the way."""
    index = _index_with(COMPLETE)
    index._hitters[("test player", "hits_runs_rbis_2plus")]["hrr_mean"] = 2.10
    out = _score(index)
    assert out["projected"] == 2.1
    assert "projected_derived_from" not in out


# --------------------------------------------------------------------------
# ALL THREE OR NOTHING — a partial sum is worse than a blank
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["h_mean", "r_mean", "rbi_mean"])
def test_any_missing_component_yields_a_blank_not_a_partial_sum(missing):
    means = {k: v for k, v in COMPLETE.items() if k != missing}
    out = _score(_index_with(means))
    assert out["projected"] is None, "a partial sum looks like a real projection and is too low"
    assert "projected_derived_from" not in out


def test_all_components_zero_does_not_swap_one_fabricated_zero_for_another():
    out = _score(_index_with({"h_mean": 0.0, "r_mean": 0.0, "rbi_mean": 0.0}))
    assert out["projected"] is None


def test_no_components_at_all_yields_a_blank():
    out = _score(_index_with({}))
    assert out["projected"] is None


# --------------------------------------------------------------------------
# scope: means only, this market only
# --------------------------------------------------------------------------


def test_probability_is_never_derived_only_the_mean():
    """The components are heavily correlated, so composing probabilities from
    them would be wrong. model_prob_over must still come from the sim."""
    out = _score(_index_with(COMPLETE))
    assert out["model_prob_over"] == 0.67


def test_other_markets_are_untouched():
    """Only HRR is a summation of primitives. batter_hits must not acquire a
    derived value if its own mean is dead."""
    index = PropProjectionIndex()
    index._hitters[("test player", "hits_2plus")] = {"name": "Test Player", "p_h_2plus": 0.4, "h_mean": 0.0}
    index._hitter_means["test player"] = dict(COMPLETE)
    out = index.project(player_name="Test Player", market="batter_hits", line=1.5)
    assert out["projected"] is None or out["projected"] == 0.0
    assert "projected_derived_from" not in out


def test_the_magnitude_matches_the_market():
    """Sanity, and the check that would catch a wrong-field or wrong-scale
    join: a real HRR mean sits near the 1.5 line the book quotes, not near 0
    and not near 40."""
    out = _score(_index_with(COMPLETE))
    assert 1.0 < out["projected"] < 4.0
