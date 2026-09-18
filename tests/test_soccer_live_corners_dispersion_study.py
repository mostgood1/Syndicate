# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/live_corners_dispersion_study.py -- H35 (offline).

End to end first: data drawn from a KNOWN law must come out with the right verdict. Poisson data must not
be called over-dispersed, and strongly gamma-mixed data must be. A study that cannot tell those apart would
answer the registered question with noise.
"""
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import live_corners_dispersion_study as d  # noqa: E402
from common import nb_sf  # noqa: E402


def _poisson(rng, lam):
    # Knuth; lam is small here
    limit, k, prod = math.exp(-lam), 0, rng.random()
    while prod > limit:
        k += 1
        prod *= rng.random()
    return k


def _synthetic(n_matches, gamma_shape=None, seed=5):
    """Rows shaped like the study's: TRAIN dates first, TEST after; R ~ Poisson(mu * rate factor).

    The factor is drawn PER ROW, so rows are independent. With one factor per match (closer to real play) the
    same test has far less power: 150 TEST matches at gamma shape 1 did not always clear zero. That is a
    property of the registered test, stated in the log before the real run, not something to tune here.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(n_matches):
        date = "2026-08-01" if i < n_matches // 2 else "2026-09-01"
        e3 = rng.uniform(8.0, 12.0)
        for cutoff in d.CUTOFFS:
            mu = e3 * (1.0 - cutoff / 95.0)
            factor = rng.gammavariate(gamma_shape, 1.0 / gamma_shape) if gamma_shape else 1.0
            r = _poisson(rng, mu * factor)
            rows.append({"key": f"lg|{i}", "lg": "lg", "date": date, "cutoff": cutoff, "mu": mu, "r": float(r), "r_count": r})
    return rows


# ---------------------------------------------------------------------------- end to end first

def test_poisson_data_is_not_called_over_dispersed():
    res = d.study(_synthetic(300))
    assert res["verdict"] == "FALSIFIED"
    assert res["phi"] <= 1.15 and res["k"] >= 32


def test_gamma_mixed_data_is_called_over_dispersed():
    res = d.study(_synthetic(300, gamma_shape=2.0))
    assert res["verdict"] == "SUPPORTED"
    assert 1 <= res["k"] <= 4 and res["phi"] > 2.0
    assert res["test_halfline_loss"][res["chosen"]] < res["test_halfline_loss"]["p0"]


# ---------------------------------------------------------------------------- laws

@pytest.mark.parametrize("law,fit,var", [("p0", {}, lambda mu: mu),
                                         ("p1", {"phi": 1.6}, lambda mu: 1.6 * mu),
                                         ("p2", {"k": 3.0}, lambda mu: mu + mu * mu / 3.0)])
def test_each_law_has_the_registered_mean_and_variance(law, fit, var):
    mu = 4.2
    probs = [math.exp(d.logpmf(law, x, mu, fit)) for x in range(200)]
    mean = sum(x * p for x, p in enumerate(probs))
    assert sum(probs) == pytest.approx(1.0, abs=1e-9)
    assert mean == pytest.approx(mu, rel=1e-6)
    assert sum((x - mean) ** 2 * p for x, p in enumerate(probs)) == pytest.approx(var(mu), rel=1e-6)


@pytest.mark.parametrize("line,mu,phi", [(2.5, 3.1, 1.4), (0.5, 1.2, 1.9), (6.5, 5.0, 1.0)])
def test_nb1_is_the_platforms_own_pregame_convention(line, mu, phi):
    assert d.prob_over("p1", line, mu, {"phi": phi}) == pytest.approx(nb_sf(int(line) + 1, mu, phi), abs=1e-12)


@pytest.mark.parametrize("mu,lines", [(3.3, [2.5, 3.5, 4.5]), (3.8, [2.5, 3.5, 4.5]), (0.7, [0.5, 1.5]), (1.0, [0.5, 1.5, 2.5])])
def test_the_registered_half_lines(mu, lines):
    assert d.lines_for(mu) == lines


