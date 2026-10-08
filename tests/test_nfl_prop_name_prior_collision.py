"""A short name AMBIGUOUS this season does not fall back to the prior season, where it may have been unique.

Lane `nfl-passing-yards-prop-coin` (2026-10-08): "Jalon Daniels" (TB, 2026) shares `j.daniels` with Jayden
Daniels, and `resolve_player_id_with_prior` returned Jayden's id because 2025 had only him.
"""
from __future__ import annotations

from syndicate.features.nfl import player_stats as ps


def test_an_ambiguous_current_season_name_does_not_fall_back(monkeypatch):
    index = {2026: {}, 2025: {"j.daniels": "JAYDEN"}}
    collisions = {2026: {"j.daniels": frozenset({"JAYDEN", "JALON"})}, 2025: {}}
    monkeypatch.setattr(ps, "player_name_index", lambda season: index.get(season, {}))
    monkeypatch.setattr(ps, "player_name_collisions", lambda season: collisions.get(season, {}))
    assert ps.resolve_player_id_with_prior(2026, "Jalon Daniels") == (None, "ambiguous_current_season")


def test_an_absent_current_season_name_still_falls_back(monkeypatch):
    """Off != on: the week-1 fallback this function exists for is untouched."""
    monkeypatch.setattr(ps, "player_name_index", lambda season: {2025: {"j.daniels": "JAYDEN"}}.get(season, {}))
    monkeypatch.setattr(ps, "player_name_collisions", lambda season: {})
    assert ps.resolve_player_id_with_prior(2026, "Jayden Daniels") == ("JAYDEN", "prior_season_fallback")


def test_the_board_path_without_teams_inherits_the_refusal(monkeypatch):
    monkeypatch.setattr(ps, "player_name_index", lambda season: {2025: {"j.daniels": "JAYDEN"}}.get(season, {}))
    monkeypatch.setattr(ps, "player_name_collisions",
                        lambda season: {"j.daniels": frozenset({"JAYDEN", "JALON"})} if season == 2026 else {})
    assert ps.resolve_player_id_for_game(2026, 5, "Jalon Daniels", set(), lambda t: t) == (None, "ambiguous_current_season")
