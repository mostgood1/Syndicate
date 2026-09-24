"""The daily scorecard's sport list is decided by the calendar, not by memory.

Lane `daily-accuracy-suite` `[2026-09-20]`.

WHAT THIS REPLACED. `DEFAULT_SPORTS` was a hand-maintained tuple whose comment read
"NBA and NCAAB are off-season ... Add them back when their seasons open." The exclusion
was a real cost decision -- each out-of-season sport spends a not-found read per board
date -- but its enforcement was somebody remembering in late October.

THE SAFETY PROPERTY THAT MATTERS MOST is the first test: on the day this shipped, the
calendar-derived list is EXACTLY the tuple it replaced. So the change is inert on the
day it lands and can only differ once the calendar moves, which is the only kind of
change worth making to a job that is currently working.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.publish_model_scorecard import (
    ALL_SPORTS,
    DEFAULT_SPORTS,
    SEASON_WINDOWS,
    in_season,
    sports_in_season,
)


def test_on_the_day_this_shipped_the_derived_list_equals_the_hand_maintained_one():
    """Inertness on landing day. If this fails, the change is not the no-op it claims."""
    assert set(sports_in_season(date(2026, 9, 20))) == set(DEFAULT_SPORTS)


def test_nba_and_ncaab_turn_themselves_on_in_november():
    """The thing nobody would have remembered to do."""
    november = sports_in_season(date(2026, 11, 15))
    assert "nba" in november
    assert "ncaab" in november


def test_and_the_summer_sports_turn_themselves_off():
    november = sports_in_season(date(2026, 11, 15))
    assert "wnba" not in november
    assert "mlb" not in november


def test_midsummer_is_the_narrow_slate_not_an_empty_one():
    """A bug that returned nothing would look like a quiet success. Pin the real answer."""
    assert set(sports_in_season(date(2026, 7, 4))) == {"mlb", "wnba"}


def test_windows_that_wrap_the_new_year_are_handled():
    """NFL runs September to mid-February. A naive `start <= now <= end` reads January as
    out of season and would drop the NFL from the accuracy job mid-playoffs."""
    assert in_season("nfl", date(2027, 1, 10)) is True
    assert in_season("ncaaf", date(2027, 1, 10)) is True
    assert in_season("nfl", date(2026, 5, 10)) is False


def test_a_non_wrapping_window_still_excludes_its_off_season():
    assert in_season("wnba", date(2026, 7, 1)) is True
    assert in_season("wnba", date(2026, 12, 1)) is False


def test_an_unknown_sport_is_never_silently_dropped():
    """Unknown must not default to the restrictive branch: a new sport the platform starts
    trading would otherwise vanish from the accuracy job with no reason emitted."""
    assert in_season("kabaddi", date(2026, 9, 20)) is True


def test_every_sport_is_in_season_on_at_least_one_day_and_off_on_another():
    """A window that never opens, or never closes, is a typo that the tests above could
    easily miss -- `wnba: ((5,1),(4,30))` would read as in-season all year."""
    days = [date(2026, month, 15) for month in range(1, 13)]
    for sport in ALL_SPORTS:
        readings = {in_season(sport, day) for day in days}
        assert readings == {True, False}, f"{sport} is never both in and out of season"


@pytest.mark.parametrize("sport", sorted(SEASON_WINDOWS))
def test_every_window_is_a_well_formed_pair_of_month_day_tuples(sport):
    (start_month, start_day), (end_month, end_day) = SEASON_WINDOWS[sport]
    assert 1 <= start_month <= 12 and 1 <= end_month <= 12
    assert 1 <= start_day <= 31 and 1 <= end_day <= 31


def test_the_sport_list_is_sorted_and_deduplicated():
    assert list(ALL_SPORTS) == sorted(set(ALL_SPORTS))


def test_the_settler_registry_and_the_season_table_agree_on_which_sports_exist():
    """A sport in the read list that no settler handles reads zero forever; a sport with a
    settler and no window never gets read. Both are silent, so pin the relationship.

    NCAAB WAS the one deliberate exception -- read (so it appeared with zero rows rather
    than vanishing) but not graded, for want of a team registry -- and this test said "when
    that changes, this test is what says so". **It said so on 2026-09-23** (lane
    `nhl-ncaab-club-maps`): the registry landed, `canonical_team("ncaab", ...)` resolves,
    and ncaab joined both `HANDLED_SPORTS` and `SETTLER_MODULES`.

    So the exception is gone and the relationship is now exact in BOTH directions. That is
    a stronger assertion than the one it replaces, and it is kept as a set comparison
    rather than a subset check for the same reason the original named its exception: a
    loose assertion here hides both silent failures this test exists to catch -- a sport
    read but never graded (zero forever) and a sport graded but never read.
    """
    from syndicate.features.shared import population_outcomes as po

    graded = set(po.build_extra_settler().sport_versions)
    read = set(ALL_SPORTS)
    assert graded - read == set(), f"settler handles sports nothing reads: {graded - read}"
    assert read - graded == set(), f"unexpected ungraded sports in the read list: {read - graded}"
    assert "ncaab" in graded and "ncaab" in read
