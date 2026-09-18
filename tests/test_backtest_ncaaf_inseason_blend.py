"""Unit coverage for `scripts/backtest_ncaaf_inseason_blend.py`.

The load-bearing one is the LEAK BOUNDARY: a rating "as of week N" must be a
function of weeks < N only. It is tested by perturbing every result from week N
on and asserting that no family's ratings move -- the same frame that caught the
`/ppa/games` postseason leak (`generate_smartsim2_ncaaf_projections.load_ppa_games_week`).
Everything is synthetic; nothing here reads `data/` or calls CFBD.
"""
from __future__ import annotations

import itertools
import random

import numpy as np
import pytest

import scripts.backtest_ncaaf_inseason_blend as bt

TEAMS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
TRUE = {t: (6.0 - 1.7 * i, -4.0 + 1.1 * i) for i, t in enumerate(TEAMS)}  # (o, d) points vs average
PRIOR = {t: (28.0 + 0.5 * o, 27.0 - 0.5 * d) for t, (o, d) in TRUE.items()}  # SP+ shape, half-strength


def _season(weeks: int = 8, noise: float = 0.0, seed: int = 7):
    rng = random.Random(seed)
    games, ppa, gid = [], {}, 1
    pairs = list(itertools.combinations(TEAMS, 2))
    for week in range(1, weeks + 1):
        rng.shuffle(pairs)
        used: set[str] = set()
        for home, away in pairs:
            if home in used or away in used:
                continue
            used |= {home, away}
            hp = 28.0 + TRUE[home][0] - TRUE[away][1] + 2.5 + rng.gauss(0, noise)
            ap = 28.0 + TRUE[away][0] - TRUE[home][1] + rng.gauss(0, noise)
            games.append(bt.Game(gid, 2030, week, home, away, hp, ap, False, True, True))
            ppa[(gid, home)] = ((hp - 28.0) / 60.0, 60)
            ppa[(gid, away)] = ((ap - 28.0) / 60.0, 60)
            gid += 1
    return games, ppa


FAMILIES = [
    bt.Setting("ridge_pts", 4.0),
    bt.Setting("ridge_ppa", 4.0),
    bt.Setting("ridge_combo", 4.0, alpha=2.0),
    bt.Setting("ridge_pts_window", 4.0, window=3),
    bt.Setting("blend_pts", 4.0),
    bt.Setting("blend_ppa", 4.0),
]


@pytest.mark.parametrize("setting", FAMILIES, ids=lambda s: s.label)
def test_ratings_as_of_week_n_never_see_week_n_or_later(setting):
    games, ppa = _season(noise=3.0)
    before = bt.ratings_asof(setting, PRIOR, games, ppa, 5, 60.0)
    shuffled = [
        bt.Game(g.game_id, g.season, g.week, g.home, g.away,
                g.home_points + (40.0 if g.week >= 5 else 0.0), g.away_points, g.neutral, True, True)
        for g in games
    ]
    ppa_shuffled = {k: ((v[0] + (1.0 if any(g.game_id == k[0] and g.week >= 5 for g in games) else 0.0)), v[1])
                    for k, v in ppa.items()}
    after = bt.ratings_asof(setting, PRIOR, shuffled, ppa_shuffled, 5, 60.0)
    assert after == before
    # ...and the week-4 results DO move them (the check above is not vacuous).
    moved = [bt.Game(g.game_id, g.season, g.week, g.home, g.away,
                     g.home_points + (40.0 if g.week == 4 else 0.0), g.away_points, g.neutral, True, True)
             for g in games]
    moved_ppa = {k: ((v[0] + (1.0 if any(g.game_id == k[0] and g.week == 4 for g in games) else 0.0)), v[1])
                 for k, v in ppa.items()}
    assert bt.ratings_asof(setting, PRIOR, moved, moved_ppa, 5, 60.0) != before


