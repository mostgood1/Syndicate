"""The NBA live re-sim's full game includes overtime (todo #763, lane nba-live-proj-actuals).

The engine returns REGULATION periods in its period lists and keeps overtime in the box's `ot_pts`. The re-sim summed
the period lists only, so a simulated overtime game was a regulation tie: no OT points in the total, and a home
non-win. On the fleet (6,215 live lanes, 10-13..11-05) every one of the 41 lanes resumed IN overtime published a home
win probability of 0.0."""
from __future__ import annotations

import numpy as np

from syndicate.features.nba import live_resim as lr
from tests.basketball_engine_fixtures import synthetic_game_kwargs


def _draws(rows):
    """`rows` of (home_reg, away_reg, home_ot, away_ot); OT None = the engine wrote no `ot_pts` (no overtime)."""
    it = iter(rows)

    def simulate(rng, gs):
        h, a, h_ot, a_ot = next(it)
        hb = {"players": []} if h_ot is None else {"players": [], "ot_pts": h_ot}
        ab = {"players": []} if a_ot is None else {"players": [], "ot_pts": a_ot}
        return hb, ab, [h, 0, 0, 0], [a, 0, 0, 0]
    return simulate


def test_an_overtime_draw_counts_its_overtime_points_and_its_winner():
    rows = [(100, 100, [12], [8])] * 50 + [(100, 100, [9, 11], [9, 7])] * 50
    out = lr.resim_live_game({}, None, sims=100, simulate=_draws(rows))
    assert out["home_win_prob"] == 1.0           # every OT was won by home; it used to read 0.0
    assert out["total_dist"] == {"220": 50, "236": 50}
    assert out["margin_dist"] == {"4": 100}
    assert out["segments"]["q1"]["total_mean"] == 200  # quarter blocks stay regulation-only


def test_a_regulation_game_is_unchanged():
    rows = [(110, 100, None, None)] * 60 + [(100, 104, None, None)] * 40
    out = lr.resim_live_game({}, None, sims=100, simulate=_draws(rows))
    assert out["home_win_prob"] == 0.6 and out["total_dist"] == {"204": 40, "210": 60}


def test_ot_points_reads_only_the_engines_list():
    assert lr._ot_points({"ot_pts": [5, 7]}) == 12
    assert lr._ot_points({}) == 0 and lr._ot_points(None) == 0 and lr._ot_points({"ot_pts": None}) == 0


def test_real_engine_resumed_in_overtime_is_not_a_certain_home_loss():
    """Reachability on the real engine: tied at the end of regulation, the resume plays overtime, and the published
    number must reflect who wins it -- not the regulation tie every draw shares."""
    from syndicate.features.basketball_engine.resume import GameState

    kw = synthetic_game_kwargs(np.random.default_rng(7), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    tied = GameState(period=5, seconds_remaining=None, home_period_pts=(25, 25, 25, 25), away_period_pts=(25, 25, 25, 25))
    out = lr.resim_live_game(kw, tied, sims=100, base_seed=3)
    assert 0.0 < out["home_win_prob"] < 1.0
    assert min(int(k) for k in out["total_dist"]) > 200  # every draw adds its overtime to the 200 already scored
    assert out["margin_dist"].get("0", 0) < 100
