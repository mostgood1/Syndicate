"""Test C late-game cells: the pre-registered window, fees and verdict rules (findings section 11)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("inplay_late_cells", ROOT / "scripts" / "inplay_late_cells.py")
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)


def test_clock_parses_mmss_and_seconds():
    assert lc.clock_s("6:00") == 360 and lc.clock_s("10:00") == 600 and lc.clock_s("45.3") == 45.3
    assert lc.clock_s("") is None and lc.clock_s("x:y") is None


def test_window_is_the_last_ten_game_minutes_and_overtime():
    nhl = [(0.0, 3, 601.0), (10.0, 3, 600.0), (20.0, 4, 300.0)]
    assert not lc.in_window(nhl, 5.0, "nhl") and lc.in_window(nhl, 10.0, "nhl") and lc.in_window(nhl, 25.0, "nhl")
    assert not lc.in_window(nhl, -1.0, "nhl")  # before the first ESPN row
    nba = [(0.0, 4, 361.0), (10.0, 4, 360.0)]
    assert not lc.in_window(nba, 5.0, "nba") and lc.in_window(nba, 10.0, "nba")
    assert lc.in_window([(0.0, 4, 480.0)], 1.0, "ncaaf") and not lc.in_window([(0.0, 3, 10.0)], 1.0, "nfl")


def test_fees():
    assert abs(lc.fee_formula(0.9) - 0.0063) < 1e-9
    assert lc.fee_one_contract(0.9) == 0.01 and lc.fee_one_contract(0.5) == 0.02


def _rows(means_by_sport):
    rows = []
    for sport, means in means_by_sport.items():
        for i, m in enumerate(means):
            rows.append({"game": f"{sport}{i}", "sport": sport, "date": f"d{i:03d}", "v": m})
    return rows


def test_verdicts_follow_the_pre_registration():
    assert lc.verdict(lc.summarise(_rows({"nba": [0.05] * 59}), "v")).startswith("INSUFFICIENT")
    go = lc.summarise(_rows({"nba": [0.04, 0.06] * 15, "nhl": [0.03, 0.05] * 15}), "v")
    assert lc.verdict(go) == "GO"
    one_sport = lc.summarise(_rows({"nba": [0.04, 0.06] * 30, "nhl": [-0.01] * 5}), "v")
    assert lc.verdict(one_sport).startswith("NO-GO")  # only one sport with >= 20 games
    kill = lc.summarise(_rows({"nba": [-0.04, -0.06] * 30}), "v")
    assert lc.verdict(kill).startswith("KILL")
    tail = lc.summarise(_rows({"nba": [0.05] * 29 + [-0.9], "nhl": [0.05] * 30}), "v")
    assert "TAIL FLAG" in lc.verdict(tail, tail_check=True)