def test_the_observation_window_is_strictly_before_week_n():
    games, ppa = _season()
    weeks = {ob.week for ob in bt.build_observations(games, ppa, 5)}
    assert weeks == {1, 2, 3, 4}
    assert {ob.week for ob in bt.build_observations(games, ppa, 5, window=2)} == {3, 4}


def test_with_no_games_played_every_family_returns_the_prior():
    games, ppa = _season()
    for setting in FAMILIES:
        got = bt.ratings_asof(setting, PRIOR, games, ppa, 1, 60.0)
        for team, (off, dfn) in PRIOR.items():
            assert got[team] == pytest.approx((off, dfn), abs=1e-6), setting.label


def test_a_weak_prior_ridge_recovers_the_true_ratings():
    games, ppa = _season(weeks=14)
    obs = bt.build_observations(games, ppa, 99)
    got = bt.fit_ridge(obs, PRIOR, lam=1e-4, weights={"pts": 1.0}, centre_on_prior=False)
    mean_o = np.mean([v[0] for v in TRUE.values()])
    mean_d = np.mean([v[1] for v in TRUE.values()])
    for team, (o, d) in TRUE.items():
        # Identified up to the league mean, which mu absorbs.
        assert got[team][0] - np.mean([v[0] for v in got.values()]) == pytest.approx(o - mean_o, abs=1e-3)
        assert got[team][1] - np.mean([v[1] for v in got.values()]) == pytest.approx(d - mean_d, abs=1e-3)


def test_ppa_rows_enter_on_the_points_scale():
    """The first cut entered PPA unscaled, weighting it ~1/beta^2 against the
    prior -- ridge_ppa returned the prior unchanged on real data."""
    games, ppa = _season(weeks=14)
    obs = bt.build_observations(games, ppa, 99)
    pts = bt.fit_ridge(obs, PRIOR, lam=1e-4, weights={"pts": 1.0}, centre_on_prior=False)
    via_ppa = bt.fit_ridge(obs, PRIOR, lam=1e-4, weights={"ppa": 1.0}, beta=60.0, centre_on_prior=False)
    spread = lambda r: max(v[0] for v in r.values()) - min(v[0] for v in r.values())
    assert spread(via_ppa) == pytest.approx(spread(pts), rel=1e-3)


def test_the_explicit_blend_runs_from_prior_to_current_with_k():
    games, ppa = _season(noise=2.0)
    heavy = bt.ratings_asof(bt.Setting("blend_pts", 1e9), PRIOR, games, ppa, 6, 60.0)
    light = bt.ratings_asof(bt.Setting("blend_pts", 1e-9), PRIOR, games, ppa, 6, 60.0)
    obs = bt.build_observations(games, ppa, 6)
    current = bt.to_sp_index(PRIOR, bt.fit_ridge(obs, PRIOR, lam=bt.CURRENT_LAMBDA, weights={"pts": 1.0},
                                                 centre_on_prior=False))
    for team in PRIOR:
        assert heavy[team] == pytest.approx(PRIOR[team], abs=1e-6)
        assert light[team] == pytest.approx(current[team], abs=1e-6)


def test_the_ppa_scale_is_recovered():
    games, ppa = _season(weeks=14)
    final = {t: (28.0 + o, 27.0 - d) for t, (o, d) in TRUE.items()}
    assert bt.fit_ppa_scale(final, games, ppa) == pytest.approx(60.0, rel=0.1)


@pytest.mark.parametrize("period,margin,garbage", [
    (1, 44, True), (1, 43, False), (2, 38, True), (3, 28, True), (3, 27, False),
    (4, 22, True), (4, 21, False), (5, 60, False),
])
def test_garbage_time_follows_the_cfbd_rule(period, margin, garbage):
    play = {"period": period, "offenseScore": margin, "defenseScore": 0}
    assert bt.is_garbage_time(play) is garbage


def test_closing_margin_is_minus_the_median_home_spread():
    rows = [
        {"id": 1, "lines": [{"spread": -7.0}, {"spread": -6.5}, {"spread": -7.5}]},
        {"id": 2, "lines": [{"spread": 3.0}, {"spread": None}]},
        {"id": 3, "lines": []},
    ]
    assert bt.closing_margins_from_rows(rows) == {1: 7.0, 2: -3.0}


