"""One player, several spellings: the live re-sim and the board join use the engine's canonical key (`#762` (7)).

Measured 2026-11-09 02:36Z on the served board: 18 of 399 live NBA prop rows had no Live proj./actual. 12 were three
spellings that split a single player:
  - the odds feed's `Derrick Jones` against the lens's `Derrick Jones Jr.` (6 rows; the join kept the suffix);
  - `Herb Jones` (odds CSV, ESPN) against the engine's `Herbert Jones` (4 rows; the re-sim had no alias table, so
    it found no lines for him and published no row);
  - `A.J. Green` (odds CSV) against the engine's `AJ Green` (2 rows; the re-sim turned periods into spaces).
These tests run the real producer into the real join, and they pin that the old keys miss (off != on).
"""
from __future__ import annotations

import csv
import unicodedata

import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_projection_join as J

_OLD_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _old_normalize_name(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)
    return " ".join(p for p in s.split() if p not in _OLD_SUFFIXES)


@pytest.mark.parametrize("a, b", [
    ("A.J. Green", "AJ Green"),
    ("Herb Jones", "Herbert Jones"),
    ("Derrick Jones", "Derrick Jones Jr."),
    ("Trey Murphy III", "Trey Murphy"),
    ("Karlo Matković", "Karlo Matkovic"),
    ("De'Andre Hunter", "De’Andre Hunter"),
    ("De'Andre Hunter", "DeAndre Hunter"),
    ("Nic Claxton", "Nicolas Claxton"),
])
def test_producer_one_player_one_key(a, b):
    assert lr.normalize_name(a) == lr.normalize_name(b) != ""


def test_producer_different_players_stay_different():
    assert lr.normalize_name("Jalen Williams") != lr.normalize_name("Jaylin Williams")
    assert lr.normalize_name("Herbert Jones") != lr.normalize_name("Derrick Jones Jr.")
    assert lr.normalize_name("Nikola Jokić") != lr.normalize_name("Nikola Jović")


def test_old_producer_key_split_them():
    assert _old_normalize_name("A.J. Green") != _old_normalize_name("AJ Green")
    assert _old_normalize_name("Herb Jones") != _old_normalize_name("Herbert Jones")


HOME, AWAY = "Milwaukee Bucks", "New Orleans Pelicans"
ENGINE = ("AJ Green", "Herbert Jones")          # the engine frames' own `player_name`
CSV_NAME = {"AJ Green": "A.J. Green", "Herbert Jones": "Herb Jones"}   # the odds feed's
ESPN_NAME = {"AJ Green": "AJ Green", "Herbert Jones": "Herb Jones"}    # ESPN's box score


def _props_csv(tmp_path):
    path = tmp_path / "props.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["home_team", "away_team", "market", "outcome_name", "player_name", "point"])
        w.writeheader()
        for engine_name in ENGINE:
            for side in ("Over", "Under"):
                w.writerow({"home_team": HOME, "away_team": AWAY, "market": "player_points", "outcome_name": side,
                            "player_name": CSV_NAME[engine_name], "point": "8.5"})
    return path


def _summary():
    athletes = [{"athlete": {"displayName": ESPN_NAME[n]}, "stats": ["4", "2", "1", "1-3", "0", "0", "1"]} for n in ENGINE]
    return {"boxscore": {"players": [{"statistics": [{"names": ["PTS", "REB", "AST", "3PT", "STL", "BLK", "TO"],
                                                      "athletes": athletes}]}]}}


def _producer_rows(tmp_path):
    result = {"sims_run": 100, "player_remainders": {"home": {n: {"pts": {"3": 50, "6": 50}} for n in ENGINE},
                                                     "away": {}}}
    lines = lr.lines_from_props_csv(_props_csv(tmp_path), HOME, AWAY)
    rows, coverage = lr.build_live_props(result, lr.actuals_from_summary(_summary()), lr.with_neighbour_lines(lines))
    return rows, coverage


def test_producer_finds_lines_and_actuals_across_spellings(tmp_path):
    rows, coverage = _producer_rows(tmp_path)
    at_line = {r["playerName"]: r for r in rows if r["line"] == 8.5}
    assert set(at_line) == set(ENGINE), sorted({r["playerName"] for r in rows})
    assert all(r["actualSoFar"] == 4.0 for r in at_line.values())
    assert coverage["no_actual"] == 0


def test_off_is_not_on_with_the_old_producer_key(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "normalize_name", _old_normalize_name)
    rows, _coverage = _producer_rows(tmp_path)
    assert rows == []


def _snapshot(names):
    rows = [{"playerName": n, "prop": "player_points", "line": 8.5, "liveProjection": 9.1, "liveModelProbOver": 0.55,
             "actualSoFar": 4.0, "side": "home", "simsRun": 100} for n in names]
    return {"games": [{"status": {"detailedState": "In Progress"}, "liveProps": rows}]}


def _grid(board_name):
    return [{"sport": "nba", "kind": "prop", "player_name": board_name, "market": "player_points", "line": 8.5,
             "side": "over", "game": {"state": "live"}}]


@pytest.mark.parametrize("lens_name, board_name", [
    ("Derrick Jones Jr.", "Derrick Jones"),
    ("Herbert Jones", "Herb Jones"),
    ("Trey Murphy III", "Trey Murphy"),
])
def test_join_falls_back_to_the_engine_key(lens_name, board_name):
    grid = _grid(board_name)
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot([lens_name])))
    assert cov["rows_live_projected"] == 1 and cov["rows_live_player_alias"] == 1, cov
    assert grid[0]["projection"]["live_aware"] is True
    assert grid[0]["projection"]["actual_so_far"] == 4.0


def test_the_web_read_time_refresh_uses_the_same_fallback():
    index = J.build_live_prop_index(_snapshot(["Derrick Jones Jr."]))
    hit = J.live_prop_hit(index, "Derrick Jones", "player_points", 8.5)
    assert hit is not None and hit["actual_so_far"] == 4.0


def test_off_is_not_on_without_the_fallback(monkeypatch):
    monkeypatch.setattr(J, "_resolve_player", lambda indexed, name: (J._norm_name(name), False))
    grid = _grid("Derrick Jones")
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot(["Derrick Jones Jr."])))
    assert cov["rows_live_projected"] == 0 and "projection" not in grid[0]


def test_an_exact_name_never_takes_the_fallback():
    grid = _grid("Gary Payton II")
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot(["Gary Payton II", "Gary Payton"])))
    assert cov["rows_live_projected"] == 1 and cov["rows_live_player_alias"] == 0


def test_an_ambiguous_engine_key_joins_nothing():
    # Two lens players share the canonical key `gary payton`; a board spelling that matches neither exactly is
    # a real ambiguity and must stay a miss.
    grid = _grid("Gary Payton III")
    cov = J.attach_live_projections(grid, J.build_live_prop_index(_snapshot(["Gary Payton II", "Gary Payton"])))
    assert cov["rows_live_projected"] == 0 and cov["rows_live_player_alias"] == 0
    assert "projection" not in grid[0]


def test_a_payload_from_an_older_index_builder_still_joins_exactly():
    index = J.build_live_prop_index(_snapshot(["Derrick Jones Jr."]))
    index.pop("players_by_canonical")
    assert J.live_prop_hit(index, "Derrick Jones Jr.", "player_points", 8.5) is not None
    assert J.live_prop_hit(index, "Derrick Jones", "player_points", 8.5) is None
