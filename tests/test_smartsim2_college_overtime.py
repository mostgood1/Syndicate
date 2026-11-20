"""todo #855: smartsim2 college overtime behind `CalibrationProfile.college_overtime` (lane ncaaf-college-overtime).

REACHABILITY FIRST (`model_engine_standard.md`): OFF is byte-identical to the pre-change engine (digests pinned on the
code before the edit, `.syndicate/findings_2026-11-20_ncaaf_college_overtime.md`), and ON changes a tied game. Then the
college rules themselves.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from syndicate.features.football.sim_engine.smartsim2 import game_simulator as gs
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE_DEFAULT,
    CalibrationProfile,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE,
    NCAAF_CALIBRATION_PROFILE_DEFAULT,
)

NFL = NFL_CALIBRATION_PROFILE_DEFAULT
NCAAF = NCAAF_CALIBRATION_PROFILE_DEFAULT
NCAAF_COT = replace(NCAAF, college_overtime=True)

# sha256 over `simulate_game(...).to_dict()` (json, sort_keys), seeds 1..20, from the code BEFORE this change.
# `ncaaf_pregame` equals tests/test_football_end_of_half_clock.py's own pin for the same inputs.
PINNED_OFF_DIGESTS = {
    "ncaaf_pregame": "2b2b1a67ebc85873c99b6113b5619a29c68954cb1a66762093bb744b50cb7c36",
    "ncaaf_tied_late": "2528c3745cb0746ab09750be5fc73f95acc324bd1c8e7829093731f7e90091f6",
    "nfl_tied_late": "c0d7eb8f093ac188d6b5ba973836d4f5e90ccdef6ed2700fe34697a8e17e2b92",
}
TIED_LATE = dict(initial_quarter=4, initial_clock_seconds=20, initial_score_home=24, initial_score_away=24,
                 initial_possession_owner="home", initial_field_position=20)
# Regulation already over and tied: the sim goes straight to overtime.
END_OF_REGULATION = dict(initial_quarter=4, initial_clock_seconds=0, initial_score_home=21, initial_score_away=21,
                         initial_possession_owner="home", initial_field_position=25)


def _inp(seed: int, **kw) -> SmartSim2SimulationInput:
    return SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed, home_offense_rating=0.1,
                                    away_defense_rating=-0.05, **kw)


def _digest(profile: CalibrationProfile, **kw) -> str:
    h = hashlib.sha256()
    for seed in range(1, 21):
        h.update(json.dumps(simulate_game(_inp(seed, **kw), profile=profile).to_dict(), sort_keys=True).encode())
    return h.hexdigest()


def _ot_drives(out):
    return [d for d in out.drive_log if int(d["start_state"]["quarter"]) >= 5]


def _points(drive) -> int:
    s, e = drive["start_state"], drive["end_state"]
    owner = s["possession_owner"]
    return (e["score_home"] - s["score_home"]) if owner == "home" else (e["score_away"] - s["score_away"])


# --------------------------------------------------------------------------
# REACHABILITY
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,profile,kw", [
    ("ncaaf_pregame", NCAAF, {}),
    ("ncaaf_tied_late", NCAAF, TIED_LATE),
    ("nfl_tied_late", NFL, TIED_LATE),
])
def test_REACHABILITY_off_is_byte_identical_to_the_pre_change_engine(name, profile, kw):
    assert profile.college_overtime is False
    assert _digest(profile, **kw) == PINNED_OFF_DIGESTS[name]


def test_REACHABILITY_on_changes_a_tied_game_and_raises_its_total():
    assert _digest(NCAAF_COT, **TIED_LATE) != PINNED_OFF_DIGESTS["ncaaf_tied_late"]
    off = [simulate_game(_inp(s, **END_OF_REGULATION), profile=NCAAF) for s in range(1, 61)]
    on = [simulate_game(_inp(s, **END_OF_REGULATION), profile=NCAAF_COT) for s in range(1, 61)]
    mean = lambda outs: sum(o.final_score["home"] + o.final_score["away"] - 42 for o in outs) / len(outs)  # noqa: E731
    assert mean(on) > mean(off) + 4.0


def test_a_game_not_tied_at_the_end_of_regulation_is_untouched():
    leading = dict(TIED_LATE, initial_score_home=31, initial_score_away=17)
    for seed in range(1, 21):
        assert simulate_game(_inp(seed, **leading), profile=NCAAF_COT).to_dict() == \
            simulate_game(_inp(seed, **leading), profile=NCAAF).to_dict()


def test_the_switch_defaults_off_everywhere_and_rides_to_dict():
    for profile in (NFL, NCAAF, NCAAF_CALIBRATION_PROFILE, CalibrationProfile(name="x")):
        assert profile.college_overtime is False
    assert CalibrationProfile(name="x").to_dict()["college_overtime"] is False
    assert NCAAF_COT.to_dict()["college_overtime"] is True


# --------------------------------------------------------------------------
# THE COLLEGE RULES
# --------------------------------------------------------------------------

def test_period_one_gives_both_teams_a_possession_from_the_opponents_25():
    for seed in range(1, 41):
        out = simulate_game(_inp(seed, **END_OF_REGULATION), profile=NCAAF_COT)
        first_period = [d for d in _ot_drives(out) if int(d["start_state"]["quarter"]) == 5]
        assert len(first_period) == 2, seed
        assert {d["start_state"]["possession_owner"] for d in first_period} == {"home", "away"}
        assert all(d["start_state"]["field_position"] == 75 for d in first_period)
        assert all((d["start_state"]["down"], d["start_state"]["distance"]) == (1, 10) for d in first_period)


def test_the_possession_order_alternates_by_period():
    for seed in range(1, 200):
        out = simulate_game(_inp(seed, **END_OF_REGULATION), profile=NCAAF_COT)
        by_q = {}
        for d in _ot_drives(out):
            by_q.setdefault(int(d["start_state"]["quarter"]), []).append(d["start_state"]["possession_owner"])
        if 6 in by_q:
            assert by_q[5][0] != by_q[6][0], seed
            return
    pytest.fail("no simulated game reached a second overtime period")


def test_a_touchdown_from_period_two_tries_for_two_and_period_one_keeps_the_kick():
    seen_q5_td = seen_q6_td = False
    for seed in range(1, 250):
        out = simulate_game(_inp(seed, **END_OF_REGULATION), profile=NCAAF_COT)
        for d in _ot_drives(out):
            q, pts = int(d["start_state"]["quarter"]), _points(d)
            if q == 5 and pts == 7:
                seen_q5_td = True
            if q >= 6:
                assert pts != 7, (seed, q, pts)
                seen_q6_td = seen_q6_td or pts in (6, 8)
    assert seen_q5_td and seen_q6_td


def test_overtime_ends_decided_and_period_three_on_moves_in_twos():
    reached_three = False
    for seed in range(1, 400):
        out = simulate_game(_inp(seed, **END_OF_REGULATION), profile=NCAAF_COT)
        assert out.final_score["home"] != out.final_score["away"], seed
        final_q = int(out.final_state["quarter"])
        if final_q >= 7:
            reached_three = True
            q6_end = [d for d in _ot_drives(out) if int(d["start_state"]["quarter"]) == 6][-1]["end_state"]
            # after both period-2 possessions the game was tied; from there only two-point attempts score
            gap_h = out.final_score["home"] - q6_end["score_home"]
            gap_a = out.final_score["away"] - q6_end["score_away"]
            assert gap_h % 2 == 0 and gap_a % 2 == 0, seed
    assert reached_three, "no simulated game reached a third overtime period"


def test_the_period_cap_stops_a_never_ending_shootout(monkeypatch):
    monkeypatch.setattr(gs, "COLLEGE_TWO_POINT_RATE", 0.0)  # nobody ever converts
    monkeypatch.setattr(gs, "COLLEGE_OVERTIME_PERIOD_CAP", 4)

    def scoreless_drive(state, simulation_input, *, rng, profile):  # noqa: ARG001
        from syndicate.features.football.sim_engine.smartsim2.contracts import DriveResult, PossessionOutcome

        return DriveResult(drive_index=0, possession_index=0, start_state=state, end_state=state,
                           outcome=PossessionOutcome.TURNOVER_ON_DOWNS)

    monkeypatch.setattr(gs, "simulate_drive", scoreless_drive)
    from random import Random

    from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state

    tied = build_initial_possession_state(home_team="H", away_team="A", quarter=4, clock_remaining=0,
                                          score_home=14, score_away=14)
    drives, steps = [], []
    end = gs._college_overtime(tied, _inp(1), rng=Random(1), profile=NCAAF_COT, drive_log=drives,
                               possession_log=steps)
    assert (end.score_home, end.score_away) == (14, 14)
    assert end.quarter == 4 + 4
    assert len(drives) == 4  # two possessions in each of periods 1 and 2, none after


def test_the_two_point_rate_is_the_measured_one():
    assert gs.COLLEGE_TWO_POINT_RATE == pytest.approx(0.451)
