"""The drive-loop scoring rate dial -- NCAAF's total over-dispersion carrier.

`pick_gate` refuses NCAAF totals on two grounds, and this file is about the
first: "Model total SD 5.77 vs market 3.46 = 1.67x ... Carrier is the drive-loop
scoring rate (20.8 -> 53.9 percent against a real 35-45)."

`calibration_profile` had already recorded that the rating weights are NOT the
cause -- a five-row sweep where parity made totals WORSE (7.83 vs 7.51) -- and
pointed at `drive_priors`. `drive_success_probability` is that parameter: it is
directly proportional to `touchdown_probability` and carried at 0.08 in
`field_goal_probability`, so it IS the drive-loop scoring rate.

THESE TESTS DO NOT ASSERT A FITTED VALUE. The dial's setting must be fit against
a production-representative slate; nothing here claims to have done that.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from syndicate.features.football.sim_engine.smartsim2 import drive_priors as dp
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE as PROFILE,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import (
    SmartSim2SimulationInput,
)


def _priors(orat: float, drat: float, *, sensitivity: float | None = None):
    profile = PROFILE if sensitivity is None else replace(
        PROFILE, drive_success_sensitivity=sensitivity
    )
    source = SmartSim2SimulationInput(
        home_team="H", away_team="A", seed=1,
        home_offense_rating=orat, home_defense_rating=drat,
    )
    return dp.build_drive_priors(source, profile=profile).to_dict()


def _scoring_rate(priors) -> float:
    """What a drive is worth: the drive-loop scoring rate the gate measured."""
    return priors["touchdown_probability"] + priors["field_goal_probability"]


@pytest.mark.parametrize("orat,drat", [(-0.45, 0.45), (0.0, 0.0), (0.45, -0.45)])
def test_the_DEFAULT_is_an_exact_no_op(orat, drat):
    """`sensitivity == 1.0` is `anchor + 1.0*(raw - anchor) == raw` for ANY
    anchor, so introducing the dial cannot move NFL -- whose profile is the
    frozen Production Candidate -- by even one float."""
    assert _priors(orat, drat) == _priors(orat, drat, sensitivity=1.0)


def test_no_profile_at_all_is_also_the_no_op():
    """Every test caller and any un-migrated caller passes no profile. That path
    must be the old behaviour, not a new default."""
    source = SmartSim2SimulationInput(home_team="H", away_team="A", seed=1,
                                      home_offense_rating=0.3, home_defense_rating=-0.3)
    assert dp.build_drive_priors(source).to_dict() == dp.build_drive_priors(
        source, profile=replace(PROFILE, drive_success_sensitivity=1.0)
    ).to_dict()


def test_the_dial_compresses_the_scoring_rate_MONOTONICALLY():
    """The whole point: lower sensitivity, narrower spread. Measured at default,
    the drive-loop scoring rate spans ~15pp across the rating range; the gate
    says football spans ~10."""
    spreads = []
    for sensitivity in (1.0, 0.6, 0.4, 0.3):
        weak = _scoring_rate(_priors(-0.45, 0.45, sensitivity=sensitivity))
        strong = _scoring_rate(_priors(0.45, -0.45, sensitivity=sensitivity))
        spreads.append(strong - weak)
    assert spreads == sorted(spreads, reverse=True), spreads
    assert spreads[0] > spreads[-1] * 2, "the dial must have real authority"


def test_it_is_THE_CARRIER_the_gate_named():
    """`pick_gate` records the rate bottoming at 20.8%. `drive_success_probability`
    bottoms at 0.214 here on the rating path -- the same parameter, not a
    coincidence of two numbers that happen to be small."""
    weak = _priors(-0.45, 0.45)["drive_success_probability"]
    assert weak == pytest.approx(0.208, abs=0.02)


def test_compressing_does_NOT_move_the_level_much():
    """Dispersion is the defect; the MEAN total was already right (51.56 vs
    53.02). A dial that fixed the spread by moving the level would trade a
    measured-good property for a measured-bad one."""
    even_default = _scoring_rate(_priors(0.0, 0.0))
    even_shrunk = _scoring_rate(_priors(0.0, 0.0, sensitivity=0.4))
    assert abs(even_shrunk - even_default) < 0.05
