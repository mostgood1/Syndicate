"""#218 -- resolving a team token to a club, across the vocabularies each
surface uses.

Every case here is a real code from a real board row. The one that mattered:
"chc" is neither a prefix of "chicago" (chi != chc) nor the initials of
"chicago cubs" (cc), so a pure string heuristic rejects it -- which is why
0 of 108 board candidates carried a quote in production on 2026-08-06.
"""

from __future__ import annotations

import unittest

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
