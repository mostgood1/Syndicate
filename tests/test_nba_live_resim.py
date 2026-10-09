"""Tests for syndicate/features/nba/live_resim.py (P3, lane nba-native-live-resim).

Summaries come from P2's synthetic ESPN builder (`tests/basketball_pbp_fixtures.Game`); engine inputs from P1's
`tests/basketball_engine_fixtures.synthetic_game_kwargs`. Hermetic: no network, no data/."""
from __future__ import annotations

import numpy as np
import pytest

from syndicate.features.nba import live_resim as lr
from tests.basketball_engine_fixtures import synthetic_game_kwargs
from tests.basketball_pbp_fixtures import Game


def _in_q2():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3).foul(1, "9:00", "home", "h2")
    g.end_period(1)
    g.shot(2, "11:40", "home", "h1").sub(2, "10:00", "away", "a6", "a5").shot(2, "9:30", "away", "a6")
    return g


# ------------------------------------------------------------------------------------------- resume state

def test_resume_mid_period_carries_score_split_clock_fouls_and_fives():
    st, gs, facts = lr.resume_from_summary(_in_q2().summary(), date="2026-01-15")
    assert (gs.period, gs.seconds_remaining) == (2, 570)
    assert gs.home_period_pts == (2, 2) and gs.away_period_pts == (3, 2)
    assert (facts.home_score, facts.away_score) == (4, 5)
    assert set(gs.away_on_floor) == {"A1", "A2", "A3", "A4", "A6"}  # ESPN display names, re-keyed later
    assert gs.home_player_fouls == {"H2": 1} and gs.away_player_fouls == {}
    assert gs.home_team_fouls == 0  # the Q1 foul is not in the Q2 bucket


def test_resume_at_a_quarter_end_starts_the_next_period_from_its_tip():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").end_period(1)
    _st, gs, _f = lr.resume_from_summary(g.summary())
    assert (gs.period, gs.seconds_remaining) == (2, None)
    assert gs.home_period_pts == (2, 0) and gs.away_period_pts == (0, 0)
    assert gs.home_on_floor == () and gs.possession is None  # a new period: lineup sampled, tip is a coin flip


def test_end_of_regulation_tied_resumes_overtime_and_decided_refuses():
    tied = Game("nba", state="in")
    tied.shot(1, "11:00", "home", "h1").shot(4, "1:00", "away", "a1").end_period(4)
    _st, gs, _f = lr.resume_from_summary(tied.summary())
    assert gs.period == 5 and gs.seconds_remaining is None
    decided = Game("nba", state="in")
    decided.shot(1, "11:00", "home", "h1").end_period(4)
    assert lr.resume_from_summary(decided.summary()) == lr.NbaResimRefusal("regulation_over")


@pytest.mark.parametrize("state,reason", [("pre", "game_not_started"), ("post", "game_final"),
                                          ("halftime??", "game_state_unrecognised")])
def test_status_refusals_are_named(state, reason):
    g = Game("nba", state=state)
    g.shot(1, "11:00", "home", "h1")
    assert lr.resume_from_summary(g.summary()).reason == reason


def test_pbp_score_disagreeing_with_the_official_score_is_refused():
    g = _in_q2()
    out = lr.resume_from_summary(g.summary(official=(9, 5)))
    assert isinstance(out, lr.NbaResimRefusal) and out.reason == "pbp_score_mismatch"


# ------------------------------------------------------------------------------------------- inputs

