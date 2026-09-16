"""`team_by_name` falls back to the shared alias map, inside the league only.

USER-REPORTED 2026-09-16 (lane `layer2-chip-rail-duplicate`): the Layer 2 chip
for Sevilla's match read `SEV / Deportiv`. ESPN sends the club as `Deportivo`;
the la_liga branding CSV lists only `Deportivo La Coruña` (`DEP`), so
`team_by_name` missed and `cards._abbr` minted an eight-letter label. The chip's
`key` was already `deportivo la coruña`, because `game_chip_scoreboard` asks
`canonical_team` and this directory never did.

Census before the change, over 410 (league, name) pairs -- every soccer chip
name on the production feed at 14:20Z plus every branding spelling: exactly one
pair changed, `la_liga|Deportivo` None -> DEP, and no existing hit moved.

Reads the git-tracked branding CSVs, like `test_soccer_sources.py`.
"""

from __future__ import annotations

from unittest.mock import patch

from syndicate.features.shared.team_aliases import canonical_team
from syndicate.features.soccer import sources as soccer_sources
from syndicate.features.soccer.cards import _abbr


def test_espn_short_name_resolves_to_the_branding_club():
    team = soccer_sources.team_by_name("la_liga", "Deportivo")
    assert team is not None, "`Deportivo` still misses the la_liga directory"
    assert team.get("abbreviation") == "DEP"
    assert str(team.get("team_id")) == "90"


def test_the_chip_label_is_the_tri_code_not_a_truncated_name():
    assert _abbr("Deportivo", "la_liga") == "DEP"


def test_a_sport_wide_alias_for_another_leagues_club_is_refused():
    # The population must be live, or this guard proves nothing: the alias map
    # DOES resolve `Athletic`, to a club that is not in La Liga.
    canonical = canonical_team("soccer", "Athletic")
    assert canonical, "precondition: `Athletic` must resolve somewhere for this guard to mean anything"
    la_liga_names = {str(t.get("name") or "").casefold() for t in soccer_sources.all_teams("la_liga")}
    assert canonical.casefold() not in la_liga_names, "precondition: the alias must name a club outside La Liga"

    assert soccer_sources.team_by_name("la_liga", "Athletic") is None


def test_the_directory_spelling_wins_over_the_alias_map():
    # A wrong alias answer must not displace a name the CSV already spells.
    with patch("syndicate.features.shared.team_aliases.canonical_team", return_value="barcelona"):
        team = soccer_sources.team_by_name("la_liga", "Sevilla")
    assert (team or {}).get("abbreviation") == "SEV"


def test_an_unresolvable_name_still_returns_none():
    assert soccer_sources.team_by_name("la_liga", "Not A Club Anywhere FC") is None
