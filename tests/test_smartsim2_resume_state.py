"""smartsim2 can be resumed from mid-game, and resuming costs the pregame path nothing.

The second half is the one that matters. `simulate_game` is the entrypoint for
NCAAF's weekly projections and both NFL generators; if adding the resume fields
moved a single simulated point, the whole live path would be paid for out of the
pregame board's accuracy.
"""
from __future__ import annotations

import pytest

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE,
)

TEAMS = dict(
    home_team="Oregon",
    away_team="Boise State",
    home_offense_rating=12.0,
    home_defense_rating=-6.0,
    away_offense_rating=1.0,
    away_defense_rating=1.0,
)


def _run(seed, **overrides):
    return simulate_game(
        SmartSim2SimulationInput(seed=seed, **TEAMS, **overrides),
        profile=NCAAF_CALIBRATION_PROFILE,
    )


def _home_win_rate(seeds, **overrides):
    wins = 0
    for seed in seeds:
        out = _run(seed, **overrides)
        if out.final_score["home"] > out.final_score["away"]:
            wins += 1
    return wins / len(seeds)


SEEDS = range(1, 41)


def test_the_defaults_are_the_values_that_used_to_be_hard_coded():
    """A caller that does not ask to resume gets the identical simulation.

    Pinned field by field rather than only through output equality: if someone
    later "tidies" `initial_clock_seconds` to a literal 900, output equality
    would still hold at the default `quarter_seconds` and silently break the
    moment anyone simulates a shorter quarter.
    """
    default = SmartSim2SimulationInput(home_team="A", away_team="B")
    assert default.initial_quarter == 1
    assert default.initial_clock_seconds is None
    assert default.initial_score_home == 0
    assert default.initial_score_away == 0


def test_pregame_output_is_unchanged_by_the_resume_fields():
    """Default input == input resumed explicitly at kickoff, seed for seed.

    This is the no-regression gate. It compares the two code paths inside the
    SAME process, so it cannot be fooled by a calibration profile that differs
    between checkouts -- which is exactly what made a first attempt at this
    comparison, run across two working trees, report a false difference.
    """
    for seed in SEEDS:
        plain = _run(seed)
        explicit = _run(
            seed,
            initial_quarter=1,
            initial_clock_seconds=900,
            initial_score_home=0,
            initial_score_away=0,
        )
        assert plain.final_score == explicit.final_score, f"seed {seed}"
        assert plain.total == explicit.total, f"seed {seed}"
        assert plain.spread == explicit.spread, f"seed {seed}"
        assert len(plain.drive_log) == len(explicit.drive_log), f"seed {seed}"
        assert len(plain.possession_log) == len(explicit.possession_log), f"seed {seed}"


def test_resuming_at_kickoff_is_the_pregame_simulation_not_an_approximation_of_it():
    """The whole design rests on this: the live model IS the pregame model."""
    assert _home_win_rate(SEEDS) == _home_win_rate(
        SEEDS, initial_quarter=1, initial_clock_seconds=900
    )


def test_off_differs_from_on_a_decided_game_is_certain():
    """Reachability before correctness: the resume fields must actually bind.

    A 21-point lead with 15 seconds left is not a probabilistic question, so an
    engine that ignored `initial_score_*` would answer with the pregame rate and
    this would fail. Both directions, so a constant 1.0 cannot pass it.
    """
    ahead = _home_win_rate(SEEDS, initial_quarter=4, initial_clock_seconds=15,
                           initial_score_home=35, initial_score_away=14)
    behind = _home_win_rate(SEEDS, initial_quarter=4, initial_clock_seconds=15,
                            initial_score_home=14, initial_score_away=35)
    assert ahead == 1.0
    assert behind == 0.0
    assert ahead != _home_win_rate(SEEDS)


def test_a_carried_score_is_never_lost():
    """Points already on the board cannot be simulated away."""
    for seed in list(SEEDS)[:10]:
        out = _run(seed, initial_quarter=3, initial_clock_seconds=600,
                   initial_score_home=17, initial_score_away=10)
        assert out.final_score["home"] >= 17
        assert out.final_score["away"] >= 10


def test_resuming_later_simulates_less_football():
    """Fewer drives remain from Q4 than from Q1. Guards a silently ignored clock."""
    early = sum(len(_run(s, initial_quarter=1).drive_log) for s in list(SEEDS)[:10])
    late = sum(
        len(_run(s, initial_quarter=4, initial_clock_seconds=300).drive_log)
        for s in list(SEEDS)[:10]
    )
    assert late < early


@pytest.mark.parametrize("period", [5, 6])
def test_a_resume_past_regulation_still_simulates_rather_than_declaring_a_winner(period):
    """The bug the overtime move-out exists to prevent.

    With the OT block inside the quarter loop, `range(5, 5)` is empty, nothing
    runs, and a tied game comes back as a confident 0.5 with an empty drive log
    -- a published probability derived from zero simulations. The producer
    refuses overtime for its own reasons; the engine must not answer badly if
    something else ever asks.
    """
    out = _run(7, initial_quarter=period, initial_clock_seconds=900,
               initial_score_home=21, initial_score_away=21)
    assert len(out.drive_log) > 0
    assert out.final_score["home"] != out.final_score["away"] or len(out.drive_log) >= 2
