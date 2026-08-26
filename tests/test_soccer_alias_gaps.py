"""Five soccer clubs the alias map could not place. `#576`.

FOUND BY A LOG LINE, NOT BY A PERSON. Every earlier batch in
`_SOCCER_VENDOR_NAME_ALIASES` was found by hand or by reading a join log after
someone noticed a broken board. `#541`'s `CHIP_JOIN_COVERAGE` named these on the
line it prints every build, with the exact spelling and the exact side:

    sport=soccer ... unknown_no_key=7 samples=[
      {'matchup': 'Ajax @ SC Telstar',        'away_key': None, ...},
      {'matchup': 'ADO Den Haag @ Feyenoord', 'home_key': None, ...},
      {'matchup': 'Charleroi @ KV Kortrijk',  'away_key': None, ...},
      {'matchup': 'Standard Liege @ Leuven',  'home_key': None, ...},
      {'matchup': 'SK Beveren @ Genk',        'home_key': None, ...}]

`away_key`/`home_key` IS `canonical_team`'s answer, so the None names the broken
side and the other side proves the fixture is otherwise fine.

Each is the club's SHORT name where the artifacts carry the long one.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.team_aliases import _soccer_alias_to_name, canonical_team

# (board spelling, artifact spelling) — the pair the map has to reconcile.
PAIRS = [
    ("Ajax", "Ajax Amsterdam"),
    ("Feyenoord", "Feyenoord Rotterdam"),
    ("Charleroi", "Royal Charleroi SC"),
    ("Leuven", "OH Leuven"),
    ("Genk", "Racing Genk"),
]


@pytest.mark.parametrize("board_name,artifact_name", PAIRS)
def test_both_spellings_land_on_one_name(board_name, artifact_name):
    """Asserted as a PAIR, not against a literal.

    The canonical string is the alias map's business and may change; what must
    never change is that the two feeds' spellings meet. A test pinning the
    literal would fail on a rename that broke nothing.
    """
    resolved = canonical_team("soccer", board_name)
    assert resolved is not None, f"{board_name} is unresolvable — the #576 defect"
    assert resolved == canonical_team("soccer", artifact_name)


@pytest.mark.parametrize("board_name,_artifact", PAIRS)
def test_each_token_is_unambiguous_across_every_league(board_name, _artifact):
    """The check `deportivo` documents, applied rather than assumed.

    A short club word is exactly the kind of key that should be SUSPECTED of
    colliding — `_soccer_alias_to_name` drops ambiguous DERIVED keys but cannot
    police a hand-written one. If a second club containing this token ever
    enters the configured set, the entry must go, and this fails to say so.
    """
    token = board_name.lower()
    canonical_names = set(_soccer_alias_to_name().values())
    matches = {name for name in canonical_names if token in name.lower()}
    assert len(matches) == 1, f"{token!r} now matches {sorted(matches)} — the alias is unsafe"


def test_the_clubs_that_already_resolved_still_do():
    """The other side of each sample fixture.

    These were never broken, and a careless edit to the map is exactly what
    would break them — so they are pinned alongside the fix rather than assumed
    to be out of scope.
    """
    for name in ("SC Telstar", "ADO Den Haag", "KV Kortrijk", "Standard Liege", "SK Beveren"):
        assert canonical_team("soccer", name) is not None, name


def test_an_unknown_club_still_refuses():
    """The map must not have become permissive."""
    assert canonical_team("soccer", "Definitely Not A Real Club") is None
