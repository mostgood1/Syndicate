"""Full-game run-margin dispersion correction (sim_engine.prob_calibration).

Measured 2026-08-05 over 873 completed games / 66 dates against real StatsAPI
finals: the sim states a mean per-game run-margin SD of 4.515 while the realised
residual SD is 4.733, so it under-disperses margin by 4.8% and pushes win
probabilities too far from 50%.

This is a variance correction derived from measured spread, NOT a calibration
fitted against outcomes -- it has no free parameters tuned on results. Validated
before wiring: over the same 873 games it moved Brier 0.24806 -> 0.24794 and
logloss 0.68943 -> 0.68912, degrading no probability bucket. Effect is small by
design (top bucket 69.0% -> 68.2%); it is applied because it is principled and
harmless, not because it is large.
"""

from __future__ import annotations

import pytest

from vendor.mlb_bettingv2.sim_engine.prob_calibration import (
    FULL_GAME_MARGIN_DISPERSION_FACTOR,
    widen_margin_distribution,
    win_probs_from_margin_distribution,
)

DIST = {-4: 40.0, -2: 120.0, -1: 180.0, 1: 260.0, 2: 220.0, 5: 180.0}


def _mean(d):
    t = sum(d.values())
    return sum(k * v for k, v in d.items()) / t


def _sd(d):
    t = sum(d.values())
    mu = _mean(d)
    return (sum(v * (k - mu) ** 2 for k, v in d.items()) / t) ** 0.5


class TestFactor:
    def test_factor_matches_the_measurement(self):
        # 4.733 / 4.515 = 1.048. Locked so a silent edit has to break a test.
        assert FULL_GAME_MARGIN_DISPERSION_FACTOR == pytest.approx(1.048, abs=1e-9)

    def test_factor_widens_rather_than_narrows(self):
        assert FULL_GAME_MARGIN_DISPERSION_FACTOR > 1.0


class TestWidening:
    def test_unit_factor_is_an_exact_noop(self):
        assert widen_margin_distribution(DIST, 1.0) == {int(k): float(v) for k, v in DIST.items()}

    def test_mass_is_preserved(self):
        out = widen_margin_distribution(DIST, FULL_GAME_MARGIN_DISPERSION_FACTOR)
        assert sum(out.values()) == pytest.approx(sum(DIST.values()), abs=1e-9)

    def test_mean_is_preserved(self):
        # Widening is about the mean, so the centre must not move.
        out = widen_margin_distribution(DIST, FULL_GAME_MARGIN_DISPERSION_FACTOR)
        assert _mean(out) == pytest.approx(_mean(DIST), abs=1e-9)

    def test_standard_deviation_scales_by_the_factor(self):
        f = FULL_GAME_MARGIN_DISPERSION_FACTOR
        out = widen_margin_distribution(DIST, f)
        # Fractional lattice splitting adds a little extra variance, so the
        # realised scaling is at least f -- never less, which would defeat it.
        assert _sd(out) / _sd(DIST) >= f - 1e-9

    def test_fractional_bins_are_split_not_rounded(self):
        # The #186 lesson: rounding to the nearest bin quantises away most of a
        # small adjustment. A 4.8% widening must produce fractional counts.
        out = widen_margin_distribution(DIST, FULL_GAME_MARGIN_DISPERSION_FACTOR)
        assert any(abs(v - round(v)) > 1e-9 for v in out.values())

    def test_empty_and_degenerate_inputs_do_not_raise(self):
        assert widen_margin_distribution({}, 1.048) == {}
        assert widen_margin_distribution({3: 0.0}, 1.048) == {3: 0.0}

    def test_non_numeric_bins_are_skipped(self):
        out = widen_margin_distribution({"x": 5.0, 1: 100.0, 2: 100.0}, 1.048)
        assert all(isinstance(k, int) for k in out)


class TestWinProbs:
    def test_probabilities_sum_to_one(self):
        h, a, t = win_probs_from_margin_distribution(DIST)
        assert h + a + t == pytest.approx(1.0, abs=1e-9)

    def test_sign_convention_is_home_minus_away(self):
        h, a, _ = win_probs_from_margin_distribution({2: 75.0, -2: 25.0})
        assert h == pytest.approx(0.75) and a == pytest.approx(0.25)

    def test_zero_margin_counts_as_a_tie(self):
        _, _, t = win_probs_from_margin_distribution({0: 10.0, 1: 90.0})
        assert t == pytest.approx(0.10)

    def test_empty_distribution_is_all_zero(self):
        assert win_probs_from_margin_distribution({}) == (0.0, 0.0, 0.0)

    def test_widening_moves_win_prob_toward_even(self):
        # The whole point: a confident sim gets less confident.
        h_raw, _, _ = win_probs_from_margin_distribution(DIST)
        widened = widen_margin_distribution(DIST, FULL_GAME_MARGIN_DISPERSION_FACTOR)
        h_wide, _, _ = win_probs_from_margin_distribution(widened)
        assert abs(h_wide - 0.5) <= abs(h_raw - 0.5) + 1e-9

    def test_the_move_is_small(self):
        # Guards against a future factor change quietly becoming a large shift.
        h_raw, _, _ = win_probs_from_margin_distribution(DIST)
        widened = widen_margin_distribution(DIST, FULL_GAME_MARGIN_DISPERSION_FACTOR)
        h_wide, _, _ = win_probs_from_margin_distribution(widened)
        assert abs(h_wide - h_raw) < 0.05
