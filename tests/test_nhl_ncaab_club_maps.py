"""The nhl and ncaab club maps, and the invariants that keep them safe.

`_alias_map` used to return `{}` for both sports, so `club_key` fell through to
raw text and `same_club` relied on `teams_match`'s heuristics. Adding a map is
NOT strictly additive -- `teams_match` returns the map's verdict when both
sides resolve and does not fall back -- so these tests pin the safety property
(nothing ambiguous becomes a key) as hard as they pin the feature.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import team_aliases
from syndicate.features.shared.ncaab_team_registry import iter_team_alias_offers, registry_rows
from syndicate.features.shared.settlement_identity import club_key, same_club, _sport_has_club_map
from syndicate.features.shared.team_aliases import normalize, teams_match


# --------------------------------------------------------------------------
# NHL
# --------------------------------------------------------------------------

# Every one of these was measured FALSE on 2026-09-23 with no map, against the
# spellings the real feeds emit. `Montreal` carries the e-acute deliberately:
# it is the form TheOddsAPI's own event listing returns.
NHL_SAME_CLUB = [
    ("Ottawa Senators", "OTT"),
    ("Montreal Canadiens", "Montréal Canadiens"),
    ("Los Angeles Kings", "LA"),
    ("Utah Mammoth", "Utah Hockey Club"),
    ("New Jersey Devils", "NJ"),
    ("San Jose Sharks", "SJ"),
    ("Tampa Bay Lightning", "TB"),
    ("Toronto Maple Leafs", "TOR"),
]

# The heuristics answered TRUE for this pair -- a confident wrong answer, not a
# miss. Colorado is COL, Columbus is CBJ.
NHL_DIFFERENT_CLUB = [
    ("Colorado Avalanche", "Columbus Blue Jackets"),
    ("New York Islanders", "New York Rangers"),
    ("Los Angeles Kings", "Anaheim Ducks"),
]


def test_nhl_has_a_club_map():
    assert _sport_has_club_map("nhl") is True
    mapping = team_aliases._alias_map("nhl")
    assert mapping, "an empty nhl map means local_nhl_odds stopped exporting TEAM_NAME_TO_ABBR"
    # 32 current clubs plus Arizona, which the source still lists separately.
    assert len(set(mapping.values())) == 33


@pytest.mark.parametrize("left,right", NHL_SAME_CLUB)
def test_nhl_variants_resolve_to_one_club(left, right):
    assert same_club("nhl", left, right) is True
    assert club_key("nhl", left) == club_key("nhl", right)


@pytest.mark.parametrize("left,right", NHL_DIFFERENT_CLUB)
def test_nhl_distinct_clubs_stay_distinct(left, right):
    assert same_club("nhl", left, right) is False


def test_nhl_map_is_reachable_off_differs_from_on():
    """Reachability before correctness: prove the map is what changed.

    Without this, every assertion above could be satisfied by a heuristic and
    the map could be inert -- the failure mode `model_engine_standard.md`
    requires an `off != on` test for.
    """
    real = team_aliases._alias_map
    team_aliases._alias_map = lambda sport: ({} if normalize(sport) == "nhl" else real(sport))
    try:
        without = teams_match("nhl", "Ottawa Senators", "OTT")
    finally:
        team_aliases._alias_map = real
    assert without is False
    assert teams_match("nhl", "Ottawa Senators", "OTT") is True


def test_nhl_canonical_is_the_first_name_the_source_lists():
    """Canonical is a fact about the source's ORDER, not a choice made here."""
    from syndicate.local_nhl_odds import TEAM_NAME_TO_ABBR

    first_by_abbr: dict[str, str] = {}
    for name, abbr in TEAM_NAME_TO_ABBR.items():
        first_by_abbr.setdefault(str(abbr).upper(), normalize(name))
    assert first_by_abbr["UTA"] == "utah mammoth"  # not "utah hockey club"
    assert first_by_abbr["STL"] == "st. louis blues"
    assert club_key("nhl", "Utah Hockey Club") == "utah mammoth"
    assert club_key("nhl", "UTA") == "utah mammoth"


def test_nhl_arizona_and_utah_are_not_silently_merged():
    """The source lists two tri-codes; merging them is a relocation claim this
    map's source does not make. A miss here is correct; a merge would rewrite
    historical Arizona rows."""
    assert same_club("nhl", "Arizona Coyotes", "Utah Mammoth") is False


def test_nhl_map_has_no_ambiguous_key():
    mapping = team_aliases._alias_map("nhl")
    assert "new york" not in mapping, "a bare place claimed by NYI and NYR must not be a key"
    assert len(mapping) == len(set(mapping)), "dict keys are unique by construction; guard against a rewrite"


