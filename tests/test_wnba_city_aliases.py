"""Portland and Toronto, by CITY, without stealing NBA's tri-codes.

MEASURED 2026-08-25T01:22:04Z, the first live run of the unresolved-club
counter added the same evening:

  wnba polymarket_us reason="spreads_refused:40
                             clubs_unresolved:2:['Portland', 'Toronto']"

Polymarket names WNBA clubs by city. `_WNBA_TEAM_ALIASES_LOCAL` carried the two
newest franchises by NICKNAME only (`fire`, `tempo`) while every other club also
carried its city -- so those two resolved to nothing and their h2h quotes were
dropped by name.

THE COLLISION THIS AVOIDS is the reason the fix is an overlay rather than four
lines in that map. `basketball_props_smart_sim` also exposes
`_TEAM_ALIASES_LOCAL = {**NBA, **WNBA}` where WNBA wins, and NBA holds
`por` -> Portland Trail Blazers / `tor` -> Toronto Raptors. Four entries in the
shared dict would have silently reassigned two NBA clubs in the merged map that
module itself reads.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.team_aliases import canonical_team, teams_match


@pytest.mark.parametrize(
    "token,expected",
    [
        ("Portland", "portland fire"),
        ("portland", "portland fire"),
        ("POR", "portland fire"),
        ("por", "portland fire"),
        ("Toronto", "toronto tempo"),
        ("TOR", "toronto tempo"),
    ],
)
def test_the_wnba_clubs_the_counter_NAMED_now_resolve(token, expected):
    assert canonical_team("wnba", token) == expected


@pytest.mark.parametrize("token,expected", [("Fire", "portland fire"), ("Tempo", "toronto tempo")])
def test_the_nicknames_that_already_worked_still_work(token, expected):
    """Additive. The overlay must not displace what the base map already had."""
    assert canonical_team("wnba", token) == expected


@pytest.mark.parametrize(
    "token,expected",
    [
        ("por", "portland trail blazers"),
        ("tor", "toronto raptors"),
        ("Portland Trail Blazers", "portland trail blazers"),
        ("Toronto Raptors", "toronto raptors"),
    ],
)
def test_NBA_is_untouched_by_the_wnba_overlay(token, expected):
    """The whole reason this is an overlay and not four map entries."""
    assert canonical_team("nba", token) == expected


def test_the_MERGED_map_still_gives_those_tricodes_to_the_NBA_clubs():
    """Read the merged dict directly. This is the object that would have been
    corrupted, and it is read by `basketball_props_smart_sim` itself -- so
    asserting on `canonical_team` alone would not have caught the damage."""
    import syndicate.features.shared.basketball_props_smart_sim as smart_sim

    assert smart_sim._TEAM_ALIASES_LOCAL["por"] == "Portland Trail Blazers"
    assert smart_sim._TEAM_ALIASES_LOCAL["tor"] == "Toronto Raptors"


def test_the_overlay_is_not_in_the_shared_map_at_all():
    """States the mechanism, so a future edit that 'simplifies' this by moving
    the entries into the shared dict fails here rather than in production."""
    import syndicate.features.shared.basketball_props_smart_sim as smart_sim

    for key in ("portland", "toronto"):
        assert key not in smart_sim._WNBA_TEAM_ALIASES_LOCAL, (
            f"{key!r} belongs in team_aliases._WNBA_EXTRA_ALIASES, not in the "
            "shared map -- see the collision note there"
        )


def test_a_venue_token_matches_the_board_team_both_directions():
    """What the join actually does: the venue says 'Portland', the board row
    says 'Portland Fire'."""
    assert teams_match("wnba", "Portland", "Portland Fire")
    assert teams_match("wnba", "Portland Fire", "Portland")
    assert teams_match("wnba", "Toronto", "Toronto Tempo")


def test_canonical_team_is_SPORT_SCOPED_and_does_not_cross_leagues():
    """The property the join actually depends on.

    Both the Polymarket adapter and the fan-in resolve through
    `canonical_team`, so this -- not `teams_match` -- is what decides whether a
    WNBA quote can ever be keyed to an NBA club.
    """
    assert canonical_team("wnba", "Portland") == "portland fire"
    assert canonical_team("nba", "Portland Trail Blazers") == "portland trail blazers"
    assert canonical_team("nba", "Portland Fire") is None
    assert canonical_team("wnba", "Portland Trail Blazers") is None


def test_the_word_overlap_HEURISTIC_still_crosses_cities_and_that_PREDATES_this():
    """RECORDED, NOT FIXED, and explicitly not claimed as this change's doing.

    `teams_match("wnba", "Portland", "Portland Trail Blazers")` is True. It was
    True BEFORE the overlay existed too -- verified by clearing
    `_WNBA_EXTRA_ALIASES` and the lru_cache and re-running: still True, with
    `canonical_team("wnba", "Portland")` returning None at the time. The cause
    is `teams_match`'s word-overlap fallback matching the shared city token
    once the map cannot answer, and the overlay does not reach that path.

    It does not affect the Polymarket join, which goes through
    `canonical_team` (asserted above). Pinned here so the behaviour is a known
    quantity rather than a surprise, and so a future fix to the heuristic has a
    test that names it.
    """
    assert teams_match("wnba", "Portland", "Portland Trail Blazers") is True
