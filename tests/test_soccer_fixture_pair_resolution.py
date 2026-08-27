"""A soccer fixture resolves as a PAIR when neither club resolves alone.

MEASURED 2026-08-27, after the competition fold made Polymarket's soccer markets
reachable: 119 h2h rows still refused as `no_match`. `team_aliases` drops club
tokens that name two clubs ACROSS leagues -- `fcb` is Bayern and Barcelona,
`stl` is Standard Liege and St. Louis CITY SC. That drop is correct and stays: a
confidently wrong club is a real bet on the wrong team.

Asked as a PAIR the ambiguity mostly disappears, because only one league holds
both clubs of a real fixture. On 295 sampled venue fixtures the global map
resolved 50 and the pair resolved 93 -- 43 rescued.

WHAT THIS DOES NOT FIX, and the tests say so rather than leaving it implied:
Polymarket's tri-codes are a DIFFERENT VOCABULARY from ESPN's abbreviations --
Bayern is `MUN` in our artifacts and `fcb` at the venue. Those codes are ABSENT,
not ambiguous, and no amount of pair logic invents them.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import team_aliases as TA
from syndicate.features.shared.polymarket_board_join import _teams_match


BY_LEAGUE = {
    # `fcb` means different clubs in the two leagues -- the collision the global
    # map drops entirely.
    "bundesliga": {"fcb": "bayern munich", "stu": "vfb stuttgart", "koe": "fc cologne"},
    "la_liga": {"fcb": "barcelona", "rma": "real madrid", "cel": "celta vigo"},
    "mls": {"stl": "st louis city sc"},
    "belgian_pro_league": {"stl": "standard liege", "and": "anderlecht"},
}


@pytest.fixture
def leagues(monkeypatch):
    monkeypatch.setattr(TA, "_soccer_alias_by_league", lambda: BY_LEAGUE)
    return BY_LEAGUE


def test_a_cross_league_collision_resolves_as_a_pair(leagues):
    """`fcb` alone is hopeless; `fcb` + `stu` is only the Bundesliga."""
    assert TA.soccer_fixture_clubs("fcb", "stu") == ("bayern munich", "vfb stuttgart")


def test_the_same_token_resolves_differently_in_its_own_league(leagues):
    assert TA.soccer_fixture_clubs("fcb", "cel") == ("barcelona", "celta vigo")


def test_a_pair_explained_by_NO_league_refuses(leagues):
    assert TA.soccer_fixture_clubs("fcb", "and") is None


def test_a_lone_ambiguous_token_still_refuses(leagues):
    """`stl` is Standard Liege AND St. Louis -- the measured `#stl` trap.

    Neither league contains a second club that would complete the fixture, so
    the pair cannot rescue it either. That is the correct outcome: this path is
    stricter than the global map, never a way around it.
    """
    assert TA.soccer_fixture_clubs("stl", "stl") is None
    assert TA.soccer_fixture_clubs("stl", "rma") is None


def test_a_club_playing_itself_refuses(leagues):
    assert TA.soccer_fixture_clubs("cel", "cel") is None


def test_empty_codes_refuse(leagues):
    assert TA.soccer_fixture_clubs(None, "stu") is None
    assert TA.soccer_fixture_clubs("", "") is None


# ---------------------------------------------------------------------------
# The join itself
# ---------------------------------------------------------------------------


@pytest.fixture
def joined(monkeypatch, leagues):
    """Global map knows nothing; only the pair path can answer."""
    monkeypatch.setattr(TA, "_soccer_alias_by_league", lambda: BY_LEAGUE)
    monkeypatch.setattr(
        "syndicate.features.shared.team_aliases.teams_match",
        lambda sport, a, b: False,
        raising=False,
    )

    def canonical(sport, value):
        table = {"bayern munich": "bayern munich", "vfb stuttgart": "vfb stuttgart"}
        return table.get(str(value or "").strip().lower())

    monkeypatch.setattr(
        "syndicate.features.shared.team_aliases.canonical_team", canonical, raising=False
    )


def test_the_join_matches_a_fixture_the_global_map_cannot(joined):
    row = {"home": "Bayern Munich", "away": "VfB Stuttgart"}
    assert _teams_match(row, {"home": "fcb", "away": "stu"}, "soccer") is True


def test_the_join_refuses_when_the_sides_are_swapped(joined):
    """Home/away order is part of the identity, not a detail.

    Matching a swapped fixture would pair our row with the opposite side of the
    same game -- the failure `_side_to_kalshi` refuses for the same reason.
    """
    row = {"home": "VfB Stuttgart", "away": "Bayern Munich"}
    assert _teams_match(row, {"home": "fcb", "away": "stu"}, "soccer") is False


def test_the_fallback_is_soccer_only(joined):
    """MLB tri-codes collide with soccer clubs -- `min`, `ath`, `sd`.

    A measured production loss came from an MLB market indexed as soccer. This
    path must never be reachable for another sport.
    """
    row = {"home": "Bayern Munich", "away": "VfB Stuttgart"}
    assert _teams_match(row, {"home": "fcb", "away": "stu"}, "mlb") is False
