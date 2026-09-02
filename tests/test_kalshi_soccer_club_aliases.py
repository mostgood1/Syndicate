"""Kalshi's soccer club spellings resolve -- and the ones we could not FORCE
still refuse.

Derived per LEAGUE from Kalshi's own `<Club> wins` market titles, then paired
against our rosters under two exact rules (token-subset, or a token unique on
both residual sides). 119 of 153 Kalshi clubs already resolved unaided and are
deliberately not in the table. Nine were refused for failing both rules.

The refusal half is the half worth testing. An alias table is authoritative and
skips the heuristics, so a wrong entry is a real order on the wrong club.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.team_aliases import canonical_team


def _rosters_present() -> bool:
    return bool(canonical_team("soccer", "Real Madrid"))


needs_rosters = pytest.mark.skipif(
    not _rosters_present(),
    reason=(
        "per-league soccer rosters absent -- `data/` is excluded from session "
        "worktrees by default, so every club resolves to None. The alias TABLE "
        "itself is asserted without the mirror in TestTheTableShape."
    ),
)


class TestTheTableShape:
    """Runs everywhere, including worktrees with no `data/`."""

    def test_the_refused_clubs_are_absent_from_the_table(self):
        """Nine pairings were not forced by the rules and must not be written.
        `Bilbao`/`Athletic Club` share no token; `St. Truidense` shares `st`
        with `Union St.-Gilloise`, so uniqueness fails."""
        from syndicate.features.shared.team_aliases import _SOCCER_VENDOR_NAME_ALIASES

        for refused in (
            "bilbao", "st. truidense", "st truidense", "fc koln", "m gladbach",
            "enschede", "los angeles g", "los angeles f",
        ):
            assert refused not in _SOCCER_VENDOR_NAME_ALIASES, refused

    def test_no_alias_key_collides_with_a_collision_prone_club_name(self):
        """`LEV`/`PAR`/`GEN`/`TOR` each name two clubs across leagues. The table
        is keyed on NAMES, never codes, precisely so those cannot be written."""
        from syndicate.features.shared.team_aliases import _SOCCER_VENDOR_NAME_ALIASES

        for code in ("lev", "par", "gen", "tor", "atm", "ath", "stt"):
            assert code not in _SOCCER_VENDOR_NAME_ALIASES, code


@needs_rosters
class TestAgainstTheRealRosters:
    @pytest.mark.parametrize("kalshi_name", [
        "La Louviere", "Standard", "Union Gilloise", "Atletico",
        "Deportivo De La Coruna", "Stade Brest 29", "Strasbourg Alsace",
        "Parma Calcio", "Paderborn", "Schalke", "Den Haag", "GA Eagles",
        "Sparta", "Newcastle", "Coventry", "Brighton", "Tottenham",
        "Philadelphia", "Vancouver", "New England", "San Jose", "Houston",
        "Seattle", "Salt Lake", "Colorado", "Saint Louis", "Minnesota",
        "Kansas City", "Portland", "Orlando", "Miami", "Atlanta",
        "New York RB", "Columbus",
    ])
    def test_every_written_kalshi_spelling_resolves(self, kalshi_name):
        assert canonical_team("soccer", kalshi_name)

    @pytest.mark.parametrize("refused", [
        "Bilbao", "St. Truidense", "FC Koln", "M gladbach", "Enschede",
        "Los Angeles G", "Los Angeles F",
    ])
    def test_a_club_we_could_not_force_still_refuses(self, refused):
        """None is the correct answer for an unproven pairing. Guessing here is
        how a bet reaches the wrong team."""
        assert canonical_team("soccer", refused) is None

    @pytest.mark.parametrize("name,expected", [
        # The cross-league code collisions, resolved by NAME and each landing on
        # its own club. A flattened code map had LEV=Leverkusen and PAR=Parma,
        # which in la_liga/ligue_1 are Levante and Paris FC.
        ("Levante", "levante"),
        ("Leverkusen", "bayer leverkusen"),
        ("Paris FC", "paris fc"),
        ("Parma Calcio", "parma"),
        ("Torino", "torino"),
        ("Toronto", "toronto fc"),
        ("Genoa", "genoa"),
        ("Genk", "racing genk"),
    ])
    def test_collision_prone_names_land_on_the_right_club(self, name, expected):
        assert canonical_team("soccer", name) == expected

    @pytest.mark.parametrize("name,expected", [
        ("Real Madrid", "real madrid"), ("Toulouse", "toulouse"),
        ("Gent", "kaa gent"), ("Kortrijk", "kv kortrijk"), ("Arsenal", "arsenal"),
    ])
    def test_previously_working_names_are_unchanged(self, name, expected):
        """The control: this table uses `setdefault`, so it can only ADD."""
        assert canonical_team("soccer", name) == expected
