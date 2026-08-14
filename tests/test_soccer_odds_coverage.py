"""`#433` — soccer odds capture must not be queued behind ten simulations.

THE DEFECT, measured on production 2026-08-14. The soccer pregame run is 50
steps for 10 leagues, grouped BY KIND rather than by league, and the odds steps
sat at positions 21-30 — behind every league's `artifacts` sim. The run does not
reach the end, and the boundary was exact and reproducible in the quote shard:

    soccer_eredivisie_odds           step #27   captured 2026-08-14T13:16Z
    soccer_primeira_liga_odds        step #28   captured 2026-08-10T20:54Z
    soccer_championship_odds         step #29   captured 2026-08-11T00:54Z
    soccer_belgian_pro_league_odds   step #30   captured 2026-08-10T20:54Z

Three leagues went 3.6 days without an odds capture — including three of that
day's four fixtures — and steps 31-50 (props, picks) never ran for any league.

These tests pin the ORDER, not the contents. The bug was not a missing step or a
wrong command; every step was present and correct and simply ran too late to
matter. A test that asserts "the odds step exists" passes on the broken build.
"""

from __future__ import annotations

import argparse

import pytest

from scripts.refresh_odds_sources import _build_soccer_steps


def _args(date="2026-08-14", **extra):
    namespace = argparse.Namespace(
        date=date,
        soccer_leagues="",
        soccer_date="",
    )
    for key, value in extra.items():
        setattr(namespace, key, value)
    return namespace


def _names(steps):
    return [step.name for step in steps]


def _first_index(names, suffix):
    """Position of the first step of a given kind, or -1."""
    for index, name in enumerate(names):
        if name.endswith(suffix):
            return index
    return -1


@pytest.fixture()
def step_names():
    # `_build_soccer_steps` resolves its own repo/bundle roots and interpreter;
    # the date is the only input that changes the step set (via the per-league
    # season window), so it is the only thing worth injecting. An August date
    # is deliberate: all ten leagues are in season, which is the case the
    # truncation actually bit on.
    steps = _build_soccer_steps(_args())
    return _names(steps)


def test_every_odds_capture_precedes_every_simulation(step_names):
    """The whole fix, stated as one inequality.

    LAST odds step before FIRST sim step -- not "first before first", which the
    broken build could satisfy by interleaving. The point is that a run which
    dies partway loses sims, never captures.
    """
    last_odds = max(i for i, n in enumerate(step_names) if n.endswith("_odds"))
    first_artifacts = _first_index(step_names, "_artifacts")

    assert first_artifacts != -1, "no sim steps built; the fixture is wrong, not the code"
    assert last_odds < first_artifacts, (
        "an odds capture is queued behind a simulation. On production this cost "
        "three leagues 3.6 days of odds because the run died at step 27 of 50."
    )


def test_every_props_capture_precedes_every_simulation(step_names):
    """Props were at 31-40 and never ran at all. Same reasoning as odds."""
    last_props = max(i for i, n in enumerate(step_names) if n.endswith("_props"))
    first_artifacts = _first_index(step_names, "_artifacts")

    assert last_props < first_artifacts


def test_picks_still_run_after_both_the_sim_and_the_odds_it_grades(step_names):
    """The constraint the reorder must NOT break.

    `build_soccer_picks.py` grades simulated projections against captured odds
    and reads `game_odds_current.csv` directly, bailing when either input is
    missing. Hoisting picks with the other cheap-looking steps would produce an
    artifact graded against nothing.
    """
    first_picks = _first_index(step_names, "_picks")
    if first_picks == -1:
        pytest.skip("no picks steps in this configuration")

    last_artifacts = max(i for i, n in enumerate(step_names) if n.endswith("_artifacts"))
    last_odds = max(i for i, n in enumerate(step_names) if n.endswith("_odds"))

    assert first_picks > last_artifacts
    assert first_picks > last_odds


def test_the_league_set_is_unchanged_by_the_reorder(step_names):
    """A reorder that drops a league would look like a pass on the tests above.

    Both loops iterate the same `league_slugs`, so every league must still carry
    both an odds and a sim step. The three leagues this bug starved are named
    explicitly -- they are the ones a truncation hits first.
    """
    for league in ("primeira_liga", "championship", "belgian_pro_league", "eredivisie"):
        assert f"soccer_{league}_odds" in step_names
        assert f"soccer_{league}_artifacts" in step_names


def test_schedule_still_precedes_the_capture_it_scopes(step_names):
    """Schedules stayed first and must: the captures are scoped from fixtures."""
    last_schedule = max(i for i, n in enumerate(step_names) if n.endswith("_schedule"))
    first_odds = _first_index(step_names, "_odds")

    assert last_schedule < first_odds
