"""`#369` -- the sim horizon could not see past the current matchweek.

MEASURED against the real schedules, reference 2026-08-11, horizon 7:

    unit-dates enumerated    8
    fixture dates in window 20

`_soccer_refresh_units` resolved ONE week per league via `default_week` and then
filtered that week's dates with `week_dates_within_horizon`. So a 7-day horizon
could never reach a fixture belonging to the FOLLOWING matchweek, however close.
Twelve fixture-dates had no unit created for them and therefore could not be
simulated at all -- not a scheduling delay, an enumeration gap.

It showed on the board precisely where the arithmetic predicts:

    la_liga        3 units / 3 dates    21/33 game rows projected
    mls            1 unit  / 3 dates    18/86
    championship   1 unit  / 4 dates     3/43
    belgian        1 unit  / 3 dates     5/43
    primeira_liga  1 unit  / 4 dates     0/27

la_liga looked healthy only because its matchweek happened to span its entire
in-horizon slate -- the bug was invisible in the one league anyone would check.

Capacity, since more units means more jobs. Production sets
`SYNDICATE_SOCCER_LEAGUE_LAUNCH_SPACING_SECONDS=300`, so 20 units is a 100-minute
full pass against a 240-minute refresh interval: 140 minutes of headroom. Without
that override the spacing self-scales to `interval // unit_count`, which keeps a
full pass at exactly one interval no matter how many units there are.
"""

from __future__ import annotations

import datetime

import pytest


@pytest.fixture()
def worker(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    monkeypatch.setenv("SYNDICATE_SOCCER_SIM_HORIZON_DAYS", "7")
    spec = importlib.util.spec_from_file_location(
        "rw_horizon", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rw_horizon"] = module
    spec.loader.exec_module(module)
    return module


def _schedule(dates):
    return {"matches": [{"date": f"{d}T19:00Z", "week": 1} for d in dates]}


def test_every_in_horizon_fixture_date_becomes_a_unit(worker, monkeypatch):
    dates = ["2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17"]
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.schedule_payload",
        lambda league, season: _schedule(dates),
        raising=False,
    )
    got = worker._soccer_schedule_dates_in_horizon("championship", 2026, "2026-08-11", 7)
    assert got == dates, "a fixture in the NEXT matchweek must still get a unit"


def test_fixtures_outside_the_horizon_are_excluded(worker, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.schedule_payload",
        lambda league, season: _schedule(["2026-08-12", "2026-08-25", "2026-09-01"]),
        raising=False,
    )
    got = worker._soccer_schedule_dates_in_horizon("epl", 2026, "2026-08-11", 7)
    assert got == ["2026-08-12"]


def test_past_fixtures_are_excluded(worker, monkeypatch):
    # Yesterday's match is not work to schedule.
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.schedule_payload",
        lambda league, season: _schedule(["2026-08-09", "2026-08-10", "2026-08-13"]),
        raising=False,
    )
    got = worker._soccer_schedule_dates_in_horizon("mls", 2026, "2026-08-11", 7)
    assert got == ["2026-08-13"]


def test_an_unreadable_schedule_yields_nothing_and_lets_the_caller_fall_back(worker, monkeypatch):
    # `_soccer_refresh_units` falls back to the week-scoped view on an empty
    # result, so a broken schedule degrades to the OLD behaviour rather than to
    # zero units -- which would silently stop every soccer sim.
    def boom(league, season):
        raise OSError("artifact unreadable")

    monkeypatch.setattr("syndicate.features.soccer.sources.schedule_payload", boom, raising=False)
    assert worker._soccer_schedule_dates_in_horizon("serie_a", 2026, "2026-08-11", 7) == []
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.schedule_payload", lambda l, s: {}, raising=False
    )
    assert worker._soccer_schedule_dates_in_horizon("serie_a", 2026, "2026-08-11", 7) == []


def test_malformed_dates_are_skipped_not_fatal(worker, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.schedule_payload",
        lambda league, season: {"matches": [
            {"date": "not-a-date"}, {"date": None}, {}, "junk",
            {"date": "2026-08-13T19:00Z"},
        ]},
        raising=False,
    )
    assert worker._soccer_schedule_dates_in_horizon("ligue_1", 2026, "2026-08-11", 7) == ["2026-08-13"]


def test_a_full_pass_still_fits_inside_the_refresh_interval(worker, monkeypatch):
    # More units means more jobs; the pass must not outrun the interval it is
    # meant to complete within.
    monkeypatch.setenv("SYNDICATE_SOCCER_LEAGUE_LAUNCH_SPACING_SECONDS", "300")
    spacing = worker._soccer_unit_launch_spacing_seconds(20)
    assert 20 * spacing < 14400, "20 units at production spacing must fit inside the 4h interval"


def test_without_the_override_spacing_self_scales(worker, monkeypatch):
    # The self-scaling rule keeps a full pass at exactly one interval regardless
    # of how many units the horizon produces.
    monkeypatch.delenv("SYNDICATE_SOCCER_LEAGUE_LAUNCH_SPACING_SECONDS", raising=False)
    for count in (8, 20, 50):
        spacing = worker._soccer_unit_launch_spacing_seconds(count)
        assert count * spacing <= 14400 + count, f"{count} units overruns the interval"
