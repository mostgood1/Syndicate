"""The WRITER must not be able to produce a league-constant artifact.

`98950c6d` made the reader immune to a degenerate projections file. It did not
stop the file being written -- and writing it OVERWRITES the healthy copy, so
the reader's immunity is worth nothing once the good artifact is gone. That is
the sequence that put `margin 0.96 / total 44.38 / home_win 0.5267` on all 16
preseason games across four dates on 2026-08-13.

Two guards at two stages, tested separately because they catch the same outage
at different costs:

  assert_ratings_data_available      before the sim -- names the missing input
  assert_projections_carry_information  before the write -- protects the file

THE FALSIFICATION CASES MATTER MORE THAN THE POSITIVE ONES here. A guard that
fires too eagerly blanks a mostly-good board, which is worse than the failure
being fixed, so the tests that must pass are the ones where it stays silent:
a partial degenerate run, and an empty schedule.
"""

from __future__ import annotations

import pytest

from scripts.generate_smartsim2_nfl_projections import (
    DegenerateProjectionRun,
    assert_projections_carry_information,
    assert_ratings_data_available,
)


PREFIX = "nflverse_pbp_epa_prior_season_shrunk"
DEGENERATE = f"{PREFIX}[neutral_no_data/neutral_no_data]"
HEALTHY = f"{PREFIX}[prior_season_fallback/prior_season_fallback]"
HALF = f"{PREFIX}[neutral_no_data/prior_season_fallback]"

PLAY = (1, "KC", "DEN", "pass", 0.2)


class _Projection:
    """Only the attribute the guard reads. Both real dataclasses carry it."""

    def __init__(self, rating_source: str) -> None:
        self.rating_source = rating_source


# --------------------------------------------------------------------------
# precondition: no play-by-play at all
# --------------------------------------------------------------------------


def test_no_plays_at_all_raises_before_any_simulation():
    with pytest.raises(DegenerateProjectionRun) as exc:
        assert_ratings_data_available(season=2026, current_plays=[], prior_plays=[])
    message = str(exc.value)
    # The message has to name the CAUSE, not just the symptom -- the failure is
    # almost always root resolution, and "no data" sends people looking for a
    # download that is not missing.
    assert "gitignored" in message
    assert "pbp_2026.csv" in message and "pbp_2025.csv" in message
    assert "DATA_ROOT" in message


def test_prior_season_alone_is_enough():
    """Preseason has no current season by definition -- the prior season is
    the only source, and a run with it is not an outage."""
    assert_ratings_data_available(season=2026, current_plays=[], prior_plays=[PLAY])


def test_current_season_alone_is_enough():
    assert_ratings_data_available(season=2026, current_plays=[PLAY], prior_plays=[])


def test_prior_plays_none_is_handled():
    assert_ratings_data_available(season=2026, current_plays=[PLAY], prior_plays=None)
    with pytest.raises(DegenerateProjectionRun):
        assert_ratings_data_available(season=2026, current_plays=[], prior_plays=None)


# --------------------------------------------------------------------------
# pre-write: would this file be worthless?
# --------------------------------------------------------------------------


def test_all_degenerate_refuses_to_write():
    projections = [_Projection(DEGENERATE) for _ in range(16)]
    with pytest.raises(DegenerateProjectionRun) as exc:
        assert_projections_carry_information(projections, season=2026, week=2)
    message = str(exc.value)
    assert "16/16" in message
    # Must state that nothing was lost, or an operator seeing this at 3am
    # cannot tell whether the good artifact survived.
    assert "previous artifact is intact" in message


def test_a_single_healthy_projection_is_enough_to_write():
    """THE CASE THAT MUST NOT FIRE. A partial degenerate run still carries real
    information for its other games, and the deployed reader already drops the
    bad rows. Refusing here would blank a mostly-good board."""
    projections = [_Projection(DEGENERATE) for _ in range(15)] + [_Projection(HEALTHY)]
    assert_projections_carry_information(projections, season=2026, week=2)


def test_half_neutral_rows_do_not_count_as_degenerate():
    """Production carries exactly this whenever a club's abbreviation does not
    resolve -- one real rating still differentiates the matchup."""
    projections = [_Projection(HALF) for _ in range(16)]
    assert_projections_carry_information(projections, season=2026, week=2)


def test_empty_projection_list_is_allowed_through():
    """No games is a DIFFERENT condition from no data. Conflating them would
    make an out-of-season run look like a broken pipeline."""
    assert_projections_carry_information([], season=2026, week=2)


def test_unparseable_rating_source_does_not_trigger_a_refusal():
    """Unknown must not default to the destructive branch: a formatting change
    in rating_source must not start blocking every write."""
    projections = [_Projection("") for _ in range(4)]
    assert_projections_carry_information(projections, season=2026, week=2)


def test_all_healthy_writes():
    assert_projections_carry_information([_Projection(HEALTHY) for _ in range(16)], season=2026, week=2)


# --------------------------------------------------------------------------
# the two generators must both be wired to it
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.generate_smartsim2_nfl_projections",
        "scripts.generate_smartsim2_nfl_preseason_projections",
    ],
)
def test_both_generators_import_both_guards(module_name):
    """Presence is not reachability -- but absence IS unreachability, and this
    catches the cheap half: a generator that never imported the guard cannot
    be protected by it."""
    import importlib

    module = importlib.import_module(module_name)
    assert hasattr(module, "assert_ratings_data_available")
    assert hasattr(module, "assert_projections_carry_information")


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.generate_smartsim2_nfl_projections",
        "scripts.generate_smartsim2_nfl_preseason_projections",
    ],
)
def test_guards_are_called_before_the_write_in_source_order(module_name):
    """The pre-write guard is only useful BEFORE the write call. Asserting the
    order in source is crude, but it fails loudly if someone moves the write
    above it -- which would restore the exact bug this lane closed."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module_name).main)
    guard_at = source.index("assert_projections_carry_information")
    write_at = source.index("write_pre") if "write_pre" in source else source.index("write_projection_artifact")
    assert guard_at < write_at, "the guard must precede the artifact write"
