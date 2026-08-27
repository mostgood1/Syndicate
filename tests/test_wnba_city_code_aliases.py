"""WNBA clubs must resolve by their standard city code.

MEASURED IN PRODUCTION 2026-08-27T19:33Z, from the Polymarket join's own
unmatched sample:

    board:   'Washington Mystics @ Phoenix Mercury'   want 'h2h|home'
    offered: ['gsv-ny@None', 'wsh-phx@None']          -> refused `no_match`

The venue was plainly offering that fixture. `wsh` resolved; `phx` did not.

THE CAUSE IS SYSTEMATIC. `_basketball_alias_to_name` merges NBA and WNBA and
drops any key naming two clubs, so EVERY city fielding both teams loses its
three-letter code. `min` (Lynx vs Timberwolves) was already supplemented for
this exact reason in 2026-08-08; `phx`, `atl`, `chi`, `dal` and `ind` were the
remainder of the same rule, not separate accidents.

THE ISOLATION TEST IS THE IMPORTANT ONE. A supplement that leaked into the NBA
map would silently turn every `phx` NBA row into the Mercury -- a wrong team on
a real bet. `_alias_map` applies the supplement only for `wnba`, and
`test_the_nba_map_is_untouched` fails if that ever stops being true.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.team_aliases import canonical_team, teams_match


CITY_CODES = {
    "phx": ("phoenix mercury", "phoenix suns"),
    "atl": ("atlanta dream", "atlanta hawks"),
    "chi": ("chicago sky", "chicago bulls"),
    "dal": ("dallas wings", "dallas mavericks"),
    "ind": ("indiana fever", "indiana pacers"),
    "min": ("minnesota lynx", "minnesota timberwolves"),
}


@pytest.mark.parametrize("code,expected", [(c, v[0]) for c, v in CITY_CODES.items()])
def test_the_wnba_club_resolves_from_its_city_code(code, expected):
    assert canonical_team("wnba", code) == expected


@pytest.mark.parametrize("code,expected", [(c, v[1]) for c, v in CITY_CODES.items()])
def test_the_nba_map_is_untouched(code, expected):
    """The supplement must never leak across sports.

    A leak here is not a missed match -- it is a bet on the wrong club.
    """
    assert canonical_team("nba", code) == expected


def test_the_reported_production_fixture_now_matches():
    """`wsh-phx` -> Washington Mystics @ Phoenix Mercury."""
    assert teams_match("wnba", "wsh", "Washington Mystics")
    assert teams_match("wnba", "phx", "Phoenix Mercury")


def test_the_vendored_map_still_wins_where_it_answers():
    """Supplement fills gaps; it does not override.

    `_alias_map` merges as `dict(SUPPLEMENT)` then `.update(mapping)`, so a
    future vendor fix silently takes precedence instead of being shadowed.
    """
    assert canonical_team("wnba", "sea") == "seattle storm"
    assert canonical_team("wnba", "lva") == "las vegas aces"


def test_an_unknown_code_still_refuses():
    """Absent must stay absent -- the supplement is not a guess generator."""
    assert canonical_team("wnba", "zzz") is None
