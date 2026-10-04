"""nba_prop_calibration: reachability first (off != on), then the estimator, the guards and the ladders."""
from __future__ import annotations

import copy
import json
import math
from collections import Counter

import pytest

from syndicate.features.shared import nba_prop_calibration as cal

ON = {cal.FLAG: "1"}
FACTORS = {"w": {"pts": 0.2, "reb": 0.3, "ast": 0.3}, "sd_scale": {"pts": 1.5, "reb": 1.25, "pra": 1.5}}


def _ladder(values):
    c = Counter(values)
    return {"distribution": {str(k): v for k, v in sorted(c.items())}, "simCount": len(values),
            "mean": sum(values) / len(values)}


def _key(name):
    return str(name or "").strip().upper()


def _write_root(tmp_path, factors=FACTORS, history=None):
    (tmp_path / cal.FACTOR_FILE).write_text(json.dumps(factors), encoding="utf-8")
    rows = history if history is not None else [
        # 3 season games for A. Player before 2026-01-10: 60 pts / 90 min -> 0.6667 pts/min, reb 30/90, ast 15/90
        ("2026-01-01", "A. Player", 30, 20, 10, 5), ("2026-01-03", "A. Player", 30, 20, 10, 5),
        ("2026-01-05", "A. Player", 30, 20, 10, 5),
        ("2025-05-01", "A. Player", 40, 99, 99, 99),   # previous season: must be ignored
        ("2026-01-10", "A. Player", 40, 99, 99, 99),   # the slate date itself: must be ignored
        ("2026-01-05", "B. Bench", 10, 2, 1, 0),        # only 1 game: no shrink
    ]
    with (tmp_path / cal.HISTORY_FILE).open("w", encoding="utf-8") as fh:
        fh.write("PLAYER_NAME,date,MIN,PTS,REB,AST,FG3M,STL,BLK,TOV\n")
        for d, name, mins, pts, reb, ast in rows:
            fh.write(f"{name},{d},{mins},{pts},{reb},{ast},1,1,0,1\n")
    cal._own_rates_cached.cache_clear()
    return tmp_path


def _sim():
    def player(name, mins, pts, reb, ast):
        return {"player_name": name, "min_mean": mins, "pts_mean": pts, "reb_mean": reb, "ast_mean": ast,
                "pra_mean": pts + reb + ast, "pts_sd": 6.0, "reb_sd": 3.0, "ast_sd": 2.0, "pra_sd": 8.0,
                "prop_ladders": {"pts": _ladder([10, 20, 30]), "pra": _ladder([20, 30, 40])}}
    return {"date": "2026-01-10", "players": {"home": [player("A. Player", 30.0, 30.0, 6.0, 3.0)],
                                              "away": [player("B. Bench", 10.0, 4.0, 1.0, 1.0)]}}


def test_reachability_flag_off_differs_from_flag_on(tmp_path):
    root = _write_root(tmp_path)
    off, on = _sim(), _sim()
    s_off = cal.apply_nba_prop_calibration(off, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    s_on = cal.apply_nba_prop_calibration(on, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    assert off == _sim() and s_off["reason"] == f"{cal.FLAG} off"
    assert on != off and s_on["applied"] and s_on["players_rate_shrunk"] == 1


def test_other_league_is_untouched(tmp_path):
    root = _write_root(tmp_path)
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="wnba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    assert out == _sim() and s["reason"] == "not nba"


def test_rate_shrink_uses_season_to_date_own_rate_strictly_before_the_slate(tmp_path):
    root = _write_root(tmp_path)
    out = _sim()
    cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    a = out["players"]["home"][0]
    own_pts = 60 / 90  # previous-season and same-date rows excluded
    assert a["pts_mean"] == pytest.approx(30 * (own_pts + 0.2 * (30 / 30 - own_pts)))
    dp, dr, da = a["pts_mean"] - 30.0, a["reb_mean"] - 6.0, a["ast_mean"] - 3.0
    assert a["pra_mean"] == pytest.approx(39.0 + dp + dr + da)
    assert a["pts_sd"] == pytest.approx(9.0) and a["reb_sd"] == pytest.approx(3.75) and a["ast_sd"] == 2.0
    assert a["pra_sd"] == pytest.approx(12.0)


def test_player_below_min_games_keeps_sim_mean_but_width_is_still_scaled(tmp_path):
    root = _write_root(tmp_path)
    out = _sim()
    cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    b = out["players"]["away"][0]
    assert b["pts_mean"] == 4.0 and b["pts_sd"] == pytest.approx(9.0)
    assert b["nba_prop_calibration"]["mean_delta"] == {}


def test_ladders_are_shifted_then_dilated(tmp_path):
    root = _write_root(tmp_path, factors={"w": {"pts": 0.0}, "sd_scale": {"pts": 2.0}})
    out = _sim()
    cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    a = out["players"]["home"][0]
    shift = a["pts_mean"] - 30.0  # w = 0 -> mean = minutes * own rate = 20
    assert shift == pytest.approx(-10.0)
    vals = sorted(int(k) for k, c in a["prop_ladders"]["pts"]["distribution"].items() for _ in range(c))
    assert vals == cal.transform_values([10, 20, 30], -10.0, 2.0) == [0, 10, 30]


def test_missing_or_invalid_factor_file_leaves_result_untouched_with_a_reason(tmp_path):
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=tmp_path, build_ladder=_ladder, name_key=_key, env=ON)
    assert out == _sim() and s["reason"].startswith("factor file absent")
    root = _write_root(tmp_path, factors={"sd_scale": {"pts": 9.0}})
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    assert out == _sim() and "outside" in s["reason"]


def test_never_raises_on_a_malformed_result(tmp_path):
    root = _write_root(tmp_path)
    bad = {"date": "2026-01-10", "players": {"home": [{"player_name": "A. Player", "min_mean": "x", "pts_mean": None}]}}
    s = cal.apply_nba_prop_calibration(copy.deepcopy(bad), league_code="nba", processed_root=root, build_ladder=_ladder,
                                       name_key=_key, env=ON)
    assert "reason" in s


def test_combo_scale_is_the_edges_independence_sigma():
    k = cal.combo_scale(("pts", "reb"), {"pts": 6.0, "reb": 3.0}, {"pts": 1.5, "reb": 1.0})
    assert k == pytest.approx(math.sqrt((9.0 ** 2 + 3.0 ** 2) / (6.0 ** 2 + 3.0 ** 2)))


def test_season_start_spans_preseason_through_june():
    assert cal.season_start("2026-01-10") == "2025-08-01"
    assert cal.season_start("2026-06-10") == "2025-08-01"
    assert cal.season_start("2026-10-21") == "2026-08-01"
