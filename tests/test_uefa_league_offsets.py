"""Hermetic tests for the UEFA club -> league placement and the cross-league offset fit (todo #699)."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from syndicate.features.soccer import uefa_league_offsets as ulo


def _row(day, home, away, hs=1, as_=0, **extra):
    return {"date": f"{day}T19:00Z", "home_team_id": home, "away_team_id": away,
            "home_score": hs, "away_score": as_, **extra}


# --------------------------------------------------------------------------- placement


def test_membership_is_season_scoped_promotion_and_relegation():
    domestic = {
        "epl": [_row("2023-09-01", "1", "2"), _row("2024-09-01", "1", "3")],
        "championship": [_row("2023-09-01", "3", "4"), _row("2024-09-01", "2", "4")],
    }
    m = ulo.build_membership(domestic)
    assert m.league(2023, "2") == "epl" and m.league(2024, "2") == "championship"  # relegated
    assert m.league(2023, "3") == "championship" and m.league(2024, "3") == "epl"  # promoted
    # A July..June window: a May 2024 match belongs to season 2023.
    assert ulo.build_membership({"epl": [_row("2024-05-01", "9", "8")]}).league(2023, "9") == "epl"
    assert m.league(2025, "1") == ""


def test_membership_conflict_takes_the_majority_and_is_reported():
    domestic = {
        "bundesliga": [_row("2023-09-01", "5", "6"), _row("2023-10-01", "7", "5")],
        "championship": [_row("2023-11-01", "5", "8")],  # an id collision / data error
    }
    m = ulo.build_membership(domestic)
    assert m.league(2023, "5") == "bundesliga"
    assert m.conflicts == [{"season": 2023, "team_id": "5", "leagues": {"bundesliga": 2, "championship": 1}}]


def test_place_and_coverage_count_cross_same_and_unplaced():
    m = ulo.Membership(league_of={(2023, "1"): "epl", (2023, "2"): "epl", (2023, "3"): "serie_a"})
    uefa = [
        {"season": 2023, "home_team_id": "1", "away_team_id": "3", "home_team": "A", "away_team": "C"},
        {"season": 2023, "home_team_id": "1", "away_team_id": "2", "home_team": "A", "away_team": "B"},
        {"season": 2023, "home_team_id": "3", "away_team_id": "99", "home_team": "C", "away_team": "Z"},
        {"season": 2024, "home_team_id": "1", "away_team_id": "3", "home_team": "A", "away_team": "C"},
    ]
    placed = ulo.place_matches(uefa, m)
    assert [ulo.is_cross_league(r) for r in placed] == [True, False, False, False]
    cov = ulo.coverage(placed)
    assert (cov["both_placed"], cov["one_placed"], cov["neither_placed"]) == (2, 1, 1)
    assert (cov["cross_league"], cov["same_league"]) == (1, 1)
    assert cov["clubs"] == 4 and cov["clubs_never_placed"] == 1  # "99"; 2024 rows place nobody
    assert cov["pairs"] == {"epl|serie_a": 1}


def test_match_flags_extra_time_and_final_neutral():
    payload = {"events": [
        {"id": "1", "season": {"slug": "final"},
         "competitions": [{"status": {"type": {"name": "STATUS_FULL_TIME"}}}]},
        {"id": "2", "competitions": [{"status": {"type": {"name": "STATUS_FINAL_AET"}}}]},
        {"id": "3", "competitions": [{"status": {"type": {"name": "STATUS_FINAL_PEN"}}}]},
        {"id": "4", "competitions": [{"status": {"type": {"name": "STATUS_FULL_TIME"}}}]},
    ]}
    flags = ulo.match_flags(payload)
    assert flags["1"] == {"status": "STATUS_FULL_TIME", "neutral": True, "extra_time": False}
    assert flags["2"]["extra_time"] and flags["3"]["extra_time"]
    assert not flags["4"]["extra_time"] and not flags["4"]["neutral"]


# --------------------------------------------------------------------------- domestic ratings


def test_domestic_index_never_reads_the_kickoff_day_or_later():
    rows = [_row("2023-09-01", "1", "2", 3, 0), _row("2023-09-08", "2", "1", 0, 3),
            _row("2023-09-15", "1", "2", 9, 0)]  # the kickoff day: must be ignored
    idx = ulo.DomesticRatingIndex({"epl": rows})
    before = idx.ratings_as_of("epl", date(2023, 9, 15))
    assert before["1"][2] == 2 and before["2"][2] == 2
    after = idx.ratings_as_of("epl", date(2023, 9, 16))
    assert after["1"][2] == 3
    assert after["1"][0] > before["1"][0]  # the 9-0 moved the attack only once it was in the past


def test_domestic_index_window_is_365_days():
    rows = [_row("2022-01-01", "1", "2"), _row("2023-06-01", "1", "2")]
    idx = ulo.DomesticRatingIndex({"epl": rows})
    assert idx.rating("epl", "1", date(2023, 6, 2))[2] == 1
    assert idx.rating("epl", "3", date(2023, 6, 2)) is None


def test_domestic_fit_ranks_the_stronger_side_and_is_penalised_toward_zero():
    rng = np.random.default_rng(0)
    hi, ai = rng.integers(0, 4, 400), rng.integers(0, 4, 400)
    keep = hi != ai
    hi, ai = hi[keep], ai[keep]
    true_att = np.array([0.5, 0.0, 0.0, -0.5])
    hg = rng.poisson(np.exp(0.2 + 0.2 + true_att[hi]))
    ag = rng.poisson(np.exp(0.2 + true_att[ai]))
    _, _, att, dfn = ulo.fit_poisson_ratings(hi, ai, hg, ag, 4, kappa=10)
    assert att[0] > att[1] > att[3] and att[0] > att[2] > att[3]
    _, _, att_hard, _ = ulo.fit_poisson_ratings(hi, ai, hg, ag, 4, kappa=1e4)
    assert np.abs(att_hard).max() < np.abs(att).max() / 5


# --------------------------------------------------------------------------- cross-league model


def _synthetic_cross(true_offsets, n=3000, seed=1, beta=1.0):
    rng = np.random.default_rng(seed)
    leagues = list(true_offsets)
    out = []
    for i in range(n):
        hl, al = rng.choice(len(leagues), 2, replace=False)
        h, a = leagues[hl], leagues[al]
        ha, hd, aa, ad = rng.normal(0, 0.25, 4)
        oh, oa = true_offsets[h], true_offsets[a]
        lh = math.exp(0.1 + 0.25 + beta * (ha - ad) + oh - oa)
        la = math.exp(0.1 + beta * (aa - hd) + oa - oh)
        out.append(ulo.CrossMatch(str(i), 2020, h, a, ha, hd, aa, ad, False,
                                  int(rng.poisson(lh)), int(rng.poisson(la)), False))
    return out


def test_offset_fit_recovers_known_offsets_and_centres_them():
    truth = {"epl": 0.3, "la_liga": 0.2, "eredivisie": -0.2, "belgian_pro_league": -0.3}
    fit = ulo.fit_cross_league(_synthetic_cross(truth), with_offset=True)
    assert abs(sum(fit.offsets.values())) < 1e-9
    for lg, v in truth.items():
        assert fit.offsets[lg] == pytest.approx(v, abs=0.05)
    assert fit.eta == pytest.approx(0.25, abs=0.06)
    assert fit.beta == pytest.approx(1.0, abs=0.15)


def test_no_offset_arm_has_no_offsets_and_offset_arm_is_reachable():
    """Reachability (off != on): the two arms must produce different probabilities."""
    truth = {"epl": 0.4, "belgian_pro_league": -0.4}
    matches = _synthetic_cross(truth, n=800)
    base = ulo.fit_cross_league(matches, with_offset=False)
    off = ulo.fit_cross_league(matches, with_offset=True)
    assert base.offsets == {}
    m = matches[0]
    assert ulo.outcome_probs(*base.rates(m)) != pytest.approx(ulo.outcome_probs(*off.rates(m)), abs=1e-3)
    loss_base = np.mean([ulo.score_match(base, x)["log_loss"] for x in matches])
    loss_off = np.mean([ulo.score_match(off, x)["log_loss"] for x in matches])
    assert loss_off < loss_base


def test_extra_time_is_excluded_from_training_and_scored_as_a_draw():
    m = ulo.CrossMatch("x", 2020, "epl", "serie_a", 0, 0, 0, 0, False, 3, 1, True)
    assert ulo.result_index(m) == 1
    matches = _synthetic_cross({"epl": 0.1, "serie_a": -0.1}, n=200) + [m]
    assert ulo.fit_cross_league(matches, with_offset=True).n_matches == 200


def test_neutral_removes_home_advantage():
    fit = ulo.CrossFit(mu=0.1, eta=0.3, beta=1.0, offsets={}, leagues=(), n_matches=0)
    home = ulo.CrossMatch("a", 2020, "epl", "serie_a", 0, 0, 0, 0, False, 0, 0, False)
    neutral = ulo.CrossMatch("b", 2020, "epl", "serie_a", 0, 0, 0, 0, True, 0, 0, False)
    assert fit.rates(home)[0] == pytest.approx(math.exp(0.4))
    assert fit.rates(neutral)[0] == pytest.approx(math.exp(0.1)) == pytest.approx(fit.rates(neutral)[1])


def test_outcome_probs_sum_to_one_and_are_symmetric():
    h, d, a = ulo.outcome_probs(1.3, 1.3)
    assert h + d + a == pytest.approx(1.0) and h == pytest.approx(a)
    assert ulo.outcome_probs(2.5, 0.5)[0] > 0.7


def test_verdict_rule_matches_the_registration():
    assert ulo.verdict(-0.01, -0.02, -0.001) == "SUPPORTED"
    assert ulo.verdict(-0.01, -0.02, 0.001) == "NOT DEMONSTRATED"
    assert ulo.verdict(0.0, -0.01, 0.01) == "FALSIFIED"
    assert ulo.verdict(0.01, 0.005, 0.02) == "FALSIFIED"


def test_paired_bootstrap_ci_is_deterministic_and_brackets_the_mean():
    diffs = np.random.default_rng(3).normal(-0.01, 0.1, 500)
    a = ulo.paired_bootstrap_ci(diffs)
    assert a == ulo.paired_bootstrap_ci(diffs)
    assert a[1] < a[0] < a[2]
    assert all(math.isnan(x) for x in ulo.paired_bootstrap_ci([]))


def test_domestic_leagues_exclude_uefa_competitions():
    assert set(ulo.DOMESTIC_LEAGUES) == {"epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "mls",
                                         "eredivisie", "primeira_liga", "championship", "belgian_pro_league"}


def test_unit_weights_reproduce_the_unweighted_fit():
    matches = _synthetic_cross({"epl": 0.3, "eredivisie": -0.3}, n=600)
    a = ulo.fit_cross_league(matches, with_offset=True)
    b = ulo.fit_cross_league(matches, with_offset=True, weights=[1.0] * len(matches))
    assert b.beta == pytest.approx(a.beta, abs=1e-6)
    assert b.offsets["epl"] == pytest.approx(a.offsets["epl"], abs=1e-6)


def test_recency_weights_track_a_drifted_offset_and_are_reachable():
    """A drifted era is recovered when old matches are down-weighted (off != on)."""
    old = _synthetic_cross({"epl": 0.0, "la_liga": 0.0}, n=3000, seed=2)
    new = _synthetic_cross({"epl": 0.3, "la_liga": -0.3}, n=3000, seed=3)
    matches = old + new
    flat = ulo.fit_cross_league(matches, with_offset=True)
    rec = ulo.fit_cross_league(matches, with_offset=True, weights=[0.01] * len(old) + [1.0] * len(new))
    assert flat.offsets["epl"] == pytest.approx(0.15, abs=0.05)
    assert rec.offsets["epl"] == pytest.approx(0.3, abs=0.05)


def test_weights_must_align_with_matches():
    with pytest.raises(ValueError):
        ulo.fit_cross_league(_synthetic_cross({"epl": 0.1, "eredivisie": -0.1}, n=10), with_offset=True, weights=[1.0])
