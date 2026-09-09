"""A bare club nickname must resolve, and an ambiguous one must not.

`venue_quote_adapters._polymarket_sides` predicted this gap in place: "the day
it sends nicknames instead, this counter is the difference between a visible
alias-map gap and a feed that quietly halves." Measured on production
2026-08-27, polymarket_us offered 2,048 NFL quotes and reported
`clubs_unresolved:64:['49ers','Bears','Bengals','Bills','Broncos','Browns']`.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.team_aliases import _alias_map, canonical_team


# The six production actually named, verbatim from the log.
PRODUCTION_UNRESOLVED = ["49ers", "Bears", "Bengals", "Bills", "Broncos", "Browns"]


@pytest.mark.parametrize("nickname", PRODUCTION_UNRESOLVED)
def test_the_nicknames_production_could_not_resolve_now_resolve(nickname):
    """THE OFF/ON TEST. Every one of these returned None before."""
    resolved = canonical_team("nfl", nickname)

    assert resolved is not None, f"{nickname} still unresolvable"
    assert resolved in set(_alias_map("nfl").values())


def test_every_nfl_club_is_reachable_by_its_bare_nickname():
    """Not a sample -- the whole league, so a partial map cannot pass."""
    clubs = set(_alias_map("nfl").values())
    assert len(clubs) == 32

    for club in clubs:
        nickname = club.split()[-1]
        assert canonical_team("nfl", nickname) == club, f"{nickname} did not resolve to {club}"


def test_exact_and_tricode_forms_still_win():
    """The fallback is LAST. Nothing that resolved before may change."""
    assert canonical_team("nfl", "Seattle Seahawks") == "seattle seahawks"
    assert canonical_team("nfl", "SEA") == "seattle seahawks"
    assert canonical_team("nfl", "New York Giants") == "new york giants"
    assert canonical_team("nfl", "NYG") == "new york giants"


def test_an_ambiguous_nickname_is_refused_not_preferred():
    """"Sox" names both Chicago and Boston. Guessing is a bet on the wrong club
    half the time, at a price that looks confident."""
    assert canonical_team("mlb", "Sox") is None
    assert canonical_team("mlb", "sox") is None


def test_the_same_nickname_resolves_per_sport():
    """The map is sport-scoped, so "Giants" is not ambiguous -- it is two
    different clubs in two different leagues, and each is unambiguous there."""
    assert canonical_team("mlb", "Giants") == "san francisco giants"
    assert canonical_team("nfl", "Giants") == "new york giants"


def test_an_unknown_token_is_still_none():
    assert canonical_team("nfl", "Notaclub") is None
    assert canonical_team("nfl", "") is None
    assert canonical_team("nfl", None) is None


def test_wnba_gains_nothing_because_its_supplement_already_covers_it():
    """Documents that this is additive-where-needed, not a second source of
    truth competing with the vendored map."""
    assert canonical_team("wnba", "Sky") == "chicago sky"


def test_a_sport_with_no_alias_map_is_unaffected():
    """nhl and ncaab are the exemplars now. NCAAF used to be one and gained a
    map on 2026-09-09; it is asserted separately below, because the derivation
    this file tests is DECLINED for that sport rather than merely empty."""
    assert canonical_team("nhl", "Bruins") is None
    assert canonical_team("ncaab", "Blue Devils") is None
    assert canonical_team("", "Bears") is None


def test_ncaaf_declines_this_derivation_even_though_it_now_has_a_map():
    """`_nickname_alias_map`'s premise is "<City> <Nickname>", where the last
    word IS the nickname. CFBD's canonical names are SCHOOLS, so the last word
    is a qualifier and the derivation yields `southern` -> Georgia Southern,
    `green` -> Bowling Green, `a&m` -> Texas A&M -- unique only because the map
    is FBS-only and Southern University and Florida A&M are hidden by that.

    Registry-independent: the branch returns `{}` before it reads anything, so
    this asserts the same thing with or without `data/`.
    """
    from syndicate.features.shared import team_aliases as ta

    assert ta._nickname_alias_map("ncaaf") == {}
    assert canonical_team("ncaaf", "Southern") is None
    assert canonical_team("ncaaf", "A&M") is None
