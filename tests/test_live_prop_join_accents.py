"""Accented player names join their unaccented board spelling (`#762`, 2026-11-07).

Measured on the DEN@IND live board at 22:40Z: 16 of 123 live NBA prop rows had no Live proj., all 16 were Nikola
Jokic's. The lens carries ESPN's `Nikola Jokić` and the board carries the odds feed's `Nikola Jokic`, and the join's
`_norm_name` turned `ć` into a space, so `nikola joki` never met `nikola jokic`. These tests run the real producer
rows through the real join, and they pin that the old normaliser misses (off != on).
"""
from __future__ import annotations

import re

import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_projection_join as J

BANKED = {"pts": 12, "reb": 7, "ast": 3, "threes": 1, "stl": 1, "blk": 0, "tov": 2}
JOINT = {"5,3,1,0,0": 40, "5,2,8,0,0": 30, "5,3,7,0,0": 10, "3,0,0,0,0": 20}


def _old_norm_name(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[.'`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


@pytest.mark.parametrize("lens, board", [
    ("Nikola Jokić", "Nikola Jokic"),
    ("Luka Dončić", "Luka Doncic"),
    ("Alperen Şengün", "Alperen Sengun"),
    ("Kristaps Porziņģis", "Kristaps Porzingis"),
    ("Jonas Valančiūnas", "Jonas Valanciunas"),
    ("Łukasz Fabiański", "Lukasz Fabianski"),
    ("Martin Ødegaard", "Martin Odegaard"),
    ("Đorđe Petrović", "Dorde Petrovic"),
    ("J.D. Martinez", "JD Martinez"),
])
def test_one_name_one_key(lens, board):
    assert J._norm_name(lens) == J._norm_name(board) != ""


def test_different_names_stay_different():
    assert J._norm_name("Nikola Jokić") != J._norm_name("Nikola Jović")
    assert J._norm_name("Will Smith") == "will smith"


def _snapshot(name="Nikola Jokić"):
    result = {"sims_run": 100, "player_remainders": {"home": {name: {"pts": {"5": 80, "3": 20},
                                                                     lr.DOUBLES_JOINT_KEY: dict(JOINT)}}, "away": {}}}
    lines = {(lr.normalize_name(name), "pts"): (15.5,), (lr.normalize_name(name), "dd"): (1.5,)}
    rows, _cov = lr.build_live_props(result, {lr.normalize_name(name): BANKED}, lines)
    assert {r["playerName"] for r in rows} == {name}            # the producer keeps ESPN's spelling
    return {"games": [{"status": {"detailedState": "In Progress"}, "liveProps": rows}]}


def _grid():
    game = {"state": "live"}
    return [
        {"sport": "nba", "kind": "prop", "player_name": "Nikola Jokic", "market": "player_points", "line": 15.5,
         "side": "over", "game": game},
        {"sport": "nba", "kind": "prop", "player_name": "Nikola Jokic", "market": "player_double_double", "line": None,
         "side": "Yes", "sides": ["yes"], "game": game},
    ]


def test_the_board_spelling_joins_the_lens_spelling():
    grid = _grid()
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot()))
    assert cov["rows_live_projected"] == 1 and cov["rows_live_display_only"] == 1, cov
    assert grid[0]["projection"]["live_aware"] is True
    assert grid[1]["projection"]["live_display_only"] is True and grid[1]["projection"]["actual_so_far"] == 1.0


def test_off_is_not_on_with_the_old_normaliser(monkeypatch):
    monkeypatch.setattr(J, "_norm_name", _old_norm_name)
    grid = _grid()
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot()))
    assert cov["rows_live_projected"] == 0 and cov["rows_live_display_only"] == 0
    assert all("projection" not in row for row in grid)


def test_the_web_read_time_refresh_finds_the_same_row():
    index = J.build_live_prop_index(_snapshot())
    hit = J.live_prop_hit(index, "Nikola Jokic", "player_points", 15.5)
    assert hit is not None and hit["actual_so_far"] == 12.0
