"""NFL prop names resolve to the ONE candidate playing in this game.

Lane `nfl-prop-name-resolution` (2026-10-07): short-name collisions (Kyren / Javonte Williams),
suffixes ("Michael Penix Jr." -> "M.Jr.") and multi-word surnames ("Amon-Ra St. Brown" ->
"A.Brown" = A.J. Brown) left stars unrated every week. Week-5 fleet rebuild: sim rows 758 -> 867,
stat-player pairs 263 -> 307, refused_wrong_team 38 -> 0.
"""
from __future__ import annotations

import pytest

from syndicate.features.nfl import player_stats as ps

_CANDIDATES = {
    2026: {
        "m.penix": frozenset({"P-PENIX"}),
        "a.brown": frozenset({"P-AJBROWN"}),
        "a.st. brown": frozenset({"P-STBROWN"}),
        "k.williams": frozenset({"P-KYREN", "P-KWILLIAMS-OTHER"}),
        "b.robinson": frozenset({"P-BIJAN", "P-BRIAN"}),
    },
    2025: {},
}
_TEAM = {"P-PENIX": "ATL", "P-AJBROWN": "PHI", "P-STBROWN": "DET", "P-KYREN": "LAR",
         "P-KWILLIAMS-OTHER": "NYG", "P-BIJAN": "ATL", "P-BRIAN": "ATL"}


@pytest.fixture(autouse=True)
def _fixture(monkeypatch):
    monkeypatch.setattr(ps, "_cached_name_candidates", lambda season: _CANDIDATES.get(season, {}))
    monkeypatch.setattr(ps, "player_team_with_prior", lambda season, week, pid: (_TEAM.get(pid), "current_season"))


def _resolve(name, teams):
    return ps.resolve_player_id_for_game(2026, 5, name, set(teams), lambda t: t)


def test_a_suffix_is_stripped():
    assert ps.short_name_keys("Michael Penix Jr.") == ["m.jr.", "m.penix"]
    assert _resolve("Michael Penix Jr.", {"ATL", "NO"})[0] == "P-PENIX"


def test_a_multi_word_surname_resolves_to_the_player_in_the_game():
    """'A.Brown' is A.J. Brown (PHI); in a DET game the full-surname key wins."""
    assert _resolve("Amon-Ra St. Brown", {"DET", "ARI"})[0] == "P-STBROWN"


def test_a_shared_short_name_is_broken_by_the_game_teams():
    pid, source = _resolve("Kyren Williams", {"LAR", "SF"})
    assert pid == "P-KYREN" and source.endswith("team_disambiguated")


def test_two_candidates_in_the_same_game_still_refuse():
    assert _resolve("Bijan Robinson", {"ATL", "NO"}) == (None, "ambiguous_in_game")


def test_off_is_not_on_without_game_teams_it_is_the_old_resolver(monkeypatch):
    """Reachability: with no teams the new path defers to `resolve_player_id_with_prior`,
    which drops the shared name -- so the match above is the team tie-break's doing."""
    monkeypatch.setattr(ps, "player_name_index", lambda season: {})
    assert _resolve("Kyren Williams", set()) == (None, "unresolved")


def test_a_player_on_neither_team_is_refused():
    assert _resolve("Kyren Williams", {"DAL", "TB"}) == (None, "unresolved")
