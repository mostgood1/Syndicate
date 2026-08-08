"""#218 -- resolving a team token to a club, across the vocabularies each
surface uses.

Every case here is a real code from a real board row. The one that mattered:
"chc" is neither a prefix of "chicago" (chi != chc) nor the initials of
"chicago cubs" (cc), so a pure string heuristic rejects it -- which is why
0 of 108 board candidates carried a quote in production on 2026-08-06.
"""

from __future__ import annotations

import unittest

import pytest

from syndicate.features.shared.team_aliases import canonical_team, teams_match


class TeamAliasTests(unittest.TestCase):
    def test_the_code_that_no_heuristic_reaches(self) -> None:
        self.assertTrue(teams_match("mlb", "chc", "Chicago Cubs"))

    def test_it_does_not_match_the_other_club_in_the_same_city(self) -> None:
        """The reason the map is authoritative rather than advisory: a prefix
        rule would happily match "chc" to the White Sox via "chicago"."""
        self.assertFalse(teams_match("mlb", "chc", "Chicago White Sox"))
        self.assertTrue(teams_match("mlb", "cws", "Chicago White Sox"))

    def test_new_york_clubs_stay_distinct(self) -> None:
        self.assertTrue(teams_match("mlb", "nyy", "New York Yankees"))
        self.assertFalse(teams_match("mlb", "nyy", "New York Mets"))
        self.assertTrue(teams_match("mlb", "nym", "New York Mets"))

    def test_codes_built_from_the_city_alone(self) -> None:
        """"kc"/"tb"/"sf" are the initials of the CITY words, not of the full
        club name ("kcc"/"tbr"/"sfg"), and are too short for a prefix rule."""
        self.assertTrue(teams_match("nfl", "kc", "Kansas City Chiefs"))
        self.assertTrue(teams_match("nfl", "gb", "Green Bay Packers"))
        self.assertTrue(teams_match("nfl", "ne", "New England Patriots"))
        self.assertTrue(teams_match("mlb", "tb", "Tampa Bay Rays"))
        self.assertTrue(teams_match("mlb", "sf", "San Francisco Giants"))

    def test_a_sport_with_no_map_still_joins_on_heuristics(self) -> None:
        """A partial join beats none; the map is the mechanism, not a gate."""
        self.assertTrue(teams_match("soccer", "ars", "Arsenal"))
        self.assertTrue(teams_match("ncaaf", "alabama", "Alabama"))

    def test_wnba_is_not_shadowed_by_nba_sharing_tri_codes(self) -> None:
        """The two leagues share MIN/ATL/PHX/LA. A merged alias map resolves
        wnba "min" to the Timberwolves and then reports a MISMATCH against the
        Lynx -- a wrong answer, and worse than no answer, because a resolved
        map skips the heuristic fallback."""
        self.assertTrue(teams_match("wnba", "min", "Minnesota Lynx"))
        self.assertFalse(teams_match("wnba", "min", "Las Vegas Aces"))
        self.assertTrue(teams_match("nba", "min", "Minnesota Timberwolves"))

    def test_full_names_resolve_from_either_direction(self) -> None:
        self.assertTrue(teams_match("mlb", "Chicago Cubs", "Chicago Cubs"))
        self.assertEqual(canonical_team("mlb", "chc"), "chicago cubs")
        self.assertEqual(canonical_team("mlb", "Chicago Cubs"), "chicago cubs")

    def test_unknown_tokens_resolve_to_nothing_rather_than_guessing(self) -> None:
        self.assertIsNone(canonical_team("mlb", "zzz"))
        self.assertIsNone(canonical_team("mlb", ""))
        self.assertFalse(teams_match("mlb", "", "Chicago Cubs"))
        self.assertFalse(teams_match("mlb", "chc", ""))

    def test_an_unimportable_sport_module_degrades_rather_than_raising(self) -> None:
        """This runs on the board read path."""
        self.assertFalse(teams_match("not-a-sport", "xyz", "Some Club"))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# NFL and the WNBA gaps. MEASURED 2026-08-08.
# ---------------------------------------------------------------------------
#
# `_alias_map` handled mlb/nba/wnba only, so NFL fell through to the heuristics
# and `teams_match("nfl", "Carolina Panthers", "CAR")` was False. Consequence:
# `attach_game_state` matched 0 rows, every NFL board row carried
# `game.state = None`, and `opportunity_gate`'s dead-market rule silently could
# not apply -- a SETTLED NFL market could rank. It is also the hard blocker on
# the S2 cadence tiers, which key on game state.


@pytest.mark.parametrize("abbr,name", [
    ("CAR", "Carolina Panthers"), ("ARI", "Arizona Cardinals"),
    ("GB", "Green Bay Packers"), ("SF", "San Francisco 49ers"),
    ("KC", "Kansas City Chiefs"), ("NE", "New England Patriots"),
])
def test_nfl_tricodes_resolve(abbr, name):
    assert teams_match("nfl", name, abbr) is True


@pytest.mark.parametrize("abbr,name", [
    ("WSH", "Washington Commanders"),   # ESPN
    ("JAC", "Jacksonville Jaguars"),    # ESPN
    ("LVR", "Las Vegas Raiders"),
    ("OAK", "Las Vegas Raiders"),       # nflverse historical
    ("SD", "Los Angeles Chargers"),
])
def test_nfl_feed_alternates_resolve(abbr, name):
    """Real feeds disagree on codes; a map that only knows one spelling joins
    on some days and not others."""
    assert teams_match("nfl", name, abbr) is True


@pytest.mark.parametrize("abbr,name", [
    ("CAR", "Arizona Cardinals"), ("NYG", "New York Jets"), ("LAC", "Los Angeles Rams"),
])
def test_nfl_does_not_match_the_wrong_club(abbr, name):
    """Same-city and same-initial pairs are where a heuristic would guess."""
    assert teams_match("nfl", name, abbr) is False


@pytest.mark.parametrize("abbr,name", [("MIN", "Minnesota Lynx"), ("POR", "Portland Fire")])
def test_wnba_supplement_fills_the_vendored_gaps(abbr, name):
    """The vendored map resolved SEA and LVA but not these, and the 2026-08-08
    slate carried a POR chip -- a live gap, not a theoretical one."""
    assert teams_match("wnba", name, abbr) is True


def test_the_vendored_wnba_map_still_wins_where_it_answers():
    assert teams_match("wnba", "Seattle Storm", "SEA") is True
    assert teams_match("wnba", "Las Vegas Aces", "LVA") is True


@pytest.mark.parametrize("sport,abbr,name", [
    ("nfl", "MIN", "Minnesota Lynx"),
    ("wnba", "MIN", "Minnesota Vikings"),
])
def test_tricodes_do_not_resolve_ACROSS_leagues(sport, abbr, name):
    """The trap the basketball map is already documented against: leagues share
    tri-codes, and a cross-league match is worse than no match because the map
    is authoritative and skips the heuristic fallback."""
    assert teams_match(sport, name, abbr) is False


def test_soccer_still_returns_no_map_deliberately():
    """~10 leagues with no stable tri-code convention across feeds. A guessed
    table would be large and wrong at the edges; it needs its own pass against
    the real chip abbreviations. Pinned so its absence stays a decision."""
    from syndicate.features.shared.team_aliases import _alias_map

    assert _alias_map("soccer") == {}