# --------------------------------------------------------------------------
# NCAAB
# --------------------------------------------------------------------------

# Measured on the committed registry: each is the last word of many schools'
# mascot column, so each must have been dropped by the collision pass.
NCAAB_AMBIGUOUS = ["bulldogs", "tigers", "wildcats", "eagles", "panthers", "bears", "cougars", "lions"]


def test_ncaab_registry_is_present_and_populated():
    """An empty registry means the CSV was deleted or truncated -- a DIFFERENT
    fact from 'this sport has no map', and one nothing else would report."""
    rows = registry_rows()
    assert len(rows) > 300, f"registry looks truncated: {len(rows)} rows"
    assert {"school", "display_name", "abbreviation", "mascot"} <= set(rows[0])


def test_ncaab_has_a_club_map():
    assert _sport_has_club_map("ncaab") is True
    mapping = team_aliases._alias_map("ncaab")
    assert len(mapping) > 1000
    assert len(set(mapping.values())) == len(registry_rows())


@pytest.mark.parametrize("token", NCAAB_AMBIGUOUS)
def test_ncaab_shared_mascots_are_not_keys(token):
    """The whole safety argument. A key two schools claim would become a
    confident wrong answer, because `teams_match` does not fall through."""
    assert token not in team_aliases._alias_map("ncaab")
    assert club_key("ncaab", token) is None


def test_ncaab_no_ambiguous_offer_leaks_into_the_map():
    owners: dict[str, set[str]] = {}
    for token, school in iter_team_alias_offers():
        key = normalize(token)
        if key:
            owners.setdefault(key, set()).add(normalize(school))
    ambiguous = {k for k, v in owners.items() if len(v) > 1}
    mapping = team_aliases._alias_map("ncaab")
    assert ambiguous, "expected college mascots to collide; a zero here means the offers changed shape"
    assert not (ambiguous & set(mapping)), sorted(ambiguous & set(mapping))[:10]


@pytest.mark.parametrize("left,right", [
    ("Duke Blue Devils", "Duke"),
    # Spellings copied from the registry's own columns, not recalled: the
    # display name is "Arizona State Sun Devils" and the short form is
    # "Arizona St". Writing the latter as the former is the same alias mistake
    # this whole map exists to stop, and it failed here first.
    ("Arizona State Sun Devils", "ASU"),
    ("Arizona St", "Arizona State"),
    ("Akron Zips", "Zips"),
    ("Purdue Boilermakers", "Boilermakers"),
    ("Abilene Christian Wildcats", "Abilene Christian"),
])
def test_ncaab_unique_tokens_resolve(left, right):
    assert same_club("ncaab", left, right) is True


@pytest.mark.parametrize("left,right", [
    ("Arizona", "Arizona St"),          # heuristics answered True -- a wrong answer
    ("Arizona", "N Arizona"),           # likewise
    ("North Alabama Lions", "South Alabama Jaguars"),
])
def test_ncaab_similar_schools_stay_distinct(left, right):
    assert same_club("ncaab", left, right) is False


def test_ncaab_nickname_derivation_declines():
    """Canonical values are SCHOOLS, so the last word is a qualifier:
    'Abilene Christian' -> `christian`, 'Air Force' -> `force`. Deriving
    nicknames from them manufactures wrong keys, exactly as for NCAAF."""
    assert team_aliases._nickname_alias_map("ncaab") == {}


def test_ncaab_map_is_reachable_off_differs_from_on():
    real = team_aliases._alias_map
    team_aliases._alias_map = lambda sport: ({} if normalize(sport) == "ncaab" else real(sport))
    try:
        without = teams_match("ncaab", "Arizona", "Arizona St")
    finally:
        team_aliases._alias_map = real
    assert without is True, "the heuristic false positive this map removes"
    assert teams_match("ncaab", "Arizona", "Arizona St") is False


# --------------------------------------------------------------------------
# Cross-sport: the other sports' maps must be untouched
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sport,expected", [
    ("mlb", True), ("nfl", True), ("nba", True), ("wnba", True),
    ("ncaaf", True), ("soccer", True), ("nhl", True), ("ncaab", True),
])
def test_every_configured_sport_reports_its_map_state(sport, expected):
    assert _sport_has_club_map(sport) is expected


def test_an_unknown_sport_still_has_no_map():
    assert _sport_has_club_map("curling") is False
    assert team_aliases._alias_map("curling") == {}
