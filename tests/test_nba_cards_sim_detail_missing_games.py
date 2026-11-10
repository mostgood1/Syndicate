"""`cards_sim_detail_<D>.json` gains every simmed game it is missing (lane `nba-sim-index-missing-games`, todo `#778`).

The file for 2026-11-10 was written on 11-09 with one game (BOS@PHI). The other five games were simmed that afternoon,
and the export kept returning the one-game file, because `_copy_existing_processed_artifact` returns an existing file
whose source and destination are the same path. The pregame prop projection join reads only this file, so those
games' prop rows carried no model projection. Each behaviour below has an OFF arm, the pre-fix path, that must
differ.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import refresh_nba_oddsapi_props as nba
from syndicate.features.shared import nba_projections

DATE = "2026-11-10"


def _sim(home: str, away: str, pts: float, names: tuple[str, str]) -> dict:
    return {
        "home": home,
        "away": away,
        "date": DATE,
        "n_sims": 100,
        "players": {
            "home": [{"player_name": names[0], "pts_mean": pts, "team": home}],
            "away": [{"player_name": names[1], "pts_mean": pts - 3.0, "team": away}],
        },
        "periods": {"q1": {"home_mean": 28.0, "away_mean": 27.0, "total_mean": 55.0, "margin_mean": 1.0, "p_home_win": 0.52}},
    }


def _write_sim(processed: Path, home: str, away: str, pts: float, names: tuple[str, str]) -> None:
    (processed / f"smart_sim_{DATE}_{home}_{away}.json").write_text(json.dumps(_sim(home, away, pts, names)), encoding="utf-8")


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path]:
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    return tmp_path, processed


def _export(source_root: Path, processed: Path) -> str | None:
    return nba._export_cards_sim_detail_snapshot(source_root=source_root, date_str=DATE, processed_root=processed)


def _games(processed: Path) -> list[dict]:
    return json.loads((processed / f"cards_sim_detail_{DATE}.json").read_text(encoding="utf-8"))["games"]


def _key(game: dict) -> str:
    return f"{game['away_tri']}@{game['home_tri']}"


def _partial_file_then_more_sims(source_root: Path, processed: Path) -> dict:
    """The 11-09 06:03Z state (one game simmed and exported), then the afternoon: the same game re-simmed with a
    different mean, and two new games simmed."""
    _write_sim(processed, "PHI", "BOS", 20.0, ("Joel Embiid", "Jayson Tatum"))
    assert _export(source_root, processed)
    before = _games(processed)[0]
    _write_sim(processed, "PHI", "BOS", 25.0, ("Joel Embiid", "Jayson Tatum"))
    _write_sim(processed, "PHX", "LAC", 18.0, ("Devin Booker", "Derrick Jones Jr."))
    _write_sim(processed, "UTA", "MIA", 16.0, ("Lauri Markkanen", "Bam Adebayo"))
    return before


def test_partial_file_gains_the_missing_games(roots) -> None:
    source_root, processed = roots
    before = _partial_file_then_more_sims(source_root, processed)

    assert _export(source_root, processed) == str(processed / f"cards_sim_detail_{DATE}.json")

    games = _games(processed)
    assert [_key(g) for g in games] == ["BOS@PHI", "LAC@PHX", "MIA@UTA"]
    # The entry that was already there is untouched, even though a newer sim exists for it.
    assert games[0] == before
    assert games[0]["sim"]["players"]["home"][0]["pts_mean"] == 20.0
    # The added entries are exactly what the builder makes from their sim files.
    built = {_key(g): g for g in nba._build_cards_sim_detail_from_local_smart_sim(processed_root=processed, date_str=DATE)}
    assert games[1] == built["LAC@PHX"] and games[2] == built["MIA@UTA"]


def test_off_arm_the_pre_fix_path_leaves_the_file_partial(roots, monkeypatch) -> None:
    source_root, processed = roots
    _partial_file_then_more_sims(source_root, processed)
    monkeypatch.setattr(nba, "_merge_missing_cards_sim_detail_games", lambda **_: 0)

    _export(source_root, processed)

    assert [_key(g) for g in _games(processed)] == ["BOS@PHI"]


def test_a_complete_file_is_not_rewritten(roots) -> None:
    source_root, processed = roots
    _write_sim(processed, "PHI", "BOS", 20.0, ("Joel Embiid", "Jayson Tatum"))
    _write_sim(processed, "PHX", "LAC", 18.0, ("Devin Booker", "Derrick Jones Jr."))
    _export(source_root, processed)
    path = processed / f"cards_sim_detail_{DATE}.json"
    os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    data, stamp = path.read_bytes(), path.stat().st_mtime_ns
    # A newer re-sim of a game that is already in the file.
    _write_sim(processed, "PHX", "LAC", 30.0, ("Devin Booker", "Derrick Jones Jr."))

    _export(source_root, processed)

    assert path.read_bytes() == data
    assert path.stat().st_mtime_ns == stamp


def test_a_game_in_the_other_orientation_is_not_duplicated(roots) -> None:
    source_root, processed = roots
    path = processed / f"cards_sim_detail_{DATE}.json"
    path.write_text(json.dumps({"date": DATE, "games": [{"home_tri": "BOS", "away_tri": "PHI", "sim": {"players": {}}}]}), encoding="utf-8")
    _write_sim(processed, "PHI", "BOS", 20.0, ("Joel Embiid", "Jayson Tatum"))

    assert nba._merge_missing_cards_sim_detail_games(path=path, processed_root=processed, date_str=DATE) == 0
    assert [_key(g) for g in _games(processed)] == ["PHI@BOS"]


def test_no_existing_file_still_builds_every_game(roots) -> None:
    source_root, processed = roots
    _write_sim(processed, "PHI", "BOS", 20.0, ("Joel Embiid", "Jayson Tatum"))
    _write_sim(processed, "PHX", "LAC", 18.0, ("Devin Booker", "Derrick Jones Jr."))

    _export(source_root, processed)

    assert [_key(g) for g in _games(processed)] == ["BOS@PHI", "LAC@PHX"]


def test_an_unreadable_existing_file_is_left_alone(roots) -> None:
    source_root, processed = roots
    path = processed / f"cards_sim_detail_{DATE}.json"
    path.write_text("{not json", encoding="utf-8")
    _write_sim(processed, "PHI", "BOS", 20.0, ("Joel Embiid", "Jayson Tatum"))

    assert _export(source_root, processed) == str(path)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_failed_merge_leaves_the_pre_fix_behaviour(roots, monkeypatch) -> None:
    source_root, processed = roots
    _partial_file_then_more_sims(source_root, processed)

    def _boom(**_):
        raise OSError("disk full")

    monkeypatch.setattr(nba, "_merge_missing_cards_sim_detail_games", _boom)

    assert _export(source_root, processed) == str(processed / f"cards_sim_detail_{DATE}.json")
    assert [_key(g) for g in _games(processed)] == ["BOS@PHI"]


def test_the_added_game_reaches_the_projection_index(roots, monkeypatch) -> None:
    """Reachability: the prop projection join's index sees the added game's players (off: absent; on: present)."""
    source_root, processed = roots
    _partial_file_then_more_sims(source_root, processed)

    def _resolve(name: str):
        path = processed / name
        return path if path.exists() else None

    monkeypatch.setattr(nba_projections, "nba_processed_file", _resolve)

    def _indexed_names() -> set[str]:
        index = nba_projections.load_nba_prop_projections(DATE)
        return {entry.player_name for entries in index.by_player.values() for entry in entries}

    assert "Derrick Jones Jr." not in _indexed_names()
    _export(source_root, processed)
    names = _indexed_names()
    assert {"Derrick Jones Jr.", "Devin Booker", "Bam Adebayo", "Joel Embiid"} <= names
