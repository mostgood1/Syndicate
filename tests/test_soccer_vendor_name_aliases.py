"""`#374` -- five clubs the odds feed spells differently from the team artifacts.

Found while chasing why belgian_pro_league sat at 5/43 after its unit demonstrably
WROTE. The sim was fine; the join was not.

THE CLEANEST PROOF OF THE CLASS is `SK Beveren`. On 2026-08-16, three of four
belgian fixtures projected and one did not -- same league, same date, same sim
file, same everything except that the club was renamed from Waasland-Beveren in
2022 and the artifacts still carry the old name. Nothing else can explain a
single fixture failing among its own siblings.

NOT A SWEEP. 23 board clubs are missing from the derived alias map and most join
anyway, because the projection index also matches on the normalised name
directly. Only a club the SIM SPELLS DIFFERENTLY actually costs a fixture, so
each entry here is tied to an observed 0-projection fixture where the sim held
the match under its own name.

TWO CANDIDATES WERE REJECTED, and they matter as much as the five kept:
`Real Salt Lake`/`Austin FC` (0.17) and `Los Angeles FC`/`Chicago Fire FC` (0.41)
came from a substring heuristic that matched on the token "FC". They are
different fixtures entirely. A similarity score is a filter for candidates, not
the decision -- which cuts both ways: `New York Red Bulls`/`Red Bull New York`
scores 0.46, below those rejects, and is kept because MLS has exactly one such
club and the identity is not in doubt.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.team_aliases import _soccer_alias_to_name, teams_match


@pytest.fixture(autouse=True)
def _fresh_alias_map():
    # The map is lru_cached and built from artifacts; a stale cache would make
    # these assertions describe a map the process built before the edit.
    _soccer_alias_to_name.cache_clear()
    yield
    _soccer_alias_to_name.cache_clear()


@pytest.mark.parametrize(
    "board_name,sim_name",
    [
        ("SK Beveren", "Waasland-Beveren"),
        ("FC Twente Enschede", "FC Twente"),
        ("FC Zwolle", "PEC Zwolle"),
        ("Real Racing Club de Santander", "Racing Santander"),
        ("New York Red Bulls", "Red Bull New York"),
    ],
)
def test_the_odds_feed_name_joins_to_the_sim_name(board_name, sim_name):
    assert teams_match("soccer", board_name, sim_name)


@pytest.mark.parametrize(
    "left,right",
    [
        # The two the heuristic got wrong -- different fixtures sharing "FC".
        ("Real Salt Lake", "Austin FC"),
        ("Los Angeles FC", "Chicago Fire FC"),
        # Same fixture, opposing clubs: must never collapse into each other.
        ("SK Beveren", "Anderlecht"),
        # Two Dutch clubs whose new aliases both mention a city-less stem.
        ("FC Zwolle", "FC Twente"),
        ("Racing Santander", "Real Madrid"),
    ],
)
def test_the_new_aliases_create_no_false_matches(left, right):
    assert not teams_match("soccer", left, right)


def test_every_alias_target_resolves_in_the_derived_map():
    """An entry whose target does not resolve is SILENTLY DROPPED.

    `_soccer_alias_to_name` only applies an override when the espn-side name is
    already in the map (`if canonical:`). A typo on the right-hand side
    therefore fails closed and invisibly -- the alias simply never exists, and
    the fixture keeps rendering blank with no error anywhere.
    """
    from syndicate.features.shared.team_aliases import (
        _SOCCER_VENDOR_NAME_ALIASES,
        fold_accents,
        normalize,
    )

    mapping = _soccer_alias_to_name()
    unresolved = [
        f"{vendor} -> {espn}"
        for vendor, espn in _SOCCER_VENDOR_NAME_ALIASES.items()
        if not (mapping.get(normalize(espn)) or mapping.get(fold_accents(espn)))
    ]
    assert not unresolved, f"alias targets that resolve to nothing: {unresolved}"


def test_the_existing_aliases_still_work():
    # Regression guard on the four that predate `#374`.
    assert teams_match("soccer", "Sint Truiden", "Sint-Truidense")
    assert teams_match("soccer", "Sporting Lisbon", "Sporting CP")
