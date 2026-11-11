"""The NBA live re-sim publishes its own chance of overtime (todo #789, lane nba-resim-overtime-prob).

#788 found the re-sim's whole late close-game miss was overtime: 8 of 160 games went to OT and each erred by about +21
points. Whether the re-sim priced that chance right could not be checked, because the full-game numbers fold OT in and
nothing kept the share of draws whose regulation ended level. This pins that share from the draw loop to the lane
(`modelOvertimeProb`) to the history row (`p_ot`), and on the real engine."""
from __future__ import annotations

import numpy as np

from syndicate.features.nba import live_resim as lr
from tests.basketball_engine_fixtures import synthetic_game_kwargs


def _draws(rows):
    """`rows` of (home_regulation_quarters, away_regulation_quarters, home_ot, away_ot); OT None = no overtime."""
    it = iter(rows)

    def simulate(rng, gs):
        hq, aq, h_ot, a_ot = next(it)
        hb = {"players": []} if h_ot is None else {"players": [], "ot_pts": h_ot}
        ab = {"players": []} if a_ot is None else {"players": [], "ot_pts": a_ot}
        return hb, ab, list(hq), list(aq)
    return simulate


TIED = ([25, 25, 25, 25], [30, 20, 25, 25], [12], [8])  # level after regulation, though no quarter is
DECIDED = ([25, 25, 25, 26], [25, 25, 25, 25], None, None)


def _facts():
    return lr.ResumeFacts("401", "GSW", "NYK", 98, 98, 4, 4.0, "home", 99, "t")


def _snapshot(lane):
    return {"generatedAt": "g", "date": "2026-11-11",
            "games": [{"event_id": "401", "home_code": "GSW", "away_code": "NYK", "gameLens": [lane]}]}


def test_overtime_prob_is_the_share_of_draws_level_after_regulation():
    out = lr.resim_live_game({}, None, sims=100, simulate=_draws([TIED] * 30 + [DECIDED] * 70))
    assert out["overtime_prob"] == 0.3
    # the full-game numbers already fold the overtime in, which is why they cannot show this
    assert out["home_win_prob"] == 1.0 and "0" not in out["margin_dist"]


def test_the_rule_is_level_after_regulation_not_overtime_points():
    """A real game level after regulation always goes to overtime, so that is what P(OT) is graded against. A draw
    whose engine wrote no `ot_pts` (its overtime loop swallows errors) or a scoreless OT still counts."""
    no_ot_written = ([25, 25, 25, 25], [25, 25, 25, 25], None, None)
    scoreless_then_decided = ([25, 25, 25, 25], [25, 25, 25, 25], [0, 6], [0, 2])
    out = lr.resim_live_game({}, None, sims=100,
                             simulate=_draws([no_ot_written] * 10 + [scoreless_then_decided] * 10 + [DECIDED] * 80))
    assert out["overtime_prob"] == 0.2


def test_no_tie_no_overtime():
    out = lr.resim_live_game({}, None, sims=100, simulate=_draws([DECIDED] * 100))
    assert out["overtime_prob"] == 0.0


def test_the_lane_and_the_history_row_carry_it():
    result = lr.resim_live_game({}, None, sims=100, simulate=_draws([TIED] * 30 + [DECIDED] * 70))
    lane = lr.build_game_lens(_facts(), result)[0]
    assert lane["modelOvertimeProb"] == 0.3
    row = lr.history_rows(_snapshot(lane))[0]
    assert row["p_ot"] == 0.3 and row["p_home"] == 1.0

    # off != on: the same path with no tied draw records 0.0, not the same number
    flat = lr.build_game_lens(_facts(), lr.resim_live_game({}, None, sims=100, simulate=_draws([DECIDED] * 100)))[0]
    assert lr.history_rows(_snapshot(flat))[0]["p_ot"] == 0.0


def test_refused_and_carried_lanes_record_no_overtime_number():
    refused = lr.build_game_lens(_facts(), lr.NbaResimRefusal("regulation_over"))[0]
    assert "modelOvertimeProb" not in refused
    assert lr.history_rows(_snapshot(refused))[0]["p_ot"] is None

    # a carried lane repeats an earlier tick's numbers; the history keeps those under their own tick, not again here
    carried = {**lr.build_game_lens(_facts(), lr.resim_live_game({}, None, sims=100, simulate=_draws([TIED] * 100)))[0],
               "carriedForward": True, "carriedRefusal": "budget_exhausted"}
    assert carried["modelOvertimeProb"] == 1.0
    assert lr.history_rows(_snapshot(carried))[0]["p_ot"] is None


def test_a_result_without_the_field_publishes_none_not_zero():
    result = {"home_win_prob": 0.5, "sims_run": 100, "home_margin_mean": 0.0, "total_mean": 200.0, "total_dist": {},
              "margin_dist": {}}
    assert lr.build_game_lens(_facts(), result)[0]["modelOvertimeProb"] is None


def _engine_kwargs():
    kw = synthetic_game_kwargs(np.random.default_rng(7), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    return kw


def test_real_engine_overtime_prob_tracks_the_score_and_the_clock():
    """Reachability on the real engine: resumed in overtime every draw played it; a tie with 30 seconds left is a real
    chance, and a smaller one with a minute left; a 30-point game with 30 seconds left has none.

    (Not pinned, recorded in the #789 findings: on these synthetic inputs a tie with 4 seconds left reads 1.0 -- the
    engine scores nothing in the last few seconds, so its P(OT) there is the share of draws reaching 0:00 level.)"""
    from syndicate.features.basketball_engine.resume import GameState

    kw = _engine_kwargs()
    in_ot = GameState(period=5, seconds_remaining=None, home_period_pts=(25, 25, 25, 25), away_period_pts=(25, 25, 25, 25))
    assert lr.resim_live_game(kw, in_ot, sims=100, base_seed=3)["overtime_prob"] == 1.0

    def level(seconds):
        gs = GameState(period=4, seconds_remaining=seconds, home_period_pts=(25, 25, 25, 23),
                       away_period_pts=(25, 25, 25, 23))
        return lr.resim_live_game(kw, gs, sims=200, base_seed=3)["overtime_prob"]

    p30, p60 = level(30), level(60)
    assert 0.1 < p30 < 0.9 and 0.0 < p60 < p30

    rout = GameState(period=4, seconds_remaining=30, home_period_pts=(35, 35, 30, 20), away_period_pts=(25, 25, 25, 20))
    assert lr.resim_live_game(kw, rout, sims=100, base_seed=3)["overtime_prob"] == 0.0
