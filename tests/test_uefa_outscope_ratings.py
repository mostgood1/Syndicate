"""Hermetic tests for the out-of-scope UEFA club ratings (todo #699 Stage 1 item (ii)). No network."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from syndicate.features.soccer import uefa_league_offsets as ulo
from syndicate.features.soccer import uefa_outscope_ratings as uor


def _m(i, home, away, hg, ag, *, home_oos=True, away_oos=True, hA=0.0, hD=0.0, aA=0.0, aD=0.0,
       season=2023, day=None, neutral=False, extra_time=False):
    return uor.OOSMatch(event_id=str(i), season=season, day=day or date(season, 9, 1), competition="uel",
                        stage="league", home_id=home, away_id=away, home_oos=home_oos, away_oos=away_oos,
                        home_A=hA, home_D=hD, away_A=aA, away_D=aD, neutral=neutral,
                        home_goals=hg, away_goals=ag, extra_time=extra_time)


def _simulate(n=6000, seed=1):
    """In-scope anchors with known (A, D) and OOS clubs in two associations with known (A, D)."""
    rng = np.random.default_rng(seed)
    anchors = {"IN1": (0.4, 0.4), "IN2": (0.0, 0.0)}
    truth = {"X1": (0.30, 0.30), "X2": (0.10, 0.10), "X3": (0.20, 0.20),   # country X, mean 0.2
             "Y1": (-0.30, -0.30), "Y2": (-0.50, -0.50), "Y3": (-0.40, -0.40)}  # country Y, mean -0.4
    countries = uor.Associations(country_of={c: c[0] for c in truth})
    oos = list(truth)
    mu, eta = 0.1, 0.3
    matches = []
    for i in range(n):
        if rng.random() < 0.5:
            h, a = rng.choice(oos, 2, replace=False)
            hA, hD = truth[h]
            aA, aD = truth[a]
            kw = {}
        else:
            h = rng.choice(oos)
            a = rng.choice(list(anchors))
            hA, hD = truth[h]
            aA, aD = anchors[a]
            kw = {"away_oos": False, "aA": aA, "aD": aD}
        lh, la = math.exp(mu + eta + hA - aD), math.exp(mu + aA - hD)
        matches.append(_m(i, h, a, int(rng.poisson(lh)), int(rng.poisson(la)), **kw))
    return matches, truth, countries


# --------------------------------------------------------------------------- associations


def test_venue_countries_reads_the_address_and_blanks_absent():
    payload = {"events": [
        {"id": "1", "competitions": [{"venue": {"address": {"city": "Copenhagen", "country": "Denmark"}}}]},
        {"id": "2", "competitions": [{"venue": {"fullName": "x"}}]},
        {"competitions": [{}]},
    ]}
    assert uor.venue_countries(payload) == {"1": "Denmark", "2": ""}


def test_associations_mode_skips_neutral_and_away_and_flags_ties_and_low_share():
    rows = [
        {"event_id": "1", "home_team_id": "A", "away_team_id": "B", "home_team": "Alpha", "away_team": "Beta"},
        {"event_id": "2", "home_team_id": "A", "away_team_id": "C"},
        {"event_id": "3", "home_team_id": "A", "away_team_id": "B"},
        {"event_id": "4", "home_team_id": "B", "away_team_id": "A"},
        {"event_id": "5", "home_team_id": "B", "away_team_id": "A"},
        {"event_id": "6", "home_team_id": "C", "away_team_id": "A"},  # neutral: ignored
    ]
    venue = {"1": "Austria", "2": "Austria", "3": "Czechia", "4": "Israel", "5": "Hungary", "6": "Spain"}
    assoc = uor.club_associations(rows, venue, {"6": True})
    assert assoc.get("A") == "Austria"          # 2 of 3 = 67% -> flagged for audit
    assert assoc.get("B") == ""                 # tie -> unknown
    assert assoc.get("C") == ""                 # only a neutral home match
    flagged = {a["team_id"] for a in assoc.audit}
    assert flagged == {"A", "B"}
    fixed = uor.club_associations(rows, venue, {"6": True}, overrides={"A": "Czechia"})
    assert fixed.get("A") == "Czechia"
    assert [a["override"] for a in fixed.audit if a["team_id"] == "A"] == ["Czechia"]


# --------------------------------------------------------------------------- fit


def test_fitted_recovers_club_strengths_and_prior_recovers_association_means():
    matches, truth, countries = _simulate()
    fitted = uor.fit_outscope(matches, countries, mode=uor.MODE_FITTED, tau_club=5, tau_assoc=5)
    prior = uor.fit_outscope(matches, countries, mode=uor.MODE_PRIOR, tau_assoc=5)
    for c, (A, D) in truth.items():
        fa, fd = fitted.oos_rating(c)
        assert abs(fa - A) < 0.12 and abs(fd - D) < 0.12, (c, fa, fd)
    assert fitted.oos_rating("X1")[0] > fitted.oos_rating("X2")[0]  # within-association order
    px, py = prior.oos_rating("X1"), prior.oos_rating("Y1")
    assert prior.oos_rating("X2") == px  # u == 0: every club of an association is the same
    assert abs(px[0] - 0.2) < 0.1 and abs(py[0] + 0.4) < 0.1
    assert abs(fitted.eta - 0.3) < 0.06 and abs(fitted.mu - 0.1) < 0.06
    # the fitted arm predicts the simulation better than the prior arm, in sample
    assert uor.mean_log_loss(fitted, matches) < uor.mean_log_loss(prior, matches)
    # SEs exist, are positive and shrink with weight
    assert all(0 < se[0] < 1 for se in fitted.club_se.values())


def test_fixed_mode_uses_the_constant_for_every_oos_club_and_fits_only_mu_eta():
    matches, _, countries = _simulate(n=1500)
    beta = 1.66
    fixed = (beta * uor.PROMOTED_RATING, beta * uor.PROMOTED_RATING)
    fit = uor.fit_outscope(matches, countries, mode=uor.MODE_FIXED, fixed=fixed)
    assert fit.oos_rating("X1") == fixed == fit.oos_rating("never-seen")
    assert fit.assoc == {} and fit.club == {}
    m = _m(0, "X1", "IN", 0, 0, away_oos=False, aA=0.4, aD=0.4)
    lh, la = fit.rates(m)
    assert lh == pytest.approx(math.exp(fit.mu + fit.eta + fixed[0] - 0.4))
    assert la == pytest.approx(math.exp(fit.mu + 0.4 - fixed[1]))


def test_unseen_club_gets_its_association_prior_and_unknown_association_gets_g():
    matches, _, countries = _simulate(n=2000)
    countries.country_of["NEWX"] = "X"
    fit = uor.fit_outscope(matches, countries, mode=uor.MODE_FITTED, tau_club=5, tau_assoc=5)
    mx = fit.assoc["X"]
    assert fit.oos_rating("NEWX") == pytest.approx((fit.g_A + mx[0], fit.g_D + mx[1]))
    assert fit.oos_rating("NOBODY") == pytest.approx((fit.g_A, fit.g_D))


def test_huge_tau_club_collapses_fitted_onto_prior():
    matches, _, countries = _simulate(n=2000)
    big = uor.fit_outscope(matches, countries, mode=uor.MODE_FITTED, tau_club=1e7, tau_assoc=5)
    prior = uor.fit_outscope(matches, countries, mode=uor.MODE_PRIOR, tau_assoc=5)
    for c in ("X1", "Y2"):
        assert big.oos_rating(c) == pytest.approx(prior.oos_rating(c), abs=1e-3)


def test_zero_weight_matches_and_extra_time_matches_do_not_train():
    matches, _, countries = _simulate(n=1500)
    poison = [_m(10_000 + i, "X1", "Y1", 0, 9) for i in range(300)]
    base = uor.fit_outscope(matches, countries, mode=uor.MODE_FITTED, tau_club=5, tau_assoc=5)
    w = uor.fit_outscope(matches + poison, countries, mode=uor.MODE_FITTED, tau_club=5, tau_assoc=5,
                         weights=[1.0] * len(matches) + [0.0] * len(poison))
    et = uor.fit_outscope(matches + [_m(20_000 + i, "X1", "Y1", 0, 9, extra_time=True) for i in range(300)],
                          countries, mode=uor.MODE_FITTED, tau_club=5, tau_assoc=5)
    for fit in (w, et):
        assert fit.oos_rating("X1") == pytest.approx(base.oos_rating("X1"), abs=1e-4)
    assert et.n_matches == base.n_matches
    with pytest.raises(ValueError):
        uor.fit_outscope(matches, countries, mode=uor.MODE_FITTED, weights=[1.0])
    with pytest.raises(ValueError):
        uor.fit_outscope(matches, countries, mode="nope")


def test_recency_weights_halve_at_the_half_life_and_none_is_flat():
    anchor = date(2024, 7, 1)
    w = uor.recency_weights([anchor, anchor - timedelta(days=365), anchor - timedelta(days=730)], anchor, 365)
    assert list(w) == pytest.approx([1.0, 0.5, 0.25])
    assert list(uor.recency_weights([anchor, date(2015, 1, 1)], anchor, None)) == [1.0, 1.0]


def test_select_taus_returns_grid_values_and_breaks_ties_toward_the_larger_tau():
    matches, _, countries = _simulate(n=1200)
    train, val = matches[:900], matches[900:]
    tc, ta, scores = uor.select_taus(train, [1.0] * len(train), val, countries, mode=uor.MODE_FITTED,
                                     grid=(2.0, 50.0))
    assert tc in (2.0, 50.0) and ta in (2.0, 50.0) and len(scores) == 4
    assert scores[f"{tc:g}|{ta:g}"] == min(scores.values())
    # prior mode: tau_club is not searched
    _, _, prior_scores = uor.select_taus(train, [1.0] * len(train), val, countries, mode=uor.MODE_PRIOR,
                                         grid=(2.0, 50.0))
    assert len(prior_scores) == 2


def test_effective_in_scope_applies_beta_and_the_league_offset():
    const = ulo.CrossFit(mu=0.1, eta=0.3, beta=1.5, offsets={"epl": 0.2, "eredivisie": -0.3},
                         leagues=("epl", "eredivisie"), n_matches=10)
    assert uor.effective_in_scope(0.1, -0.2, "epl", const) == pytest.approx((0.35, -0.1))
    assert uor.effective_in_scope(0.1, -0.2, "eredivisie", const) == pytest.approx((-0.15, -0.6))


def test_thin_clubs_counts_oos_sides_in_the_window_only():
    ms = [_m(i, "A", "B", 1, 0, season=2023) for i in range(6)]
    ms += [_m(10, "B", "IN", 1, 0, away_oos=False, season=2023), _m(11, "A", "B", 1, 0, season=2019)]
    n, thin = uor.thin_clubs(ms, range(2020, 2024))
    assert n["A"] == 6 and n["B"] == 7 and "IN" not in n
    assert thin == set()
    _, thin2 = uor.thin_clubs(ms, range(2020, 2024), threshold=7)
    assert thin2 == {"A"}


def test_score_match_scores_extra_time_as_a_draw():
    fit = uor.OutscopeFit(mode=uor.MODE_FIXED, mu=0.2, eta=0.3)
    win = _m(1, "A", "B", 3, 1)
    aet = _m(2, "A", "B", 3, 1, extra_time=True)
    probs = ulo.outcome_probs(*fit.rates(win))
    assert uor.score_match(fit, win)["log_loss"] == pytest.approx(-math.log(probs[0]))
    assert uor.score_match(fit, aet)["log_loss"] == pytest.approx(-math.log(probs[1]))


def test_rating_table_reports_production_units_and_thin_flag():
    matches, _, countries = _simulate(n=1500)
    fit = uor.fit_outscope(matches, countries, mode=uor.MODE_FITTED, tau_club=5, tau_assoc=5)
    rows = uor.rating_table(fit, beta=2.0, names={"X1": "Ex One"}, counts={"X1": 3}, thin={"X1"})
    x1 = next(r for r in rows if r["team_id"] == "X1")
    assert x1["team"] == "Ex One" and x1["thin"] and x1["recent_matches"] == 3 and x1["association"] == "X"
    assert x1["attack_rating"] == pytest.approx(x1["A"] / 2.0)
    assert rows[0]["A"] + rows[0]["D"] >= rows[-1]["A"] + rows[-1]["D"]
