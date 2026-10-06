"""NHL SAVES priced by a negative binomial (lane `nhl-saves-overdispersion`, H26 passed 2026-10-06)."""
from __future__ import annotations

import math

import pytest

from syndicate.features.nhl import prop_projections as P


def _nb_ref(line, mu, k):
    """Independent reference: explicit lgamma pmf, as in scripts/nhl_saves_overdispersion.py."""
    s = 0.0
    for x in range(int(math.floor(line)) + 1):
        s += math.exp(math.lgamma(x + k) - math.lgamma(k) - math.lgamma(x + 1)
                      + k * math.log(k / (k + mu)) + x * math.log(mu / (k + mu)))
    return 1.0 - s


@pytest.mark.parametrize("line, mu", [(22.5, 23.18), (25.5, 24.47), (28.5, 26.0), (0.5, 0.3), (24.0, 24.0)])
def test_nb_matches_the_reference_pmf(line, mu):
    assert P.nb_p_over(line, mu, P.SAVES_NB_K) == pytest.approx(_nb_ref(line, mu, P.SAVES_NB_K), abs=1e-12)


def test_nb_tends_to_poisson_and_is_wider():
    assert P.nb_p_over(22.5, 23.0, 1e9) == pytest.approx(P.poisson_p_over(22.5, 23.0), abs=1e-6)
    # overdispersion pulls a line near the mean toward 0.5 and fattens the far tail
    assert abs(P.nb_p_over(22.5, 23.18, P.SAVES_NB_K) - 0.5) < abs(P.poisson_p_over(22.5, 23.18) - 0.5)
    assert P.nb_p_over(32.5, 23.0, P.SAVES_NB_K) > P.poisson_p_over(32.5, 23.0)


def test_only_saves_changes_market():
    assert P.price_p_over("SAVES", 22.5, 23.18) == pytest.approx(P.nb_p_over(22.5, 23.18, P.SAVES_NB_K))
    assert P.price_p_over("saves", 22.5, 23.18) == pytest.approx(P.nb_p_over(22.5, 23.18, P.SAVES_NB_K))
    for code in ("SOG", "GOALS", "ASSISTS", "POINTS", "BLOCKS"):
        assert P.price_p_over(code, 2.5, 3.1) == P.poisson_p_over(2.5, 3.1)
    assert P.pricing_basis("SAVES") == "sim_mean_negbin" and P.pricing_basis("SOG") == "sim_mean_poisson"
    assert P.SAVES_NB_K == 16.367
