"""A drive that reaches the end zone must score. Default OFF, and that is deliberate.

THE DEFECT. `PlayOutcome.TOUCHDOWN` is SAMPLED from a weight distribution, and
it was the only way a drive could score six. An ordinary GAIN or EXPLOSIVE_GAIN
carried its full yardage regardless of how much field remained, while
`advance_field_position` clamps the yardline to [1, 100] -- so the ball pinned
itself ON the goal line and the drive kept running plays that gained yards going
nowhere, until the quarter expired.

Measured over 2,409 NCAAF drives before the fix:

    yards_gained > 100 (physically impossible)   6.60% of drives
    gained > 75 yards and scored NOTHING         3.82%
    longest single drive                       249 yards

WHY IT SHIPPED OFF, AND WHAT CHANGED. Both profiles were calibrated WITH the
defect present, so correcting the mechanism invalidated the estimators absorbing
it. That is now resolved PER PROFILE rather than by a global switch:

    ncaaf shipped off  15.00%      ncaaf re-fitted ON   7.24%   <- promoted
    nfl   shipped off   4.22%      nfl   re-fitted ON   4.18%   <- NOT promoted

NCAAF opts in through its calibration artifact. NFL measures BEST as it ships,
so it stays off and its profile is untouched.

THESE TESTS DRIVE THE DEFAULT PROFILE ON PURPOSE. They pin the ENV-OVERRIDE
path — off vs on — which is the shadow-run seam for a profile that has not
opted in. Using the live NCAAF profile here would make the "off" arm impossible,
because that profile now enables the mechanism itself; the test would pass
trivially and prove nothing. `test_football_calibration_artifacts.py` covers
the profile-gated path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2 import play_simulator
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE_DEFAULT as NCAAF_CALIBRATION_PROFILE,
)

FLAG = "SYNDICATE_FOOTBALL_GOAL_LINE_TOUCHDOWN"


def _drives(*, games: int = 40, seed0: int = 5100) -> list[dict]:
    out_drives: list[dict] = []
    for i in range(games):
        out = simulate_game(
            SmartSim2SimulationInput(
                home_team="A", away_team="B", seed=seed0 + i,
                home_offense_rating=0.0, home_defense_rating=0.0,
                away_offense_rating=0.0, away_defense_rating=0.0,
            ),
            profile=NCAAF_CALIBRATION_PROFILE,
        )
        out_drives.extend(out.drive_log or [])
    return out_drives


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    yield


@pytest.fixture()
def flag_off(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    yield


def test_flag_defaults_off(flag_off):
    """Absent must read as OFF, never as a permissive default."""
    assert play_simulator._goal_line_touchdown_enabled() is False


def test_flag_reads_truthy_values(flag_on):
    assert play_simulator._goal_line_touchdown_enabled() is True


def test_reachability_the_flag_actually_changes_the_simulation(flag_off, monkeypatch):
    """off != on. A flag that changes nothing is the failure this repo keeps hitting.

    Asserted on the DEFECT ITSELF (impossible drives) rather than on any
    aggregate, so a shift in unrelated calibration cannot make it pass.
    """
    impossible_off = sum(1 for d in _drives() if float(d.get("yards_gained") or 0) > 100)
    monkeypatch.setenv(FLAG, "true")
    impossible_on = sum(1 for d in _drives() if float(d.get("yards_gained") or 0) > 100)
    assert impossible_off > 0, (
        "the pre-fix defect should still be present with the flag OFF; if this is "
        "zero the flag is no longer gating anything and the test proves nothing"
    )
    assert impossible_on == 0


def test_with_the_flag_on_no_drive_exceeds_the_field(flag_on):
    """The physical invariant. A drive cannot gain more than 100 yards."""
    drives = _drives()
    assert drives, "no drives simulated"
    worst = max(float(d.get("yards_gained") or 0) for d in drives)
    assert worst <= 100, f"a drive gained {worst} yards; the field is 100 long"


def test_with_the_flag_on_long_drives_do_not_score_nothing(flag_on):
    """3.82% of drives gained >75 yards and scored ZERO before the fix."""
    drives = _drives()
    long_scoreless = [
        d for d in drives
        if float(d.get("yards_gained") or 0) > 75 and float(d.get("points_scored") or 0) == 0
    ]
    assert len(long_scoreless) / len(drives) < 0.01, (
        f"{len(long_scoreless)}/{len(drives)} drives travelled over 75 yards and scored "
        "nothing -- the goal line is not terminating drives"
    )


def test_the_touchdown_is_capped_to_the_remaining_field(flag_on):
    """A scoring play cannot be credited more yards than were left to gain.

    The SAMPLED touchdown path already did this (`max(1, 100 - yardline)`); the
    goal-line path must match it, or drive yardage inflates by exactly the
    amount this fix exists to remove.
    """
    for drive in _drives():
        if float(drive.get("points_scored") or 0) <= 0:
            continue
        for step in (drive.get("steps") or []):
            if not isinstance(step, dict):
                continue
            start = (step.get("start_state") or {})
            yardline = start.get("field_position") if isinstance(start, dict) else None
            gain = step.get("yards_gained")
            if yardline is None or not isinstance(gain, (int, float)):
                continue
            if str(step.get("outcome") or "").lower().endswith("touchdown"):
                assert gain <= max(1, 100 - float(yardline)) + 1e-6, (
                    f"touchdown credited {gain} yards from yardline {yardline}"
                )
