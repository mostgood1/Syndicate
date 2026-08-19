"""Unit tests for `historical_truth.faceoff_decay_model` — the discrete-event faceoff redesign
`hockeysim_faceoff_segment_validation_report.md` flagged as the properly-faithful way to model a
real, measured, sharp, short-lived post-faceoff shot-generation effect (a uniform per-segment
multiplier cannot represent it).
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_decay_model import (
    draw_strength_zone,
    expected_multipliers_strength_zone,
    segment_average_multipliers,
    segment_average_multipliers_dz,
    segment_average_multipliers_nz,
    segment_average_multipliers_oz,
    segment_average_multipliers_pk_role,
    segment_average_multipliers_pk_role_dz,
    segment_average_multipliers_pk_role_nz,
    segment_average_multipliers_pp_role,
    segment_average_multipliers_pp_role_dz,
    segment_average_multipliers_pp_role_nz,
    segment_average_multipliers_pp_role_oz,
    segment_average_multipliers_strength_zone,
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


def test_nz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_nz(5.0)
    assert result.winner_mult == pytest.approx(1.4964, abs=1e-4)
    assert result.other_mult == pytest.approx(0.5036, abs=1e-4)


def test_nz_effect_is_weaker_than_the_general_curve_at_every_matched_length():
    """The general (blended) curve's short-segment integral is dominated by the OZ-heavy portion
    of its population (OZ's raw winner rate is far larger per-draw than NZ's, even though NZ is
    the largest of the three zone populations by draw COUNT) -- checked directly via the
    TIME-WEIGHTED INTEGRAL both curves actually use, not assumed from the marginal buckets alone
    (which show a MIXED bucket-by-bucket picture, NZ briefly exceeding the general curve in the
    mid-range before the comparison is integrated)."""
    for seg_len in (5.0, 10.0, 20.0, 42.5, 90.0, 1200.0):
        nz = segment_average_multipliers_nz(seg_len)
        general = segment_average_multipliers(seg_len)
        assert nz.winner_mult <= general.winner_mult, f"failed at seg_len={seg_len}"


@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_nz_mean_of_winner_and_other_is_always_one(seg_len):
    result = segment_average_multipliers_nz(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-4)


def test_nz_very_long_segment_converges_to_baseline():
    """Like the general and OZ curves (unlike DZ), the NZ curve fully reconverges within the
    measured range -- a very long segment should land at essentially the no-effect baseline."""
    result = segment_average_multipliers_nz(1200.0)
    assert result.winner_mult == pytest.approx(1.0, abs=0.05)
    assert result.other_mult == pytest.approx(1.0, abs=0.05)


def test_nz_typical_engine_segment_length_still_shows_a_real_effect():
    """At the engine's real ~40-45s segment length, the NZ winner should still show a measurable
    positive edge -- weaker than the general curve's own (see the dedicated comparison test above),
    but a REAL effect, not a no-op."""
    nz = segment_average_multipliers_nz(42.5)
    assert nz.winner_mult > 1.0
    assert nz.other_mult < 1.0


@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_nz_non_positive_or_invalid_input_returns_neutral_baseline(bad):
    result = segment_average_multipliers_nz(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0


# ---------------------------------------------------------------------------
# Strength-state (PP/PK) curves -- the first faceoff mechanism curves to apply during a power
# play or penalty kill; every other curve is gated EV-only.
# ---------------------------------------------------------------------------

def test_pp_role_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_pp_role(5.0)
    assert result.winner_mult == pytest.approx(1.9167, abs=1e-4)
    assert result.other_mult == pytest.approx(0.0833, abs=1e-4)


def test_pp_role_stays_strongly_positive_at_every_length_including_very_long():
    """Unlike every other curve, PP-role never reconverges within the measured window -- a real
    power play often runs close to or beyond 90s. A very long segment should hold near the (60,90]
    bucket's own values, NOT decay toward the no-effect baseline."""
    for seg_len in (5.0, 42.5, 1200.0):
        result = segment_average_multipliers_pp_role(seg_len)
        assert result.winner_mult > 1.5, f"failed at seg_len={seg_len}"
        assert result.other_mult < 0.5, f"failed at seg_len={seg_len}"


@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_pp_role_mean_of_winner_and_other_is_always_one(seg_len):
    result = segment_average_multipliers_pp_role(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-4)