def test_the_fit_is_maximum_likelihood_over_the_registered_grids():
    res = d.fit_laws(_synthetic(200, gamma_shape=4.0))
    assert res["phi"] in d.PHI_GRID and res["k"] in d.K_GRID
    assert res["phi_loglik"][res["phi"]] == max(res["phi_loglik"].values())
    assert res["k_loglik"][res["k"]] == max(res["k_loglik"].values())


def test_train_picks_the_law_and_test_alone_grades_it():
    """A TEST set that would favour the other law must not change the choice."""
    train = [r for r in _synthetic(300, gamma_shape=2.0) if r["date"] < d.TRAIN_END]
    test = [dict(r, date="2026-09-01", key="t" + r["key"]) for r in _synthetic(300, seed=9) if r["date"] >= d.TRAIN_END]
    res = d.study(train + test)
    assert res["chosen"] == d.choose(train, d.fit_laws(train))[0]     # decided by TRAIN alone
    assert res["verdict"] == "FALSIFIED"          # Poisson TEST data: the TRAIN-chosen law does not beat P0 there


@pytest.mark.parametrize("hi,expected", [(-0.001, "SUPPORTED"), (0.0, "FALSIFIED"), (float("nan"), "FALSIFIED")])
def test_verdict(hi, expected):
    assert d.verdict((-0.01, (-0.02, hi), 100)) == expected


def test_match_rows_use_the_production_share_table():
    from syndicate.features.soccer.features.live_corners import share_remaining

    rows = d.match_rows("epl", "1", "2026-09-01", 10.0, 11.0, lambda cutoff: cutoff // 10)
    assert [r["cutoff"] for r in rows] == list(d.CUTOFFS)
    assert rows[0]["mu"] == pytest.approx(10.0 * share_remaining(20 * 60.0))
    assert rows[0]["r"] == 9.0 and rows[-1]["r"] == 3.0            # 11 - 2 at 20', 11 - 8 at 80'


def test_a_fit_on_the_edge_of_its_grid_is_named():
    res = d.study(_synthetic(200, gamma_shape=0.5))       # far past any registered phi
    assert "phi" in res["fit_at_grid_edge"]


def _world(n_matches, law, param, seed, date):
    """Independent rows over a WIDE range of means, where NB1 and NB2 separate clearly: an NB1 world (variance
    ratio `param` at every mean) picks p1 and an NB2 world (gamma shape `param`) picks p2, measured over 3 seeds."""
    rng = random.Random(seed)
    rows = []
    for i in range(n_matches):
        for cutoff in d.CUTOFFS:
            mu = rng.uniform(0.5, 14.0)
            rate = rng.gammavariate(mu / (param - 1.0), param - 1.0) if law == "nb1" else mu * rng.gammavariate(param, 1.0 / param)
            r = _poisson(rng, rate)
            rows.append({"key": f"{law}{seed}|{i}", "lg": "lg", "date": date, "cutoff": cutoff, "mu": mu, "r": float(r), "r_count": r})
    return rows


def test_nothing_about_test_reaches_the_fit_or_the_choice():
    """Same TRAIN, two TESTs that favour opposite laws: phi, k and the chosen law must not move. The second TEST
    is drawn from NB2 at exactly TRAIN's fitted k, so a choice made on TEST would flip to p2."""
    train = _world(150, "nb1", 2.5, 1, "2026-08-01")
    alone = d.fit_laws(train)
    nb2_test = _world(150, "nb2", alone["k"], 3, "2026-09-01")
    assert d.choose(nb2_test, alone)[0] == "p2"                       # the trap is armed
    with_nb1_test = d.study(train + _world(150, "nb1", 2.5, 2, "2026-09-01"))
    with_nb2_test = d.study(train + nb2_test)
    for res in (with_nb1_test, with_nb2_test):
        assert (res["phi"], res["k"]) == (alone["phi"], alone["k"])
        assert res["chosen"] == d.choose(train, alone)[0] == "p1"
