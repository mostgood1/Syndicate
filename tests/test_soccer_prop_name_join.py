"""Soccer prop name join: same-match unique surname, HTML entities, non-player selections.

Lane `soccer-prop-name-join` (2026-10-05). Measured on the fleet grid that day, of 1,306
`player_miss_name` rows: 288 were players on the match's OWN roster under a first-name
variant (`Nicolas Paz` / `Nico Paz`, `Anastasios Douvikas` / `Tasos Douvikas`), 138 were
`No Scorer` selections, and a few sim names were HTML-entity encoded (`Dara O&#039;Shea`).
"""
from __future__ import annotations

from tests.test_soccer_projection_attribution import DATE, _player_row, _write_with_players

from syndicate.features.shared.soccer_projections import (
    attach_soccer_projections,
    load_soccer_projections,
)


def _join(tmp_path, roster, board_name, market="player_shots"):
    _write_with_players(tmp_path, "serie_a", DATE, "Como", "Inter", roster)
    index = load_soccer_projections([tmp_path], DATE, window_dates=[DATE])
    rows = [_player_row("serie_a", "Como", "Inter", board_name, market=market)]
    return rows, attach_soccer_projections(rows, index)


def test_a_first_name_variant_joins_on_a_unique_surname(tmp_path):
    rows, cov = _join(tmp_path, ["Nico Paz", "Lautaro Martinez"], "Nicolas Paz")
    assert rows[0].get("projection") is not None
    assert cov["player_surname_hits"] == 1
    assert cov["unmatched_player_rows"] == 0


def test_off_is_not_on_the_variant_does_not_join_without_the_surname_rule(tmp_path):
    """Reachability: the same board name against a roster WITHOUT that surname misses,
    so the join above is the surname rule's doing and not some other path."""
    rows, cov = _join(tmp_path, ["Lautaro Martinez"], "Nicolas Paz")
    assert rows[0].get("projection") is None
    assert cov["player_surname_hits"] == 0
    assert cov["unmatched_player_rows"] == 1


def test_a_shared_surname_in_the_match_is_refused(tmp_path):
    rows, cov = _join(tmp_path, ["Nico Paz", "Martin Paz"], "Nicolas Paz")
    assert rows[0].get("projection") is None
    assert cov["player_alias_ambiguous"] == 1
    assert cov["player_surname_hits"] == 0


def test_a_short_surname_is_never_used(tmp_path):
    rows, cov = _join(tmp_path, ["Nico Li"], "Nicolas Li")
    assert rows[0].get("projection") is None
    assert cov["player_surname_hits"] == 0


def test_an_html_entity_sim_name_joins_the_plain_board_name(tmp_path):
    rows, cov = _join(tmp_path, ["Dara O&#039;Shea"], "Dara O'Shea")
    assert rows[0].get("projection") is not None
    assert cov["unmatched_player_rows"] == 0


def test_no_scorer_is_counted_apart_from_player_misses(tmp_path):
    rows, cov = _join(tmp_path, ["Nico Paz"], "No Scorer", market="player_first_goal_scorer")
    assert cov["non_player_selection_rows"] == 1
    assert cov["unmatched_player_rows"] == 0
    assert cov["player_miss_name"] == 0


def test_an_initialled_sim_name_joins_the_full_board_name(tmp_path):
    """`B. Saka` (sim) is `Bukayo Saka` (board): the same player, joined by surname."""
    rows, cov = _join(tmp_path, ["B. Saka", "Martin Odegaard"], "Bukayo Saka")
    assert rows[0].get("projection") is not None
    assert cov["player_surname_hits"] == 1


def test_a_curly_apostrophe_sim_name_joins_the_straight_board_name(tmp_path):
    rows, cov = _join(tmp_path, ["Konan N’Dri"], "Konan N'Dri")
    assert rows[0].get("projection") is not None
    assert cov["unmatched_player_rows"] == 0
