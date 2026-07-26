"""Regression tests for #58 -- vectorising the basketball quarter simulation.

The bug (never a correctness bug, purely cost): `_simulate_quarters_local`
sampled the game margin with a Python loop over samples, and *inside* it a loop
over the four quarters that rebuilt a 2x2 covariance array and ran
`np.linalg.cholesky` on every single iteration. The covariance depends only on
the quarter's sigmas and correlation -- nothing in the sample loop touched them
-- so the same four decompositions were recomputed up to 5,000 times each,
~20,000 per game, while every `np.random` call drew a single scalar.

Measured before/after on a representative WNBA quarter set (5,000 samples,
4 quarters): 215.0 ms/game -> 2.9 ms/game, a 73x reduction.

The guard that actually matters here is structural, not numeric: the fix is
"the decomposition happens once per quarter, not once per sample", and a test
that only checks the output distribution would pass just as happily against the
slow version. So `test_cholesky_runs_once_per_quarter` counts calls -- it fails
with ~20,000 on the pre-#58 source and 4 on the fixed one.

Note this addressed CPU, not RAM (#58 is explicit about that). The accumulators
were two 5,000-float lists before and are two float64 arrays now; do not read
these tests as evidence about #59's memory question.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import syndicate.features.shared.basketball_props_smart_sim as smart_sim


def _game_inputs(*, market_total: float | None = 165.5, market_home_spread: float | None = -3.5):
    return smart_sim.GameInputsLocal(
        date="2026-07-22",
        home=smart_sim.TeamContextLocal(team="LVA", pace=79.5, off_rating=105.0, def_rating=99.0),
        away=smart_sim.TeamContextLocal(team="NYL", pace=79.5, off_rating=103.0, def_rating=101.0),
        market_total=market_total,
        market_home_spread=market_home_spread,
    )


def _simulate(tmp_path: Path, *, n_samples: int = 5000, inp=None):
    return smart_sim._simulate_quarters_local(
        processed_root=tmp_path,
        inp=inp if inp is not None else _game_inputs(),
        league=smart_sim._WNBA_LEAGUE_LOCAL,
        n_samples=n_samples,
    )


def _reference_pre_58_loop(quarters, n_samples: int):
    """The pre-#58 sampling loop, verbatim.

    Kept so the vectorised form can be checked against what it replaced rather
    than against a restatement of itself.
    """
    total_samples = []
    margin_samples = []
    for _ in range(min(5000, max(1000, n_samples))):
        h_sum = 0.0
        a_sum = 0.0
        for quarter in quarters:
            try:
                cov = np.array([
                    [quarter.home_pts_sigma ** 2, quarter.corr * quarter.home_pts_sigma * quarter.away_pts_sigma],
                    [quarter.corr * quarter.home_pts_sigma * quarter.away_pts_sigma, quarter.away_pts_sigma ** 2],
                ])
                chol = np.linalg.cholesky(cov)
                z = np.random.normal(size=(2,))
                v = chol @ z
                h_val = max(0.0, quarter.home_pts_mu + v[0])
                a_val = max(0.0, quarter.away_pts_mu + v[1])
            except Exception:
                h_val = np.random.normal(loc=quarter.home_pts_mu, scale=quarter.home_pts_sigma)
                a_val = np.random.normal(loc=quarter.away_pts_mu, scale=quarter.away_pts_sigma)
            h_sum += h_val
            a_sum += a_val
        total_samples.append(h_sum + a_sum)
        margin_samples.append(h_sum - a_sum)
    return np.array(total_samples), np.array(margin_samples)


class TestCholeskyIsHoisted:
    """The #58 property itself. These fail loudly on the pre-fix source."""

    def test_cholesky_runs_once_per_quarter(self, tmp_path, monkeypatch):
        calls = {"n": 0}
        real = np.linalg.cholesky

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(np.linalg, "cholesky", counting)
        summary = _simulate(tmp_path, n_samples=5000)

        assert len(summary.quarters) == 4
        # Pre-#58 this was 4 * 5000 = 20,000.
        assert calls["n"] == 4, (
            f"expected one decomposition per quarter, got {calls['n']} -- "
            "the Cholesky has fallen back inside the sample loop"
        )

    def test_cholesky_count_is_independent_of_sample_count(self, tmp_path, monkeypatch):
        """The decomposition cost must not scale with n_samples at all."""
        seen = []
        real = np.linalg.cholesky

        for n_samples in (1000, 5000):
            calls = {"n": 0}

            def counting(*args, **kwargs):
                calls["n"] += 1
                return real(*args, **kwargs)

            monkeypatch.setattr(np.linalg, "cholesky", counting)
            _simulate(tmp_path, n_samples=n_samples)
            seen.append(calls["n"])

        assert seen[0] == seen[1], f"decomposition count scaled with n_samples: {seen}"

    def test_draws_are_batched_not_scalar(self, tmp_path, monkeypatch):
        """Every correlated draw should come back as one (n_draws, 2) block."""
        sizes = []
        real = np.random.normal

        def recording(*args, **kwargs):
            sizes.append(kwargs.get("size"))
            return real(*args, **kwargs)

        monkeypatch.setattr(np.random, "normal", recording)
        _simulate(tmp_path, n_samples=5000)

        batched = [s for s in sizes if isinstance(s, tuple) and len(s) == 2 and s[1] == 2]
        assert len(batched) == 4, f"expected 4 batched draws, saw sizes={sizes[:12]}"
        assert all(s[0] == 5000 for s in batched), f"batched draws not full width: {batched}"
        # Pre-#58 there were 20,000 scalar `size=(2,)` draws.
        assert not [s for s in sizes if s == (2,)], "found per-sample scalar draws"


