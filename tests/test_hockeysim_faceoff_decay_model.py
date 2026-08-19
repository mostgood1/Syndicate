"""Unit tests for `historical_truth.faceoff_decay_model` — the discrete-event faceoff redesign
`hockeysim_faceoff_segment_validation_report.md` flagged as the properly-faithful way to model a
real, measured, sharp, short-lived post-faceoff shot-generation effect (a uniform per-segment
multiplier cannot represent it).
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_decay_model import (
    segment_average_multipliers,
    segment_average_multipliers_dz,
    segment_average_multipliers_oz,
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


# ---------------------------------------------------------------------------
# DZ-specific curve (`segment_average_multipliers_dz`) -- direction REVERSED relative to the
# general curve, per `hockeysim_faceoff_dz_segment_validation_report.md`'s real measurement.
# ---------------------------------------------------------------------------

def test_dz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_dz(5.0)
    assert result.winner_mult == pytest.approx(0.3890, abs=1e-4)
    assert result.other_mult == pytest.approx(1.6110, abs=1e-4)


def test_dz_direction_is_reversed_from_the_general_curve():
    """The defining property of the DZ curve: at short segment lengths, the WINNER's multiplier is
    BELOW 1.0 and the OTHER team's is ABOVE 1.0 -- the opposite of the general curve, matching the
    real measured direction (a team that wins its own DZ draw is out-shot, not out-shooting)."""
    dz = segment_average_multipliers_dz(10.0)
    general = segment_average_multipliers(10.0)
    assert dz.winner_mult < 1.0 < dz.other_mult
    assert general.winner_mult > 1.0 > general.other_mult


@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_dz_mean_of_winner_and_other_is_always_one(seg_len):
    """Same design invariant as the general curve and every per-team index this session built:
    the winner's and other team's multipliers average to 1.0 for ANY segment length."""
    result = segment_average_multipliers_dz(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-6)


def test_dz_very_long_segment_holds_at_the_last_measured_bucket_not_assumed_parity():
    """Unlike the general curve (which converges to 1.0/1.0 beyond 90s), the DZ curve never
    reached parity within the measured range -- a very long segment should hold at the (60,90]
    bucket's own values, not silently assume the effect fully decayed."""
    result = segment_average_multipliers_dz(1200.0)
    assert result.winner_mult == pytest.approx(0.9726, abs=0.01)
    assert result.other_mult == pytest.approx(1.0274, abs=0.01)
    # And explicitly NOT the general curve's converged baseline:
    assert result.winner_mult != pytest.approx(1.0, abs=1e-3)


def test_dz_typical_engine_segment_length_shows_a_real_but_diluted_reversed_effect():
    """At the engine's real ~40-45s segment length, the DZ winner should still show a measurable
    suppression, but far smaller than the raw 5s-window ratio, since most of the segment falls
    past the sharpest early suppression."""
    result = segment_average_multipliers_dz(42.5)
    assert 0.9 < result.winner_mult < 1.0
    assert 1.0 < result.other_mult < 1.1


@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_dz_non_positive_or_invalid_input_returns_neutral_baseline(bad):
    result = segment_average_multipliers_dz(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0


# ---------------------------------------------------------------------------
# OZ-specific curve (`segment_average_multipliers_oz`) -- a dramatically stronger, cleaner
# version of the general curve's own effect, fully reconverging by 60-90s (unlike DZ).
# ---------------------------------------------------------------------------

def test_oz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_oz(5.0)
    assert result.winner_mult == pytest.approx(1.9834, abs=1e-4)
    assert result.other_mult == pytest.approx(0.0165, abs=1e-4)


def test_oz_effect_is_stronger_than_the_general_curve_at_every_matched_length():
    """The defining property of the OZ curve: since it isolates the purest case of the general
    phenomenon (no dilution from NZ/DZ draws), its winner_mult should be >= the general curve's
    own at short/medium segment lengths."""
    for seg_len in (5.0, 10.0, 20.0, 45.0):
        oz = segment_average_multipliers_oz(seg_len)
        general = segment_average_multipliers(seg_len)
        assert oz.winner_mult >= general.winner_mult, f"failed at seg_len={seg_len}"


@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_oz_mean_of_winner_and_other_is_always_one(seg_len):
    # abs=1e-3, not 1e-6 like the general/DZ curves' own version of this test: the OZ curve's
    # extreme first-bucket ratio (raw 119.7x) means its 4-decimal-place constants carry slightly
    # more rounding error than the milder general/DZ curves' own constants do.
    result = segment_average_multipliers_oz(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-3)


def test_oz_very_long_segment_converges_to_baseline():
    """Unlike DZ, the OZ curve DOES fully reconverge within the measured range -- a very long
    segment should land at essentially the no-effect baseline, same as the general curve."""
    result = segment_average_multipliers_oz(1200.0)
    assert result.winner_mult == pytest.approx(1.0, abs=0.05)
    assert result.other_mult == pytest.approx(1.0, abs=0.05)


def test_oz_typical_engine_segment_length_shows_a_real_and_larger_effect():
    """At the engine's real ~40-45s segment length, the OZ winner should show a measurable edge
    LARGER than the general curve's own edge at the same length, reflecting the purer signal."""
    oz = segment_average_multipliers_oz(42.5)
    general = segment_average_multipliers(42.5)
    assert oz.winner_mult > general.winner_mult
    assert oz.winner_mult > 1.0
    assert oz.other_mult < 1.0


@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_oz_non_positive_or_invalid_input_returns_neutral_baseline(bad):
    result = segment_average_multipliers_oz(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0