def test_paired_delta_ci():
    actual = np.array([10.0, -3.0, 7.0, 0.0, 21.0, -14.0] * 20)
    base = actual + np.array([8.0, -8.0] * 60)
    same = bt.paired_delta_ci(base, base, actual, reps=500, seed=1)
    assert same["delta_mae"] == 0.0 and same["ci95"] == [0.0, 0.0]
    better = bt.paired_delta_ci(actual + np.array([2.0, -2.0] * 60), base, actual, reps=500, seed=1)
    assert better["delta_mae"] == pytest.approx(-6.0)
    assert better["ci95"][1] < 0


def test_market_regression_recovers_the_model_weight():
    rng = np.random.default_rng(3)
    market = rng.normal(0, 14, 3000)
    model = market + rng.normal(0, 6, 3000)
    actual = 1.0 + market + 0.5 * (model - market) + rng.normal(0, 3, 3000)
    fit = bt.market_regression(model, market, actual, reps=200, seed=1)
    assert fit["w"] == pytest.approx(0.5, abs=0.05)
    assert fit["b"] == pytest.approx(1.0, abs=0.05)
    assert fit["w_ci95"][0] < 0.5 < fit["w_ci95"][1]


def test_evaluation_games_are_rated_fbs_pairs_in_weeks_3_to_15():
    games = [
        bt.Game(1, 2030, 3, "alpha", "bravo", 1, 0, False, True, True),
        bt.Game(2, 2030, 2, "alpha", "bravo", 1, 0, False, True, True),    # week 2
        bt.Game(3, 2030, 16, "alpha", "bravo", 1, 0, False, True, True),   # week 16
        bt.Game(4, 2030, 5, "alpha", "zulu", 1, 0, False, True, True),     # no prior
        bt.Game(5, 2030, 5, "alpha", "bravo", 1, 0, False, True, False),   # FCS side
    ]
    sd = bt.SeasonData(2030, games, {}, PRIOR, {}, 60.0, "test")
    assert [g.game_id for g in sd.eval_games()] == [1]


def test_the_dispersion_control_is_the_prior_rescaled_and_never_a_candidate():
    games, ppa = _season()
    same = bt.ratings_asof(bt.Setting("control_scale", 1.0), PRIOR, games, ppa, 6, 60.0)
    assert same == pytest.approx(PRIOR)
    half = bt.ratings_asof(bt.Setting("control_scale", 0.5), PRIOR, games, ppa, 6, 60.0)
    # Same mean, half the spread -- i.e. SP_RATING_SCALE doubled.
    assert np.std([v[0] for v in half.values()]) == pytest.approx(0.5 * np.std([v[0] for v in PRIOR.values()]))
    assert all(s.family != "control_scale" for s in bt.all_settings())


def test_cfbd_ppa_rows_are_keyed_by_game_and_team():
    rows = [
        {"gameId": 7, "team": "Ohio State", "seasonType": "regular", "offense": {"overall": 0.31}},
        {"gameId": 7, "team": "Michigan", "seasonType": "postseason", "offense": {"overall": 0.5}},
        {"gameId": 8, "team": "Iowa", "seasonType": "regular", "offense": {"overall": None}},
    ]
    assert bt.game_ppa_from_cfbd_rows(rows) == {(7, bt.norm("Ohio State")): (0.31, 0)}


def test_engine_inputs_are_the_generators_own_centring():
    gen = bt.gen()
    means = gen.sp_league_means(PRIOR)
    expected = gen.sp_offense_defense_rating("alpha", PRIOR, means) + gen.sp_offense_defense_rating("hotel", PRIOR, means)
    assert bt.engine_inputs(PRIOR, "alpha", "hotel") == pytest.approx(expected)
    assert bt.engine_inputs(PRIOR, "alpha", "zulu") is None