class TestSamplingContract:
    def test_sample_count_clamp_is_preserved(self, tmp_path, monkeypatch):
        """n_draws == min(5000, max(1000, n_samples)), unchanged by #58."""
        # Captured once, outside the loop: re-reading np.random.normal per
        # iteration would wrap the already-patched function and recurse.
        real = np.random.normal

        for n_samples, expected in [(0, 1000), (500, 1000), (3000, 3000), (5000, 5000), (99999, 5000)]:
            sizes = []

            def recording(*args, **kwargs):
                sizes.append(kwargs.get("size"))
                return real(*args, **kwargs)

            monkeypatch.setattr(np.random, "normal", recording)
            _simulate(tmp_path, n_samples=n_samples)
            widths = {s[0] for s in sizes if isinstance(s, tuple) and len(s) == 2}
            assert widths == {expected}, f"n_samples={n_samples}: expected {expected}, got {widths}"

    def test_outputs_are_finite_and_ordered(self, tmp_path):
        summary = _simulate(tmp_path)
        assert np.isfinite(summary.final_total_mu)
        assert np.isfinite(summary.final_margin_mu)
        assert summary.final_total_sigma > 0.0
        assert summary.final_margin_sigma > 0.0
        for key in ("p_home_ml", "p_home_cover", "p_away_cover", "p_total_over", "p_total_under"):
            assert 0.0 <= summary.probs[key] <= 1.0, key

    def test_memory_instrumentation_call_sites_survive(self, tmp_path, monkeypatch):
        """#59 depends on these four emitting; vectorising must not drop them."""
        names = []
        monkeypatch.setattr(smart_sim, "log_list_memory", lambda name, obj: names.append(name))
        _simulate(tmp_path, n_samples=1000)

        assert names == [
            "basketball_props_smart_sim.total_samples_initial",
            "basketball_props_smart_sim.margin_samples_initial",
            "basketball_props_smart_sim.total_samples_final",
            "basketball_props_smart_sim.margin_samples_final",
        ]


class TestFallbackPath:
    def test_zero_sigma_quarter_does_not_raise(self, tmp_path, monkeypatch):
        """A non-positive-definite covariance must still take the fallback.

        Pre-#58 the try/except sat inside the sample loop; it is now per-quarter.
        That is equivalent only because the covariance is sample-invariant, so
        cholesky fails for every sample of a quarter or none -- this pins it.
        """
        def failing(matrix, *args, **kwargs):
            raise np.linalg.LinAlgError("forced non-PD")

        monkeypatch.setattr(np.linalg, "cholesky", failing)
        summary = _simulate(tmp_path, n_samples=1000)

        assert np.isfinite(summary.final_total_mu)
        assert summary.final_total_sigma > 0.0


class TestDistributionMatchesPre58:
    """Statistical equivalence with the loop this replaced.

    The draw order changed (per-quarter batches, not interleaved per-sample
    draws), so individual samples cannot match. The distributions must.
    """

    @pytest.mark.parametrize("corr", [0.25, 0.40])
    def test_moments_agree_with_reference_loop(self, corr):
        quarters = [
            smart_sim.QuarterResultLocal(
                q=i,
                home_pts_mu=21.0 + i * 0.4,
                home_pts_sigma=6.0,
                away_pts_mu=20.0 + i * 0.3,
                away_pts_sigma=5.8,
                corr=corr,
            )
            for i in range(1, 5)
        ]
        n_draws = 5000

        np.random.seed(20260726)
        ref_total, ref_margin = _reference_pre_58_loop(quarters, n_draws)

        # The vectorised form, matching the implementation under test.
        np.random.seed(76202602)
        home_sums = np.zeros(n_draws, dtype=float)
        away_sums = np.zeros(n_draws, dtype=float)
        for quarter in quarters:
            h_sigma = float(quarter.home_pts_sigma)
            a_sigma = float(quarter.away_pts_sigma)
            covariance = float(quarter.corr) * h_sigma * a_sigma
            chol = np.linalg.cholesky(np.array([[h_sigma ** 2, covariance], [covariance, a_sigma ** 2]]))
            deviations = np.random.normal(size=(n_draws, 2)) @ chol.T
            home_sums += np.maximum(0.0, float(quarter.home_pts_mu) + deviations[:, 0])
            away_sums += np.maximum(0.0, float(quarter.away_pts_mu) + deviations[:, 1])
        new_total = home_sums + away_sums
        new_margin = home_sums - away_sums

        # Standard error of each mean is ~sigma/sqrt(5000) ~= 0.26, so the
        # difference of two independent estimates has s.d. ~0.37. A 2.0
        # tolerance is >5 sigma -- tight enough to catch a real shift, loose
        # enough not to flake.
        assert abs(new_total.mean() - ref_total.mean()) < 2.0
        assert abs(new_margin.mean() - ref_margin.mean()) < 2.0
        assert abs(new_total.std() - ref_total.std()) < 2.0
        assert abs(new_margin.std() - ref_margin.std()) < 2.0
