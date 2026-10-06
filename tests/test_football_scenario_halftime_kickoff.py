"""Lane `football-scenario-calibration` H1: the second half starts with a kickoff.

`advance_quarter` only bumps the quarter, so before this switch the team holding
the ball at the half kept it at the same spot. `CalibrationProfile.halftime_kickoff`
(default OFF) gives the ball to the team that did not receive the opening kick.
"""
from __future__ import annotations

from dataclasses import replace

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE_DEFAULT,
    CalibrationProfile,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE_DEFAULT,
)
from syndicate.features.shared.calibration_profile_store import profile_with_overrides

ON_NFL = replace(NFL_CALIBRATION_PROFILE_DEFAULT, halftime_kickoff=True)
ON_NCAAF = replace(NCAAF_CALIBRATION_PROFILE_DEFAULT, halftime_kickoff=True)


def _first_q3_drive(out):
    return next(d for d in out.drive_log if int(d["start_state"]["quarter"]) == 3)


def _inp(seed, **kw):
    return SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed, **kw)


def test_default_is_off_on_both_sports():
    assert NFL_CALIBRATION_PROFILE_DEFAULT.halftime_kickoff is False
    assert NCAAF_CALIBRATION_PROFILE_DEFAULT.halftime_kickoff is False


def test_field_round_trips_through_the_artifact_dict():
    # A field missing from to_dict() loads back OFF and the switch is inert (the goal_line lesson).
    d = ON_NFL.to_dict()
    assert d["halftime_kickoff"] is True
    back = profile_with_overrides(NFL_CALIBRATION_PROFILE_DEFAULT, d)
    assert isinstance(back, CalibrationProfile) and back.halftime_kickoff is True


def test_on_kicks_off_to_the_team_that_did_not_receive_first():
    for prof in (ON_NFL, ON_NCAAF):
        for opener in ("home", "away"):
            for seed in range(1, 31):
                d = _first_q3_drive(simulate_game(_inp(seed, initial_possession_owner=opener), profile=prof))
                st = d["start_state"]
                assert st["possession_owner"] == ("away" if opener == "home" else "home")
                assert (st["field_position"], st["down"], st["distance"]) == (25, 1, 10)


def test_reachability_on_differs_from_off():
    off = [simulate_game(_inp(s)).final_score for s in range(1, 41)]
    on = [simulate_game(_inp(s), profile=ON_NFL).final_score for s in range(1, 41)]
    assert off != on
    # and OFF really is the bug being fixed: some seeds start Q3 away from the 25 / with the wrong team
    starts = [_first_q3_drive(simulate_game(_inp(s)))["start_state"] for s in range(1, 41)]
    assert any(st["field_position"] != 25 or st["possession_owner"] == "home" for st in starts)


def test_resume_after_the_half_is_untouched():
    for seed in range(1, 21):
        inp = _inp(seed, initial_quarter=3, initial_clock_seconds=600, initial_score_away=10)
        assert simulate_game(inp).final_score == simulate_game(inp, profile=ON_NFL).final_score


def test_first_half_resume_tosses_a_coin_for_the_receiver():
    owners = set()
    for seed in range(1, 41):
        inp = _inp(seed, initial_quarter=2, initial_clock_seconds=300, initial_score_home=7,
                   initial_possession_owner="away", initial_field_position=60)
        st = _first_q3_drive(simulate_game(inp, profile=ON_NFL))["start_state"]
        assert st["field_position"] == 25
        owners.add(st["possession_owner"])
    assert owners == {"home", "away"}
