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


def test_a_swapped_soccer_fixture_is_the_SAME_GAME_and_still_matches(joined):
    """`_teams_match` answers "same GAME"; SIDE is decided downstream by NAME.

    THIS ASSERTION WAS INVERTED, 2026-09-03. It used to require `False` here,
    on the reasoning that "matching a swapped fixture would pair our row with
    the opposite side of the same game". That contract changed when the soccer
    PAIR resolver landed (2026-08-27/29), and the change is deliberate:
    `_teams_match` compares `board_pair == slug_pair` as SETS and returns
    immediately, with the comment "a wrong-GAME check must not be entangled
    with a wrong-SIDE one". The venue's slug order is not a reliable home/away
    signal, so requiring it here refused real fixtures -- that fallback exists
    because 119 h2h rows were being dropped, and it rescued 43 of 93.

    WHY THIS IS NOT A WRONG-SIDE BET, traced rather than assumed:
    `_probability_for_side` (polymarket_board_join.py:2988) is what turns a
    matched market into a price, and it resolves team outcomes THROUGH
    `team_aliases` by name, never positionally. Its own docstring: "None is the
    important return ... assigning a side positionally is a bet on the wrong
    team half the time, at a price that looks confident." It also re-verifies
    the subject rather than trusting the candidate filter, so a caller that
    skipped the check cannot obtain a confident price. A swapped match yields a
    row whose side must still be NAMED, or refused.

    THE CONTRACT IS SPLIT BY SPORT, which is the part worth pinning:
    `_teams_match` ends (line 2985) with a genuinely ordered check --
    `pair[0] == board_home and pair[1] == board_away` -- but for any soccer
    fixture the pair resolver can name, the unordered return fires first and
    that line is unreachable. So ORDER IS ENFORCED FOR OTHER SPORTS AND NOT FOR
    SOCCER, which the function's name and its "Both clubs, or no match"
    docstring do not convey. `test_the_fallback_is_soccer_only` below pins the
    other half.
    """
    row = {"home": "VfB Stuttgart", "away": "Bayern Munich"}
    assert _teams_match(row, {"home": "fcb", "away": "stu"}, "soccer") is True


def test_the_ordered_check_still_governs_a_NON_soccer_swap(joined):
    """The other half of the split contract, so the asymmetry is pinned on
    BOTH sides rather than only where it was discovered.

    A non-soccer sport never reaches the pair resolver at all (see
    `test_the_fallback_is_soccer_only`), so a swap there stays unmatched --
    for that reason rather than because of an order check, and either way the
    behaviour a caller depends on is the same.
    """
    row = {"home": "VfB Stuttgart", "away": "Bayern Munich"}
    assert _teams_match(row, {"home": "fcb", "away": "stu"}, "mlb") is False


def test_the_fallback_is_soccer_only(joined):
    """MLB tri-codes collide with soccer clubs -- `min`, `ath`, `sd`.

    A measured production loss came from an MLB market indexed as soccer. This
    path must never be reachable for another sport.
    """
    row = {"home": "Bayern Munich", "away": "VfB Stuttgart"}
    assert _teams_match(row, {"home": "fcb", "away": "stu"}, "mlb") is False