def _kwargs(seed=7):
    kw = synthetic_game_kwargs(np.random.default_rng(seed), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    return kw


def test_engine_inputs_round_trip_and_named_refusals(tmp_path):
    kw = {k: k for k in lr._INPUT_KEYS}  # values are opaque to the store
    p = lr.persist_engine_inputs("2026-01-15", "gsw", "nyk", kw, root=tmp_path)
    assert p.name == "GSW_NYK.pkl" and "engine_inputs" in str(p)
    assert lr.load_engine_inputs("2026-01-15", "GSW", "NYK", root=tmp_path) == kw
    assert lr.load_engine_inputs("2026-01-15", "BOS", "MIA", root=tmp_path).reason == "no_pregame_inputs"
    lr.persist_engine_inputs("2026-01-15", "LAL", "SAC", {"cfg": 1}, root=tmp_path)
    out = lr.load_engine_inputs("2026-01-15", "LAL", "SAC", root=tmp_path)
    assert out.reason == "pregame_inputs_incomplete" and "home_players" in out.detail


def test_names_map_across_accents_and_suffixes_and_a_partial_five_is_dropped():
    import pandas as pd
    from syndicate.features.basketball_engine.resume import GameState

    hf = pd.DataFrame({"player_name": ["Jusuf Nurkić", "Jaren Jackson Jr.", "A", "B", "C"]})
    af = pd.DataFrame({"player_name": ["X", "Y", "Z", "W", "V"]})
    gs = GameState(period=2, seconds_remaining=300, home_period_pts=(1, 1), away_period_pts=(1, 1),
                   home_on_floor=("JUSUF NURKIC", "Jaren Jackson", "A", "B", "C"),
                   away_on_floor=("X", "Y", "Z", "W", "Nobody"),
                   home_player_fouls={"Jusuf Nurkic": 3}, away_player_fouls={"Nobody": 6})
    new, rep = lr.map_state_names(gs, hf, af)
    assert new.home_on_floor == ("Jusuf Nurkić", "Jaren Jackson Jr.", "A", "B", "C")
    assert new.away_on_floor == () and rep["away_on_floor_matched"] == 4
    assert new.home_player_fouls == {"Jusuf Nurkić": 3} and new.away_player_fouls == {}


# ------------------------------------------------------------------------------------------- the re-sim

def _fake(totals):
    it = iter(totals)

    def simulate(rng, gs):
        h, a = next(it)
        return None, None, [h, 0, 0, 0], [a, 0, 0, 0]
    return simulate


def test_resim_aggregates_distributions_and_win_prob():
    draws = [(110, 100)] * 60 + [(100, 104)] * 40
    out = lr.resim_live_game({}, None, sims=100, simulate=_fake(draws))
    assert out["sims_run"] == 100 and out["home_win_prob"] == 0.6
    assert out["total_dist"] == {"204": 40, "210": 60}
    assert out["margin_dist"] == {"-4": 40, "10": 60}
    assert out["segments"]["q1"]["total_mean"] == pytest.approx(0.6 * 210 + 0.4 * 204)


def test_the_budget_is_a_refusal_never_a_thinner_number():
    t = iter(range(1000))
    out = lr.resim_live_game({}, None, sims=100, simulate=_fake([(1, 0)] * 100), deadline=50,
                             clock=lambda: next(t))
    assert out.reason == "budget_exhausted" and out.detail == "50/100"


def test_too_few_sims_and_engine_errors_are_refused_by_name():
    assert lr.resim_live_game({}, None, sims=10).reason == "sims_below_floor"

    def boom(rng, gs):
        raise ValueError("bad state")
    assert lr.resim_live_game({}, None, sims=100, simulate=boom).reason == "engine_resume_rejected"


def test_stable_seed_reproduces_an_unchanged_state():
    assert lr.stable_seed("401", 55) == lr.stable_seed("401", 55) != lr.stable_seed("401", 56)


def test_real_engine_resume_moves_the_answer_the_right_way():
    """Reachability: the resumed state reaches the engine. Up 15 at 5:00 Q4 must be nearly won; down 15 lost."""
    from syndicate.features.basketball_engine.resume import GameState

    kw = _kwargs()
    up = GameState(period=4, seconds_remaining=300, home_period_pts=(30, 30, 30, 15), away_period_pts=(25, 25, 25, 15))
    down = GameState(period=4, seconds_remaining=300, home_period_pts=(25, 25, 25, 15), away_period_pts=(30, 30, 30, 15))
    r_up = lr.resim_live_game(kw, up, sims=100, base_seed=1)
    r_down = lr.resim_live_game(kw, down, sims=100, base_seed=1)
    assert r_up["home_win_prob"] > 0.9 > 0.1 > r_down["home_win_prob"]
    # completed periods come from the state, so every draw's Q1-Q3 total is exactly the actual
    assert set(r_up["segments"]["q1"]["total_dist"]) == {"55"}
    assert r_up == lr.resim_live_game(kw, up, sims=100, base_seed=1)  # seeded: identical


# ------------------------------------------------------------------------------------------- lanes / snapshot

def test_a_refused_lane_carries_no_probability_at_all():
    lane = lr.build_game_lens(None, lr.NbaResimRefusal("no_pregame_inputs", "GSW_NYK.pkl"))[0]
    assert lane["source"] == lr.PREGAME_LENS_SOURCE == "pregame_only"
    assert "modelHomeWinProb" not in lane and "projection" not in lane
    assert lane["liveResimRefusal"] == "no_pregame_inputs"


def test_a_success_lane_carries_the_distributions_the_join_prices():
    facts = lr.ResumeFacts("401", "GSW", "NYK", 50, 48, 2, 0.0, None, 99, "t")
    res = {"sims_run": 200, "home_win_prob": 0.55, "total_mean": 220.0, "home_margin_mean": 2.0,
           "total_dist": {"220": 200}, "margin_dist": {"2": 200}, "segments": {}}
    lane = lr.build_game_lens(facts, res)[0]
    assert lane["source"] == "live_resim" and lane["simsRun"] == 200 and lane["modelHomeWinProb"] == 0.55
    assert lane["projection"]["totalRunsDist"] == {"220": 200} and lane["projection"]["marginDist"] == {"2": 200}


def test_snapshot_publishes_one_lane_per_live_game_and_counts_refusals(tmp_path, monkeypatch):
    live = _in_q2().summary()
    sb = {"events": [
        {"id": "999", "competitions": [{"status": {"type": {"state": "in"}}, "competitors": []}]},
        {"id": "998", "competitions": [{"status": {"type": {"state": "pre"}}, "competitors": []}]},
    ]}
    monkeypatch.setattr(lr, "resim_live_game", lambda *a, **k: {
        "sims_run": 200, "home_win_prob": 0.4, "total_mean": 1.0, "home_margin_mean": -1.0,
        "total_dist": {"1": 200}, "margin_dist": {"-1": 200}, "segments": {}})
    snap = lr.build_live_lens_snapshot("2026-01-15", fetch_scoreboard=lambda *_a: sb,
                                       fetch_summary=lambda *_a: live, inputs_root=tmp_path)
    assert len(snap["games"]) == 1  # the pregame game is not a live game
    assert snap["refusalsByReason"] == {"no_pregame_inputs": 1}
    lr.persist_engine_inputs("2026-01-15", "GSW", "NYK", {k: _kwargs()[k] if k in _kwargs() else None
                                                          for k in lr._INPUT_KEYS} | {
        "home_players": _kwargs()["home_players"], "away_players": _kwargs()["away_players"]}, root=tmp_path)
    snap = lr.build_live_lens_snapshot("2026-01-15", fetch_scoreboard=lambda *_a: sb,
                                       fetch_summary=lambda *_a: live, inputs_root=tmp_path)
    lane = snap["games"][0]["gameLens"][0]
    assert lane["source"] == "live_resim" and snap["refusalsByReason"] == {}
    assert (snap["games"][0]["home"], snap["games"][0]["away"]) == ("GSW", "NYK")
