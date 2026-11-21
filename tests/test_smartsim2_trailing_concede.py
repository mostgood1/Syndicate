"""todo #859: the trailer concedes in regulation Q4 (`CalibrationProfile.trailing_concede_deficit`), lane
ncaaf-margin-aware-endgame. DEFAULT OFF.

REACHABILITY FIRST (`model_engine_standard.md`). OFF is byte-identical to the engine before this change: digests pinned
on the pre-change code (`.syndicate/findings_2026-11-20_ncaaf_margin_aware_endgame.md`). ON changes a blowout. Then the
rule itself, at the function the engine calls.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE,
    NFL_CALIBRATION_PROFILE_DEFAULT,
    CalibrationProfile,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE,
    NCAAF_CALIBRATION_PROFILE_DEFAULT,
)
from syndicate.features.football.sim_engine.smartsim2.play_state import build_play_state_from_possession_state
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state
from syndicate.features.football.sim_engine.smartsim2.situation_model import (
    URGENCY_END_GAME_PRESERVATION,
    URGENCY_NEUTRAL,
    URGENCY_TRAILING,
    URGENCY_TWO_MINUTE,
    classify_urgency,
)

NFL = NFL_CALIBRATION_PROFILE_DEFAULT
NCAAF = NCAAF_CALIBRATION_PROFILE_DEFAULT
EOH = dict(halftime_kickoff=True, q2_urgency_ignores_score=True, end_of_half_clock=True, end_of_half_kneel_out=True,
           end_of_half_clock_by_need=True, q4_kick_waits=True, kneel_out_q4_only=True)
TIED_LATE = dict(initial_quarter=4, initial_clock_seconds=20, initial_score_home=24, initial_score_away=24,
                 initial_possession_owner="home", initial_field_position=20)
# Home down 28 with 5:00 left and the ball: the state the rule exists for.
BLOWOUT_LATE = dict(initial_quarter=4, initial_clock_seconds=300, initial_score_home=7, initial_score_away=35,
                    initial_possession_owner="home", initial_field_position=30)

# sha256 over `simulate_game(...).to_dict()` (json, sort_keys), seeds 1..20, from the code BEFORE this change.
PINNED_OFF_DIGESTS = {
    "ncaaf_pregame": "2b2b1a67ebc85873c99b6113b5619a29c68954cb1a66762093bb744b50cb7c36",
    "ncaaf_tied_late": "2528c3745cb0746ab09750be5fc73f95acc324bd1c8e7829093731f7e90091f6",
    "ncaaf_blowout_late": "983ba4b359430816dcce20f3ac1cbd6ff2755531d20fcb0f3bf72f0f59f5169b",
    "ncaaf_808_blowout_late": "cc44720d82ecb79f727454bc29577db1fdc4ed8558f40a79b94326015f752237",
    "nfl_808_blowout_late": "ece4074758141959a632926e6404dc321d57ea18e2d65be4f9976383eb7deb74",
}


def _digest(profile: CalibrationProfile, **kw) -> str:
    h = hashlib.sha256()
    for seed in range(1, 21):
        inp = SmartSim2SimulationInput(home_team="H", away_team="A", seed=seed, home_offense_rating=0.1,
                                       away_defense_rating=-0.05, **kw)
        h.update(json.dumps(simulate_game(inp, profile=profile).to_dict(), sort_keys=True).encode())
    return h.hexdigest()


# --------------------------------------------------------------------------
# REACHABILITY
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,profile,kw", [
    ("ncaaf_pregame", NCAAF, {}),
    ("ncaaf_tied_late", NCAAF, TIED_LATE),
    ("ncaaf_blowout_late", NCAAF, BLOWOUT_LATE),
    ("ncaaf_808_blowout_late", replace(NCAAF, **EOH), BLOWOUT_LATE),
    ("nfl_808_blowout_late", replace(NFL, **EOH), BLOWOUT_LATE),
])
def test_REACHABILITY_off_is_byte_identical_to_the_pre_change_engine(name, profile, kw):
    assert profile.trailing_concede_deficit is None
    assert _digest(profile, **kw) == PINNED_OFF_DIGESTS[name]


@pytest.mark.parametrize("base", [NCAAF, replace(NCAAF, **EOH)])
def test_REACHABILITY_on_changes_a_blowout(base):
    off = _digest(base, **BLOWOUT_LATE)
    assert _digest(replace(base, trailing_concede_deficit=25), **BLOWOUT_LATE) != off


def test_on_leaves_a_one_score_game_alone_when_no_deficit_reaches_the_threshold():
    one_score = dict(BLOWOUT_LATE, initial_score_home=21, initial_score_away=24, initial_clock_seconds=60)
    prof = replace(NCAAF, **EOH)
    assert _digest(replace(prof, trailing_concede_deficit=25), **one_score) == _digest(prof, **one_score)


def test_the_switch_defaults_off_everywhere_and_rides_to_dict():
    for profile in (NFL, NCAAF, NFL_CALIBRATION_PROFILE, NCAAF_CALIBRATION_PROFILE, CalibrationProfile(name="x")):
        assert profile.trailing_concede_deficit is None
    assert CalibrationProfile(name="x").to_dict()["trailing_concede_deficit"] is None
    assert replace(NCAAF, trailing_concede_deficit=25).to_dict()["trailing_concede_deficit"] == 25


# --------------------------------------------------------------------------
# THE RULE, at the function the engine calls
# --------------------------------------------------------------------------

def _u(diff, quarter=4, seconds=300, concede=None):
    return classify_urgency(quarter=quarter, seconds_remaining=seconds, score_differential=diff, yardline=40,
                            concede_deficit=concede)


@pytest.mark.parametrize("diff,quarter,seconds,off,on", [
    (-30, 4, 300, URGENCY_TRAILING, URGENCY_NEUTRAL),      # hopeless deficit, 5:00 left: no hurry-up
    (-30, 4, 100, URGENCY_TWO_MINUTE, URGENCY_NEUTRAL),    # and no two-minute drill
    (-25, 4, 300, URGENCY_TRAILING, URGENCY_NEUTRAL),      # at the threshold
    (-24, 4, 300, URGENCY_TRAILING, URGENCY_TRAILING),     # under it: unchanged
    (-30, 2, 100, URGENCY_TWO_MINUTE, URGENCY_TWO_MINUTE),  # the first half is never touched
    (-30, 5, 100, URGENCY_TWO_MINUTE, URGENCY_TWO_MINUTE),  # nor overtime
    (30, 4, 100, URGENCY_END_GAME_PRESERVATION, URGENCY_END_GAME_PRESERVATION),  # nor the leader
])
def test_classify_urgency_concedes_only_a_q4_trailer_at_or_beyond_the_deficit(diff, quarter, seconds, off, on):
    assert _u(diff, quarter, seconds) == off
    assert _u(diff, quarter, seconds, concede=25) == on


def test_the_play_state_carries_the_rule_into_classify_situation():
    st = build_initial_possession_state(home_team="H", away_team="A", owner="home", quarter=4, clock_remaining=100,
                                        score_home=7, score_away=37, field_position=40)
    assert build_play_state_from_possession_state(st).two_minute_drill is True
    conceded = build_play_state_from_possession_state(st, trailing_concede_deficit=25)
    assert conceded.two_minute_drill is False
    assert conceded.urgency_state == URGENCY_NEUTRAL
    assert "trailing_concede_deficit" not in conceded.to_dict()  # a rule switch, not game state
