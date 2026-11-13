"""A club the odds feed names differently from ESPN's branding snapshot still gets its crest (lane team-logo-canonical-names, #796).

Measured on the fleet's served board 2026-11-13 14:11Z: 177 of 1,567 NBA rows (all of Oklahoma City Thunder @ Los Angeles
Clippers) had no Clippers crest, and the game's 22 Clippers prop rows no `player_side`. ESPN's snapshot spells the club
"LA Clippers" / "LAC" / "LA"; the odds feed says "Los Angeles Clippers". `logo_url`'s alias pass mapped that to the canonical
"los angeles clippers", which the index did not hold. `player_headshots.player_side` matches a player's team to a side BY
CREST, so the missing crest also cost every Clippers player his side.

Each behaviour has an OFF arm -- the index without canonical names -- that must differ (off != on).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import team_aliases
from syndicate.features.shared import team_logos

HEADER = "team_id,abbreviation,location,display_name,primary_color,secondary_color,logo_url,source_snapshot_date\n"
LAC = "https://a.espncdn.com/i/teamlogos/nba/500/lac.png"
LAL = "https://a.espncdn.com/i/teamlogos/nba/500/lal.png"
OKC = "https://a.espncdn.com/i/teamlogos/nba/500/okc.png"

# ESPN's snapshot as the fleet holds it: the Clippers' display name is "LA Clippers".
NBA_ROWS = (
    f"12,LAC,LA,LA Clippers,,,{LAC},2026-10-01\n"
    f"13,LAL,Los Angeles,Los Angeles Lakers,,,{LAL},2026-10-01\n"
    f"25,OKC,Oklahoma City,Oklahoma City Thunder,,,{OKC},2026-10-01\n"
)


@pytest.fixture
def branding(tmp_path, monkeypatch):
    path = Path(tmp_path) / "nba_team_branding.csv"
    path.write_text(HEADER + NBA_ROWS, encoding="utf-8")
    monkeypatch.setattr(team_logos, "_branding_files", lambda sport: [path])
    cached_index = team_logos._index  # an OFF arm swaps `_index` out until monkeypatch undoes it
    cached_index.cache_clear()
    yield path
    cached_index.cache_clear()


def no_canonical_names(monkeypatch) -> None:
    """The pre-fix index: ESPN's display name, location and abbreviation only.

    `canonical_team` is still reachable from `logo_url`'s own alias pass, exactly as before the fix; only the index
    build is denied it.
    """
    real = team_aliases.canonical_team
    calls = {"index": False}
    original_index = team_logos._index.__wrapped__

    def index_without_canonical(sport):
        calls["index"] = True
        monkeypatch.setattr(team_aliases, "canonical_team", lambda *_a, **_k: None)
        try:
            return original_index(sport)
        finally:
            monkeypatch.setattr(team_aliases, "canonical_team", real)

    team_logos._index.cache_clear()
    monkeypatch.setattr(team_logos, "_index", index_without_canonical)


# ------------------------------------------------------------------------------------------------------ the gap

def test_the_odds_feed_name_gets_the_crest(branding, monkeypatch):
    assert team_logos.logo_url("nba", "Los Angeles Clippers") == LAC
    no_canonical_names(monkeypatch)
    assert team_logos.logo_url("nba", "Los Angeles Clippers") is None  # off: the 11-13 board


def test_the_row_stamp_gets_the_home_crest(branding, monkeypatch):
    def rows():
        return [{"sport": "nba", "home_team": "Los Angeles Clippers", "home_key": "los angeles clippers",
                 "away_team": "Oklahoma City Thunder", "away_key": "oklahoma city thunder"}]

    on = rows()
    assert team_logos.stamp_row_logos(on) == 1
    assert (on[0].get("home_logo"), on[0].get("away_logo")) == (LAC, OKC)
    no_canonical_names(monkeypatch)
    off = rows()
    team_logos.stamp_row_logos(off)
    assert (off[0].get("home_logo"), off[0].get("away_logo")) == (None, OKC)


def test_a_clippers_prop_row_gets_its_side(branding, monkeypatch):
    """Reachability: `player_side` matches the player's team ("LAC", from the roster) to a side by crest."""
    from syndicate.features.shared import player_headshots as H

    monkeypatch.setattr(H, "_player_team", lambda row: "LAC")
    row = {"sport": "nba", "kind": "prop", "player_name": "Kris Dunn", "home_team": "Los Angeles Clippers",
           "away_team": "Oklahoma City Thunder"}
    assert H.player_side(row) == "home"
    no_canonical_names(monkeypatch)
    assert H.player_side(row) is None  # off: the 22 rows on 11-13


# ------------------------------------------------------------------------------------------- what must not change

def test_espn_keys_still_win(branding):
    """"LA" is the Clippers' ESPN location and "Los Angeles" the Lakers'; neither moves."""
    assert team_logos.logo_url("nba", "LA") == LAC
    assert team_logos.logo_url("nba", "Los Angeles") == LAL
    assert team_logos.logo_url("nba", "LA Clippers") == LAC
    assert team_logos.logo_url("nba", "LAC") == LAC
    assert team_logos.logo_url("nba", "Los Angeles Lakers") == LAL
    assert team_logos.logo_url("nba", "Oklahoma City Thunder") == OKC


def test_a_canonical_name_two_crests_claim_is_left_out(branding, monkeypatch):
    """Never a guess: if the alias map ever sent two clubs to one name, that name resolves to no crest."""
    monkeypatch.setattr(team_aliases, "canonical_team",
                        lambda sport, name: "la team" if "Lakers" in str(name) or "Clippers" in str(name) else None)
    team_logos._index.cache_clear()
    index = team_logos._index("nba")
    assert "lateam" not in index  # claimed by the Lakers' AND the Clippers' crest
    assert index["la"] == LAC and index["losangeles"] == LAL  # ESPN's own keys unchanged


def test_a_canonical_name_never_overrides_an_espn_key(branding, monkeypatch):
    """If the alias map ever named the Clippers "Los Angeles", the Lakers' ESPN location keeps its crest."""
    monkeypatch.setattr(team_aliases, "canonical_team",
                        lambda sport, name: "los angeles" if "Clippers" in str(name) or str(name) == "LAC" else None)
    team_logos._index.cache_clear()
    assert team_logos._index("nba")["losangeles"] == LAL


def test_an_unknown_club_is_still_none(branding):
    assert team_logos.logo_url("nba", "Seattle SuperSonics") is None


def test_a_failing_alias_map_is_the_espn_only_index(branding, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("alias map unavailable")

    monkeypatch.setattr(team_aliases, "canonical_team", boom)
    team_logos._index.cache_clear()
    assert team_logos.logo_url("nba", "LA Clippers") == LAC
    assert team_logos.logo_url("nba", "Los Angeles Clippers") is None