@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_pp_role_non_positive_or_invalid_input_returns_neutral_baseline(bad):
    result = segment_average_multipliers_pp_role(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0


def test_pk_role_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_pk_role(5.0)
    assert result.winner_mult == pytest.approx(1.1331, abs=1e-4)
    assert result.other_mult == pytest.approx(0.8669, abs=1e-4)


def test_pk_role_direction_flips_as_the_window_widens():
    """A real, distinctive property of this curve alone: a brief clear-driven bump favors the
    shorthanded winner in the first ~5-10s, then the opponent's man-advantage reasserts and the
    INTEGRATED average crosses below 1.0 -- unlike DZ, which is reversed from the shortest bucket
    onward, and unlike PP-role/general/OZ/NZ, which never reverse direction at all."""
    short = segment_average_multipliers_pk_role(5.0)
    long = segment_average_multipliers_pk_role(15.0)
    assert short.winner_mult > 1.0
    assert long.winner_mult < 1.0


def test_pk_role_stays_suppressed_at_typical_and_very_long_segment_lengths():
    """Like PP-role, PK-role never reconverges to the no-effect baseline within the measured
    window -- held at the (60,90] bucket's own (suppressed) values."""
    for seg_len in (42.5, 1200.0):
        result = segment_average_multipliers_pk_role(seg_len)
        assert result.winner_mult < 0.6, f"failed at seg_len={seg_len}"
        assert result.other_mult > 1.4, f"failed at seg_len={seg_len}"


@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_pk_role_mean_of_winner_and_other_is_always_one(seg_len):
    result = segment_average_multipliers_pk_role(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-4)


@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_pk_role_non_positive_or_invalid_input_returns_neutral_baseline(bad):
    result = segment_average_multipliers_pk_role(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0


# ---------------------------------------------------------------------------
# Joint role-and-zone curves (§2z) -- five dedicated curves (PP+O, PP+N, PP+D, PK+N, PK+D);
# PK+O (197 real draws, too thin) intentionally falls back to the flat PK-role curve, tested
# separately below via the dispatcher.
# ---------------------------------------------------------------------------

_JOINT_CURVE_FUNCS = {
    ("PP", "O"): segment_average_multipliers_pp_role_oz,
    ("PP", "N"): segment_average_multipliers_pp_role_nz,
    ("PP", "D"): segment_average_multipliers_pp_role_dz,
    ("PK", "N"): segment_average_multipliers_pk_role_nz,
    ("PK", "D"): segment_average_multipliers_pk_role_dz,
}


def test_pp_role_oz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_pp_role_oz(5.0)
    assert result.winner_mult == pytest.approx(1.9271, abs=1e-4)
    assert result.other_mult == pytest.approx(0.0729, abs=1e-4)


def test_pp_role_nz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_pp_role_nz(5.0)
    assert result.winner_mult == pytest.approx(1.4997, abs=1e-4)
    assert result.other_mult == pytest.approx(0.5003, abs=1e-4)


def test_pp_role_dz_short_segment_matches_the_first_bucket_exactly():
    """The thinnest curve kept this pass -- a real, measured zero-winner-shots first bucket."""
    result = segment_average_multipliers_pp_role_dz(5.0)
    assert result.winner_mult == pytest.approx(0.0, abs=1e-4)
    assert result.other_mult == pytest.approx(2.0, abs=1e-4)


def test_pk_role_nz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_pk_role_nz(5.0)
    assert result.winner_mult == pytest.approx(1.6111, abs=1e-4)
    assert result.other_mult == pytest.approx(0.3889, abs=1e-4)


def test_pk_role_dz_short_segment_matches_the_first_bucket_exactly():
    result = segment_average_multipliers_pk_role_dz(5.0)
    assert result.winner_mult == pytest.approx(1.0, abs=1e-4)
    assert result.other_mult == pytest.approx(1.0, abs=1e-4)


@pytest.mark.parametrize("key", list(_JOINT_CURVE_FUNCS.keys()))
@pytest.mark.parametrize("seg_len", [1.0, 5.0, 15.0, 40.0, 45.0, 60.0, 90.0, 200.0, 1200.0])
def test_joint_curve_mean_of_winner_and_other_is_always_one(key, seg_len):
    """Same mean-1-per-bucket invariant as every other curve this session built -- required for
    `_strength_state_zone_multipliers`'s own exact-normalization proof to hold."""
    fn = _JOINT_CURVE_FUNCS[key]
    result = fn(seg_len)
    assert (result.winner_mult + result.other_mult) / 2.0 == pytest.approx(1.0, abs=1e-4)


@pytest.mark.parametrize("fn", list(_JOINT_CURVE_FUNCS.values()))
@pytest.mark.parametrize("bad", [0.0, -5.0, None, "not-a-number"])
def test_joint_curve_non_positive_or_invalid_input_returns_neutral_baseline(fn, bad):
    result = fn(bad)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0


def test_pp_role_dz_is_meaningfully_weaker_than_pp_role_oz():
    """The real, large, measured finding this pass: a power-play team winning its own DEFENSIVE-
    zone draw (a rare tail) is dramatically LESS favorable than winning in its own offensive zone
    (the majority case) -- confirms the two curves are genuinely distinct, not near-duplicates."""
    oz = segment_average_multipliers_pp_role_oz(15.0)
    dz = segment_average_multipliers_pp_role_dz(15.0)
    assert oz.winner_mult > dz.winner_mult


def test_pk_role_dz_is_meaningfully_weaker_than_pk_role_nz():
    """The mirror finding for PK-role: winning a shorthanded draw in the DEFENSIVE zone (the
    majority case) is meaningfully worse than winning one in the NEUTRAL zone."""
    dz = segment_average_multipliers_pk_role_dz(15.0)
    nz = segment_average_multipliers_pk_role_nz(15.0)
    assert nz.winner_mult > dz.winner_mult


# ---------------------------------------------------------------------------
# `segment_average_multipliers_strength_zone` -- the (role, zone) dispatcher, including the
# floored PK+O fallback.
# ---------------------------------------------------------------------------

def test_dispatcher_routes_to_the_matching_joint_curve():
    direct = segment_average_multipliers_pp_role_oz(30.0)
    dispatched = segment_average_multipliers_strength_zone("PP", "O", 30.0)
    assert dispatched == direct


def test_dispatcher_is_case_insensitive():
    assert segment_average_multipliers_strength_zone("pp", "o", 30.0) == \
        segment_average_multipliers_strength_zone("PP", "O", 30.0)


def test_dispatcher_pk_o_falls_back_to_the_flat_pk_role_curve():
    """PK+O (197 real draws, median 6/team/season) is too data-thin to trust its own curve -- the
    dispatcher must route it to the flat PK-role curve instead, not a dedicated (and unreliable)
    PK+O curve."""
    dispatched = segment_average_multipliers_strength_zone("PK", "O", 30.0)
    fallback = segment_average_multipliers_pk_role(30.0)
    assert dispatched == fallback


def test_dispatcher_unrecognized_combination_returns_neutral_baseline():
    result = segment_average_multipliers_strength_zone("XX", "O", 30.0)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0
    result2 = segment_average_multipliers_strength_zone("PP", "X", 30.0)
    assert result2.winner_mult == 1.0
    assert result2.other_mult == 1.0


# ---------------------------------------------------------------------------
# `expected_multipliers_strength_zone` -- the zone-marginalized expectation
# `_strength_state_zone_multipliers`'s own normalization needs.
# ---------------------------------------------------------------------------

def test_expected_multipliers_matches_a_direct_weighted_sum():
    """Not a black-box check -- recomputes the weighted sum independently (using the SAME real
    zone probabilities, imported directly) and confirms the function returns exactly that, not an
    approximation or a different weighting scheme."""
    from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.faceoff_decay_model import (
        _STRENGTH_ZONE_PROBS,
    )
    seg_len = 42.5
    expected_winner = sum(
        p * segment_average_multipliers_strength_zone("PP", z, seg_len).winner_mult
        for z, p in _STRENGTH_ZONE_PROBS["PP"].items()
    )
    result = expected_multipliers_strength_zone("PP", seg_len)
    assert result.winner_mult == pytest.approx(expected_winner, abs=1e-4)


def test_expected_multipliers_unrecognized_role_returns_neutral_baseline():
    result = expected_multipliers_strength_zone("XX", 30.0)
    assert result.winner_mult == 1.0
    assert result.other_mult == 1.0


# ---------------------------------------------------------------------------
# `draw_strength_zone` -- maps a uniform draw to a zone using the real population proportions.
# ---------------------------------------------------------------------------

def test_draw_strength_zone_is_deterministic_for_the_same_inputs():
    assert draw_strength_zone("PP", 0.1) == draw_strength_zone("PP", 0.1)


def test_draw_strength_zone_pp_low_u_is_offensive_zone():
    """PP-role's population is 82.8% offensive-zone -- a low `u` must land there."""
    assert draw_strength_zone("PP", 0.01) == "O"


def test_draw_strength_zone_pk_low_u_is_offensive_zone():
    """PK-role's population is only 2.9% offensive-zone -- a very low `u` still lands there (it's
    listed first in the fixed iteration order), but a mid-range `u` should NOT."""
    assert draw_strength_zone("PK", 0.01) == "O"
    assert draw_strength_zone("PK", 0.5) == "D"  # PK-role is 83.6% defensive-zone


def test_draw_strength_zone_covers_the_full_unit_interval_without_gaps():
    """Every `u` in `[0, 1)` must resolve to a real zone -- no silent `None`/crash at any point,
    including right at the boundary between cumulative probability segments."""
    for i in range(1000):
        u = i / 1000.0
        assert draw_strength_zone("PP", u) in ("O", "N", "D")
        assert draw_strength_zone("PK", u) in ("O", "N", "D")


def test_draw_strength_zone_unrecognized_role_falls_back_to_offensive():
    assert draw_strength_zone("XX", 0.5) == "O"
