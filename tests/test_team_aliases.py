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


def test_soccer_map_is_derived_from_the_team_artifacts():
    """Supersedes `test_soccer_still_returns_no_map_deliberately`.

    That test pinned soccer at `{}` because a HAND-WRITTEN table across ~10
    leagues would be large and wrong at the edges. It is still hand-written
    tables that are rejected -- this map is DERIVED from the per-league team
    artifacts the repo already stores, so it is neither guessed nor typed out.
    """
    from syndicate.features.shared.team_aliases import _alias_map

    mapping = _alias_map("soccer")
    assert len(mapping) > 200, "expected the full multi-league club set"
    assert mapping.get("psv eindhoven") == "psv eindhoven"
    assert mapping.get("nec") == "nec nijmegen"


@pytest.mark.parametrize("odds_name,espn_token", [
    # Reduced by rule: diacritics and club-type designators.
    ("SC Telstar", "TEL"),
    ("Houston Dynamo", "Houston Dynamo FC"),
    ("Westerlo", "KVC Westerlo"),
    ("CS Maritimo", "Maritimo"),
    ("CF Estrela", "Estrela"),
    # Reached only by the measured vendor-name table.
    ("Sporting Lisbon", "Sporting CP"),
    ("Sint Truiden", "Sint-Truidense"),
    ("Union Saint-Gilloise", "Union St.-Gilloise"),
    ("Vitória SC", "Vitória de Guimaraes"),
])
def test_soccer_vendor_spellings_resolve(odds_name, espn_token):
    """Every club on production's 2026-08-08 board that did NOT resolve by
    exact name. Before this, `attach_game_state` matched 0 of 300 soccer rows;
    with these it matches all 300."""
    assert teams_match("soccer", odds_name, espn_token) is True


def test_soccer_tricodes_that_collide_across_leagues_resolve_to_nothing():
    """`STL` is Standard Liege in Belgium and St. Louis CITY SC in MLS, and the
    board joins per SPORT, not per league -- so first-wins would have joined a
    Belgian row to an MLS scoreboard. 11 keys collide on the real artifacts."""
    from syndicate.features.shared.team_aliases import canonical_team

    assert canonical_team("soccer", "STL") is None
    assert teams_match("soccer", "Standard Liege", "Standard Liege") is True


def test_nflverse_writes_the_rams_as_la():
    """nflverse -- the vocabulary `nfl_game_projections` keys its index on --
    spells the Rams `LA`, not `LAR`. Measured over the whole 2026 schedule
    (`data/nfl_source/schedule_2026.csv`): 32 distinct codes, `LA` present,
    `LAR` absent entirely.

    The gap was PREDICTED IN PLACE by `nfl_game_projections`'s own
    `_is_degenerate_rating_source` docstring -- "production carries exactly that
    case for two clubs (WSH, LAR) whose nflverse abbreviations do not resolve".
    WSH was fixed; this half was not. Measured on production's board grid
    2026-09-04: 78 of 1,252 rows carried no projection, and 17 of 17 distinct
    residual fixtures were Rams games.
    """
    assert teams_match("nfl", "los angeles rams", "la") is True
    assert teams_match("nfl", "la", "los angeles rams") is True
    assert canonical_team("nfl", "la") == "los angeles rams"


def test_la_does_not_also_claim_the_chargers():
    """The reason this alias is safe to add, and the reason it had to be added
    to the MAP rather than left to the heuristics.

    `LA` and `LAC` are the two codes nflverse uses for the two Los Angeles
    clubs, so `LA` is unambiguous WITHIN the sport -- and `teams_match` is
    sport-scoped, so the NBA/WNBA `LA` (Lakers/Clippers/Sparks) is unreachable
    from here.

    Without the map entry the INITIALS heuristic already matched `la` against
    "los angeles chargers" -- `"".join(w[0] for w in words[:2])` over
    ["los","angeles","chargers"] is exactly "la". So this entry REMOVES a
    live wrong-club match rather than risking one: with both sides resolvable
    the map is authoritative and `teams_match` returns before the heuristics
    (`team_aliases.py`, the "Both resolved" branch).
    """
    assert teams_match("nfl", "la", "los angeles chargers") is False
    assert teams_match("nfl", "los angeles chargers", "la") is False
    assert canonical_team("nfl", "lac") == "los angeles chargers"
    # The relocated-club history keys still point where they always did.
    assert canonical_team("nfl", "stl") == "los angeles rams"
    assert canonical_team("nfl", "sd") == "los angeles chargers"


def test_adding_la_leaves_the_derived_maps_untouched():
    """FORBIDDEN 2026-08-29(b): a map addition is not strictly additive -- it
    flips lookups from heuristic-fallback to map-authoritative, so the delta
    has to be enumerated rather than assumed.

    `_nickname_alias_map` and `unambiguous_club_tokens` both derive from the
    map's VALUES, and `la` adds a key whose value ("los angeles rams") was
    already present via `lar`/`stl`. So neither derived map moves. Enumerated
    exhaustively over the sport's whole vocabulary (71 tokens, 5,041 ordered
    pairs): exactly 6 `teams_match` verdicts change, every one of them a
    Rams/LA pair, and 0 map-resolvable pairs disagree with the map afterwards.
    """
    from syndicate.features.shared.team_aliases import (
        _nickname_alias_map,
        unambiguous_club_tokens,
    )

    assert len(_nickname_alias_map("nfl")) == 32
    assert len(unambiguous_club_tokens("nfl")) == 95
    # `la` must NOT become a bare-nickname key or an "unambiguous word".
    assert "la" not in _nickname_alias_map("nfl")
    assert "la" not in unambiguous_club_tokens("nfl")
