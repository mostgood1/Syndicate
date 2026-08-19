"""Unit tests for `historical_truth.faceoff_decay_model` — the discrete-event faceoff redesign
`hockeysim_faceoff_segment_validation_report.md` flagged as the properly-faithful way to model a
real, measured, sharp, short-lived post-faceoff shot-generation effect (a uniform per-segment
multiplier cannot represent it).
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_decay_model import (
    segment_average_multipliers,
)


def test_short_segment_matches_the_first_bucket_exactly():
    """A segment no longer than the first measured bucket (5s) should reproduce that bucket's own
    multipliers exactly -- no blending with anything else."""
    result = segment_average_multipliers(5.0)
    assert result.winner_mult == pytest.approx(1.7548, abs=1e-4)
    assert result.other_mult == pytest.approx(0.2452, abs=1e-4)


def test_decay_is_monotonically_shrinking_toward_baseline():
    """As the segment gets longer, the winner's advantage should shrink toward 1.0 (more of the
    CUMULATIVE average is diluted by the decayed tail) -- these are averages FROM the draw, not the
    marginal rate AT that point, so even the 90s average stays above 1.0 (see the separate
    very-long-segment test for where the average itself converges)."""
    short = segment_average_multipliers(10.0)
    medium = segment_average_multipliers(45.0)
    longer = segment_average_multipliers(90.0)
    assert short.winner_mult > medium.winner_mult > longer.winner_mult > 1.0


def test_very_long_segment_converges_to_baseline():
    """A segment far longer than any measured decay (e.g. a full period) should land at
    essentially the no-effect baseline -- the real data shows the effect fully decayed by 90s."""
    result = segment_average_multipliers(1200.0)
    assert result.winner_mult == pytest.approx(1.0, abs=0.06)
    assert result.other_mult == pytest.approx(1.0, abs=0.06)


@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_mean_of_winner_and_other_is_always_one(seg_len):
    """The same design invariant every per-team index this session built holds here too: the
    winner's and loser's multipliers average to 1.0 for ANY segment length, so redistributing shots
    between the two teams never shifts the segment's own EXPECTED total -- only who gets them."""
    result = segment_average_multipliers(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-6)


def test_typical_engine_segment_length_shows_a_real_but_diluted_effect():
    """Engine segments are ~40-45s (`engine.py`'s `target_seg`) -- at that length the winner
    should still show a measurable edge, but far smaller than the raw 10s-window ratio (3.84x),
    since most of a 40-45s segment falls in the already-decayed tail."""
    result = segment_average_multipliers(42.5)
    assert 1.0 < result.winner_mult < 1.5
    assert 0.5 < result.other_mult < 1.0


@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_non_positive_or_invalid_input_returns_neutral_baseline(bad):
    result = segment_average_multipliers(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0
