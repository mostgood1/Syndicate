"""Lane `football-scenario-calibration` H3: points the offense did not score.

OFF (default): no return touchdowns and no safeties. ON: defensive TDs on
turnovers, punt and kickoff return TDs, and safeties from inside the own 10, at
`situation_model.NON_OFFENSIVE_RATES`.
"""
from __future__ import annotations

from dataclasses import replace
from random import Random

from syndicate.features.football.sim_engine.smartsim2 import drive_simulator as D
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE_DEFAULT
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome, SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE_DEFAULT
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state
from syndicate.features.football.sim_engine.smartsim2.situation_model import NON_OFFENSIVE_RATES, non_offensive_rates
from syndicate.features.shared.calibration_profile_store import profile_with_overrides

ON_NFL = replace(NFL_CALIBRATION_PROFILE_DEFAULT, non_offensive_scoring=True)


def _drive_points(out):
    return sum(int(d.get("points_scored") or 0) for d in out.drive_log)


def _total(out):
    return out.final_score["home"] + out.final_score["away"]


def test_default_is_off_and_round_trips():
    assert NFL_CALIBRATION_PROFILE_DEFAULT.non_offensive_scoring is False
    assert NCAAF_CALIBRATION_PROFILE_DEFAULT.non_offensive_scoring is False
    assert profile_with_overrides(NFL_CALIBRATION_PROFILE_DEFAULT, ON_NFL.to_dict()).non_offensive_scoring is True


def test_rates_are_probabilities_and_select_by_sport():
    for sport in ("nfl", "ncaaf"):
        r = NON_OFFENSIVE_RATES[sport]
        for k in ("def_td", "punt_ret_td", "ko_ret_td", "safety_1_5", "safety_6_10"):
            assert 0.0 < r[k] < 0.2
        assert r["safety_1_5"] > r["safety_6_10"]
        assert 20 <= r["free_kick_start"] <= 50
    assert non_offensive_rates("ncaaf") is NON_OFFENSIVE_RATES["ncaaf"]
    assert non_offensive_rates("nfl") is NON_OFFENSIVE_RATES["nfl"]


def test_off_has_no_non_offensive_points():
    for seed in range(1, 21):
        out = simulate_game(SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed))
        assert _total(out) == _drive_points(out)


def test_on_produces_them_at_about_the_measured_level():
    """Reachability, then level: ON != OFF, and non-offensive points/game land near
    the real NFL 1.76/game these rates imply (wide band: 300 games)."""
    nonoff = 0
    differs = False
    for seed in range(1, 301):
        inp = SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed)
        on = simulate_game(inp, profile=ON_NFL)
        nonoff += _total(on) - _drive_points(on)
        if seed <= 20:
            differs = differs or on.final_score != simulate_game(inp).final_score
    assert differs
    per_game = nonoff / 300
    assert 0.8 < per_game < 3.0, per_game


def test_return_touchdown_scores_for_the_team_holding_the_ball_then_kicks_back():
    st = build_initial_possession_state(home_team="H", away_team="A", owner="away", field_position=60,
                                        clock_remaining=500, score_home=3, score_away=0)

    class Always:
        def random(self):
            return 0.0

    out = D._return_touchdown(st, PossessionOutcome.TURNOVER, Always(), ON_NFL)
    assert (out.score_home, out.score_away) == (3, 7)
    assert (out.possession_owner, out.field_position, out.down) == ("home", 25, 1)
    # a score with no clock left is not followed by a kickoff
    done = replace(st, clock_remaining=0)
    assert D._return_touchdown(done, PossessionOutcome.TOUCHDOWN, Always(), ON_NFL) == done
    # end of half / turnover on downs: nothing to return
    assert D._return_touchdown(st, PossessionOutcome.TURNOVER_ON_DOWNS, Always(), ON_NFL) == st


def test_safety_gives_two_points_and_the_free_kick():
    inp = SmartSim2SimulationInput(home_team="H", away_team="A", seed=1)
    st = build_initial_possession_state(home_team="H", away_team="A", owner="home", field_position=2,
                                        quarter=2, clock_remaining=600)
    for seed in range(1, 400):
        res = D.simulate_drive(st, inp, rng=Random(seed), profile=ON_NFL)
        if res.outcome == PossessionOutcome.SAFETY:
            assert (res.end_state.score_home, res.end_state.score_away) == (0, 2)
            assert res.end_state.possession_owner == "away"
            assert res.end_state.field_position == NON_OFFENSIVE_RATES["nfl"]["free_kick_start"]
            return
    raise AssertionError("no safety in 400 drives from the own 2 (rate 0.03/snap)")
