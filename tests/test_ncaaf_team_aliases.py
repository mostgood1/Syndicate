"""NCAAF gains a `_alias_map` branch -- and this file is the gate that keeps it
honest, because the same change was REVERTED once already.

`.syndicate/handoff_2026-08-29_ncaaf_umass_alias_gap.md` and the FORBIDDEN entry
in `learnings_evidence.md` record the 2026-08-29 attempt: it was backed out
because a populated map makes `teams_match` MAP-AUTHORITATIVE (it returns the
map's equality verdict and does NOT fall through to the heuristics), so a
mis-resolution stops being a harmless miss and becomes a confident wrong answer
-- and this resolver feeds order placement.

That entry does not ban the map; it bans adding one without clearing two gates.
Both are asserted here rather than described:

  (a) the SOURCE carries the name the join was failing on -- `umass minutemen`,
      the exact token that defeated the 08-29 map;
  (b) nothing the heuristics used to leave unresolved is now resolved WRONGLY --
      `MAS` was the named failure and must stay None, and the pairs the prefix
      rule got wrong (`Iowa`/`Iowa State`, `Ohio`/`Ohio State`) must now be
      refused.

The five sports that already had maps are pinned too. A regression there would
be invisible: every one of them has a working join today.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import team_aliases as ta
from syndicate.features.shared.team_aliases import canonical_team, teams_match


def _registry_present() -> bool:
    try:
        from syndicate.features.ncaaf.oddsapi_lines import fbs_canonical_names

        return bool(fbs_canonical_names())
    except Exception:
        return False


# The registry CSV is git-tracked but excluded from session worktrees by design
# (`session_worktree.py` skips `data/`). Named loudly rather than skipped
# quietly: a silent skip here would look exactly like a passing suite.
needs_registry = pytest.mark.skipif(
    not _registry_present(),
    reason=(
        "ncaaf_team_registry_snapshot.csv absent -- run with SYNDICATE_DATA_ROOT "
        "pointed at a tree that carries data/, or open the worktree --with-data. "
        "These assertions are NOT optional; an absent registry means they did not run."
    ),
)


# ---------------------------------------------------------------------------
# The map exists, and it is FBS-sized
# ---------------------------------------------------------------------------


@needs_registry
def test_the_map_is_populated_and_covers_every_fbs_club() -> None:
    from syndicate.features.ncaaf.oddsapi_lines import fbs_canonical_names

    mapping = ta._alias_map("ncaaf")
    assert mapping, "the whole point of this change"
    assert len(set(mapping.values())) == len(fbs_canonical_names())


@needs_registry
def test_every_fbs_club_resolves_by_its_own_canonical_name() -> None:
    from syndicate.features.ncaaf.oddsapi_lines import fbs_canonical_names

    unresolved = [team for team in fbs_canonical_names() if not canonical_team("ncaaf", team)]
    assert unresolved == []


def test_an_absent_registry_yields_NO_map_rather_than_a_small_one(monkeypatch) -> None:
    """`unknown` must not land on the permissive branch. A partially-built map
    would make `teams_match` authoritative over a vocabulary that is mostly
    missing -- worse than having none at all."""
    import syndicate.features.ncaaf.oddsapi_lines as ol

    ta._ncaaf_alias_to_name.cache_clear()
    monkeypatch.setattr(ol, "fbs_canonical_names", lambda: frozenset())
    try:
        assert ta._alias_map("ncaaf") == {}
    finally:
        ta._ncaaf_alias_to_name.cache_clear()


# ---------------------------------------------------------------------------
# Canonical names, abbreviations, punctuation and spelling variants
# ---------------------------------------------------------------------------


@needs_registry
@pytest.mark.parametrize(
    "token,expected",
    [
        ("Ohio State", "ohio state"),
        ("Alabama", "alabama"),
        ("Notre Dame", "notre dame"),
        # A known abbreviation.
        ("UCF", "ucf"),
        ("TCU", "tcu"),
        ("LSU", "lsu"),
        ("BYU", "byu"),
        ("SMU", "smu"),
        # Punctuation and spelling variants that are NOT ambiguous -- exactly
        # what a map is for.
        ("Texas A&M", "texas a&m"),
        ("Texas A and M", "texas a&m"),
        ("Ole Miss", "ole miss"),
        ("Pitt", "pittsburgh"),
        ("Pittsburgh", "pittsburgh"),
        ("Boise St.", "boise state"),
        ("Boise State", "boise state"),
        # Apostrophes: CFBD spells these with one, the board's feed does not.
        ("Hawaii", "hawai'i"),
        ("Hawaii Rainbow Warriors", "hawai'i"),
        ("Louisiana Ragin Cajuns", "louisiana"),
        # The 08-29 gate (a) token, and the reason this map has a source the
        # reverted one did not.
        ("UMass", "massachusetts"),
        ("UMass Minutemen", "massachusetts"),
    ],
)
def test_a_name_the_feeds_actually_send_resolves(token: str, expected: str) -> None:
    assert canonical_team("ncaaf", token) == expected


@needs_registry
def test_the_directional_split_is_two_different_programmes() -> None:
    assert canonical_team("ncaaf", "Washington") == "washington"
    assert canonical_team("ncaaf", "Washington State") == "washington state"
    assert not teams_match("ncaaf", "Washington", "Washington State")


@needs_registry
def test_miami_is_resolved_by_QUALIFIER_and_the_two_never_meet() -> None:
    """DELIBERATE DEVIATION, STATED SO IT CANNOT BE MISTAKEN FOR AN OVERSIGHT.

    "Miami" is ambiguous in English and NOT in this vocabulary: CFBD names
    Miami FL `Miami` and Miami OH `Miami (OH)`, so the bare token is one
    programme's own canonical name rather than a coin flip between two. It
    would resolve through `canonical_team`'s already-a-value branch even if the
    map omitted the key, and `chip_join_key` has returned this same verdict via
    `resolve_team` since 2026-09-03 -- two resolvers disagreeing about one club
    is the drift `team_aliases` exists to prevent.

    What must hold is that the QUALIFIED forms are never confused, and that the
    two programmes never match each other.
    """
    assert canonical_team("ncaaf", "Miami") == "miami"
    assert canonical_team("ncaaf", "Miami FL") == "miami"
    assert canonical_team("ncaaf", "Miami Florida") == "miami"
    assert canonical_team("ncaaf", "Miami (OH)") == "miami (oh)"
    assert canonical_team("ncaaf", "Miami OH") == "miami (oh)"
    assert canonical_team("ncaaf", "Miami Ohio") == "miami (oh)"
    assert not teams_match("ncaaf", "Miami (OH)", "Miami")
    assert not teams_match("ncaaf", "Miami Ohio", "Miami")


# ---------------------------------------------------------------------------
# THE BAR: unambiguous within the sport, or nothing
# ---------------------------------------------------------------------------


@needs_registry
@pytest.mark.parametrize(
    "nickname",
    ["Bulldogs", "Tigers", "Wildcats", "Eagles", "Cougars", "Aggies", "Panthers", "Bears"],
)
def test_a_bare_nickname_shared_by_several_programmes_resolves_to_NOTHING(nickname: str) -> None:
    """ASSERTED, NOT INCIDENTAL. College football is where this bites: on the
    2026-08-26 snapshot `tigers` is claimed by 25 schools (5 FBS) and
    `bulldogs` by 23 (4 FBS). 95 keys were dropped for collision and every one
    was a bare mascot. Resolving these to the most popular programme would put
    a real order on the wrong game.
    """
    assert canonical_team("ncaaf", nickname) is None
    assert canonical_team("ncaaf", nickname.lower()) is None


@needs_registry
def test_a_mascot_unique_across_all_684_schools_is_allowed_through() -> None:
    """The collision rule is a refusal of AMBIGUITY, not of nicknames."""
    assert canonical_team("ncaaf", "Buckeyes") == "ohio state"
    assert canonical_team("ncaaf", "Boilermakers") == "purdue"


@needs_registry
def test_no_last_word_nicknames_are_derived_for_this_sport() -> None:
    """`_nickname_alias_map`'s premise -- that a club is "<City> <Nickname>" --
    is false for CFBD's SCHOOL names, where the last word is a qualifier.
    Deriving anyway yielded `southern` -> Georgia Southern, `green` -> Bowling
    Green, `a&m` -> Texas A&M: unique only because the FBS filter hides
    Southern University, Florida A&M and Alabama A&M."""
    assert ta._nickname_alias_map("ncaaf") == {}
    assert canonical_team("ncaaf", "Southern") is None
    assert canonical_team("ncaaf", "A&M") is None


@needs_registry
def test_the_reverted_attempts_named_failure_stays_unresolved() -> None:
    """GATE (b). `MAS` is UMass Dartmouth's real abbreviation and collides with
    the synthetic three-letter abbr a board chip builds for Massachusetts. The
    08-29 map answered `UMass Dartmouth` and that is what got it reverted."""
    assert canonical_team("ncaaf", "MAS") is None
    assert canonical_team("ncaaf", "mas") is None
    assert not teams_match("ncaaf", "MAS", "Idaho Vandals")


@needs_registry
@pytest.mark.parametrize(
    "pair",
    [("Iowa", "Iowa State"), ("Ohio", "Ohio State"), ("Texas", "North Texas")],
)
def test_a_school_is_not_its_neighbour_with_a_suffix(pair) -> None:
    """These were all TRUE on the bare prefix heuristic before the map existed
    -- `teams_match` accepted a token that is a prefix of any word in the row.
    A map that only ever added answers would have left them wrong."""
    left, right = pair
    assert not teams_match("ncaaf", left, right)
    assert teams_match("ncaaf", left, left)
    assert teams_match("ncaaf", right, right)


# ---------------------------------------------------------------------------
# FCS and non-FBS opponents, which appear on real slates
# ---------------------------------------------------------------------------


@needs_registry
@pytest.mark.parametrize(
    "school",
    [
        "Albany", "Merrimack", "St. Anselm", "Bethune-Cookman", "West Georgia",
        "Villanova Wildcats", "Towson Tigers", "UC Davis Aggies", "Wagner Seahawks",
    ],
)
def test_a_non_fbs_opponent_resolves_to_nothing_without_raising(school: str) -> None:
    """The map is FBS-only and the collision pass counts offers across ALL FOUR
    divisions before filtering, so a code an FCS school also claims is dropped
    rather than handed to the FBS one. These fall back to the heuristics, which
    is exactly the behaviour they had before this change."""
    assert canonical_team("ncaaf", school) is None


@needs_registry
def test_an_unknown_school_resolves_to_nothing_without_raising() -> None:
    for token in ("Nowhere Tech", "", None, 12345, "   "):
        assert canonical_team("ncaaf", token) is None


# ---------------------------------------------------------------------------
# FALSIFICATION: the five sports that already had maps are untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sport,alias_entries,nickname_entries",
    [("mlb", 38, 27), ("nfl", 39, 32), ("nba", 42, 26), ("wnba", 50, 0), ("soccer", 508, 71)],
)
def test_the_other_sports_maps_are_the_same_size_as_before(
    sport: str, alias_entries: int, nickname_entries: int
) -> None:
    """Pinned counts, measured on this commit's parent. NCAAF's branch is added
    AFTER every other branch returns, so nothing above it can be reached
    differently -- but a map is exactly the kind of shared state where that
    argument has been wrong before."""
    assert len(ta._alias_map(sport)) == alias_entries
    assert len(ta._nickname_alias_map(sport)) == nickname_entries


@pytest.mark.parametrize(
    "sport,token,expected",
    [
        ("mlb", "chc", "chicago cubs"),
        ("mlb", "cws", "chicago white sox"),
        ("mlb", "Padres", "san diego padres"),
        ("nfl", "GB", "green bay packers"),
        ("nfl", "Chargers", "los angeles chargers"),
        ("nba", "lal", "los angeles lakers"),
        ("wnba", "min", "minnesota lynx"),
        ("nba", "min", "minnesota timberwolves"),
        ("soccer", "Real Madrid", "real madrid"),
        # Sports that still have no map at all, and must keep refusing.
        ("nhl", "TOR", None),
        ("ncaab", "Duke", None),
    ],
)
def test_resolution_for_every_other_sport_is_unchanged(sport, token, expected) -> None:
    assert canonical_team(sport, token) == expected


@pytest.mark.parametrize("sport,tokens", [("mlb", 86), ("nfl", 95), ("nba", 92), ("wnba", 49), ("soccer", 403)])
def test_unambiguous_club_tokens_unchanged_for_the_other_sports(sport, tokens) -> None:
    assert len(ta.unambiguous_club_tokens(sport)) == tokens


def test_the_sports_with_no_map_still_get_an_empty_token_set() -> None:
    """`unknown` must not default permissive. nhl and ncaab keep refusing."""
    assert ta.unambiguous_club_tokens("nhl") == frozenset()
    assert ta.unambiguous_club_tokens("ncaab") == frozenset()


@needs_registry
def test_the_603_quote_token_shape_is_HELD_even_though_ncaaf_now_canonicalises() -> None:
    """The one place a map would have SUBTRACTED coverage.

    `game_token`'s two halves get different vocabularies -- the board row holds
    full club names, `_polymarket_sides` holds slug fragments ("nmxst",
    "flst"). With NCAAF resolvable, the board half would build a club-pair
    token while the venue half still built `evt:`, and
    `venue_quote_fanin._quote_is_for_another_game` rejects a quote whose game
    disagrees. `game_token` therefore refuses NCAAF explicitly, which is
    byte-for-byte what it did before the map existed.
    """
    from syndicate.features.shared.venue_quote_adapters import event_game_token, game_token

    assert canonical_team("ncaaf", "Florida State Seminoles") == "florida state"
    assert canonical_team("ncaaf", "New Mexico State Aggies") == "new mexico state"
    assert game_token("ncaaf", "Florida State Seminoles", "New Mexico State Aggies") is None
    assert event_game_token("evt-nmxst-flst") == "evt:evt-nmxst-flst"
    # The sports that DID have maps keep their club-pair token.
    assert game_token("mlb", "Chicago Cubs", "Toronto Blue Jays") == "chicago cubs+toronto blue jays"


@needs_registry
def test_match_event_blob_can_now_resolve_an_fbs_pairing() -> None:
    """THE CHOKE POINT THIS CHANGE EXISTS TO REMOVE. `match_event_blob`'s
    resolver branch requires BOTH split halves to canonicalise; with
    `_alias_map('ncaaf')` empty it produced an empty candidate list and skipped
    every NCAAF game, so a Kalshi ticker could never name one of our fixtures.
    """
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    games = [
        {"event_id": "g1", "away_team": "Texas Longhorns", "home_team": "Ohio State Buckeyes"},
        {"event_id": "g2", "away_team": "Clemson Tigers", "home_team": "LSU Tigers"},
    ]
    # Kalshi spells the clubs with codes our board does not use.
    assert match_event_blob("TEXOSU", games, sport="ncaaf")["status"] == "ok"
    assert match_event_blob("TEXOSU", games, sport="ncaaf")["event_id"] == "g1"
    assert match_event_blob("CLEMLSU", games, sport="ncaaf")["event_id"] == "g2"
    # An FCS visitor still refuses rather than guessing.
    fcs = [{"event_id": "g3", "away_team": "Wagner Seahawks", "home_team": "James Madison Dukes"}]
    assert match_event_blob("WAGJMU", fcs, sport="ncaaf")["status"] == "no_match"


@needs_registry
def test_ncaaf_tokens_exclude_the_words_many_programmes_share() -> None:
    """`unambiguous_club_tokens`' own docstring warned that "Ohio State
    Buckeyes" would otherwise offer `ncaaf|h2h|state` -- a key that could win a
    quote from an entirely different fixture."""
    tokens = ta.unambiguous_club_tokens("ncaaf")
    assert tokens, "an empty set here would mean the map failed to build"
    for shared in ("state", "ohio", "miami", "carolina", "tech", "southern", "texas", "north"):
        assert shared not in tokens
