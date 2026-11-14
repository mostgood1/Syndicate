"""The roster's exact full name answers before the short-name keys. `#804`.

Lane `nfl-prop-name-roster-first`, 2026-11-14. `resolve_player_id_for_game` tried the plain key first, so a namesake
in the SAME game won: "Amon-Ra St. Brown" -> `a.brown` -> A.J. Brown (NE), who played DET on 11-15, and every St.
Brown prop in `nfl_prop_projections_2026_wk10.json` carried A.J. Brown's 3-game log (3.0 catches, team NE). The first
test FAILS on the pre-change code. Replayed over the 11-15 capture (421 quoted names): St. Brown moved to his own id,
four refused names resolved, and no name that resolved before moved.
"""
from __future__ import annotations

import pytest

from syndicate.features.nfl import player_stats as ps

_CANDIDATES = {
    2026: {
        "a.brown": frozenset({"P-AJBROWN"}),
        "a.st. brown": frozenset({"P-STBROWN"}),
        "k.williams": frozenset({"P-KYREN", "P-KWILLIAMS-OTHER"}),
        "j.palmer": frozenset({"P-PALMER"}),
    },
    2025: {},
}
_TEAM = {"P-AJBROWN": "NE", "P-STBROWN": "DET", "P-KYREN": "LAR", "P-KWILLIAMS-OTHER": "NYG", "P-PALMER": "BUF",
         "P-ROOKIE": "DAL"}
_ROSTER = ({"amon ra st brown": "P-STBROWN", "aj brown": "P-AJBROWN", "josh palmer": "P-PALMER",
            "rookie guy": "P-ROOKIE"},
           {"P-STBROWN": "amon ra st brown", "P-AJBROWN": "aj brown", "P-PALMER": "josh palmer", "P-ROOKIE": "rookie guy"})


@pytest.fixture(autouse=True)
def _fixture(monkeypatch):
    monkeypatch.setattr(ps, "_cached_name_candidates", lambda season: _CANDIDATES.get(season, {}))
    monkeypatch.setattr(ps, "player_team_with_prior", lambda season, week, pid: (_TEAM.get(pid), "current_season"))
    monkeypatch.setattr(ps, "roster_identity", lambda season: _ROSTER)


def _resolve(name, teams):
    return ps.resolve_player_id_for_game(2026, 10, name, set(teams), lambda t: t)


def test_a_namesake_in_the_same_game_no_longer_takes_the_row():
    """NE @ DET: `a.brown` is A.J. Brown and he is IN this game; the roster names St. Brown exactly."""
    assert _resolve("Amon-Ra St. Brown", {"NE", "DET"}) == ("P-STBROWN", "roster_full_name")
    assert _resolve("A.J. Brown", {"NE", "DET"}) == ("P-AJBROWN", "roster_full_name")


def test_without_the_roster_the_short_name_path_is_unchanged(monkeypatch):
    """Reachability: an empty roster gives the old answer -- which is the bug, so the fix above is the roster's doing."""
    monkeypatch.setattr(ps, "roster_identity", lambda season: ({}, {}))
    assert _resolve("Amon-Ra St. Brown", {"NE", "DET"}) == ("P-AJBROWN", "current_season")
    assert _resolve("Amon-Ra St. Brown", {"DET", "ARI"}) == ("P-STBROWN", "current_season")


def test_a_roster_player_on_neither_team_falls_back_to_the_short_name_keys():
    """The roster names him, but he plays for neither club in this game: not him, try the keys."""
    assert _resolve("Rookie Guy", {"NE", "DET"}) == (None, "unresolved")
    assert _resolve("Kyren Williams", {"LAR", "SF"})[0] == "P-KYREN"


def test_a_book_spelling_the_roster_does_not_know_still_resolves_by_short_name():
    """"Joshua Palmer" is "Josh Palmer" on the roster. The replay refused three of these under a stricter rule."""
    assert _resolve("Joshua Palmer", {"BUF", "NYJ"}) == ("P-PALMER", "current_season")


def test_no_game_teams_is_still_the_old_resolver(monkeypatch):
    monkeypatch.setattr(ps, "player_name_index", lambda season: {})
    monkeypatch.setattr(ps, "player_name_collisions", lambda season: set())
    assert _resolve("Amon-Ra St. Brown", set()) == (None, "unresolved")


def test_roster_identity_reads_the_snapshot_and_drops_a_shared_name(tmp_path, monkeypatch):
    from syndicate.features.nfl import sources

    path = tmp_path / "roster_2026_snapshot.csv"
    path.write_text(
        "player_id,player_name,team\n"
        "00-0036963,Amon-Ra St. Brown,DET\n"
        "00-0035676,A.J. Brown,NE\n"
        "00-1,Josh Allen,BUF\n"
        "00-2,Josh Allen,JAX\n",
        encoding="utf-8",
    )
    monkeypatch.undo()  # the real function, not the fixture's stub
    monkeypatch.setattr(sources, "nfl_roster_snapshot_path", lambda season: path)
    real = ps.roster_identity.__wrapped__  # past the lru_cache, so no other test's read leaks in
    by_name, name_of = real(2026)
    assert by_name["amon ra st brown"] == "00-0036963"
    assert by_name["aj brown"] == "00-0035676"
    assert "josh allen" not in by_name, "two ids share the name: no evidence picks one"
    assert name_of["00-2"] == "josh allen"
    monkeypatch.setattr(sources, "nfl_roster_snapshot_path", lambda season: tmp_path / "absent.csv")
    assert real(2026) == ({}, {})
