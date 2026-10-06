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
    # season-to-date now reads player_logs.csv (regular season only) from this season's ESPN regular-season start
    # (lane nba-season-phase); the ESPN season table is cached so the slate's phase resolves offline.
    with (tmp_path / cal.PRIOR_FILE).open("w", encoding="utf-8") as fh:
        fh.write("PLAYER_NAME,GAME_DATE,MIN,PTS,REB,AST,FG3M,STL,BLK,TOV\n")
        for d, name, mins, pts, reb, ast in rows:
            fh.write(f"{name},{d},{mins},{pts},{reb},{ast},1,1,0,1\n")
    write_season_types(tmp_path)
    cal._own_rates_cached.cache_clear()
    return tmp_path


ESPN_TYPES = {  # measured 2026-10-05 from ESPN seasons/<yr>/types
    2026: [{"type": 1, "start": "2025-10-01T07:00Z", "end": "2025-10-21T06:59Z"},
           {"type": 2, "start": "2025-10-21T07:00Z", "end": "2026-04-13T06:59Z"},
           {"type": 5, "start": "2026-04-13T07:00Z", "end": "2026-04-18T06:59Z"},
           {"type": 3, "start": "2026-04-18T07:00Z", "end": "2026-06-27T06:59Z"},
           {"type": 4, "start": "2026-06-27T07:00Z", "end": "2026-09-30T06:59Z"}],
    2027: [{"type": 1, "start": "2026-09-30T07:00Z", "end": "2026-10-20T06:59Z"},
           {"type": 2, "start": "2026-10-20T07:00Z", "end": "2027-04-12T06:59Z"},
           {"type": 5, "start": "2027-04-12T07:00Z", "end": "2027-04-17T06:59Z"},
           {"type": 3, "start": "2027-04-17T07:00Z", "end": "2027-06-26T06:59Z"}],
}


def write_season_types(root):
    from syndicate.features.shared import nba_season_phase as ph
    cache = root / "_espn_cache" / "nba"
    cache.mkdir(parents=True, exist_ok=True)
    for yr, rows in ESPN_TYPES.items():
        (cache / f"season_types_{yr}.json").write_text(json.dumps(rows), encoding="utf-8")
    ph._types_cached.cache_clear()


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
    assert off == _sim() and "unset and factor file not enabled" in s_off["reason"]
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
    assert vals == sorted(cal.transform_values([10, 20, 30], -10.0, 2.0))
    # mean-preserving (2026-10-05): the ladder mean is the calibrated mean (20 - 10), not the clip-inflated 13.3
    # the old round_half_up rule produced ([0, 10, 30])
    assert sum(vals) / len(vals) == pytest.approx(10.0)


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


def test_blend_pulls_the_shrunk_mean_toward_the_season_per_game_average(tmp_path):
    root = _write_root(tmp_path, factors={"w": {"pts": 0.2}, "blend": {"pts": 0.25}, "sd_scale": {"pts": 1.0}})
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    a = out["players"]["home"][0]
    own_rate, own_avg = 60 / 90, 60 / 3            # season-to-date: 60 pts in 3 games / 90 minutes
    shrunk = cal.shrink_mean(30.0, 30.0, own_rate, 0.2)
    assert a["pts_mean"] == pytest.approx(0.25 * shrunk + 0.75 * own_avg)
    assert s["b"] == {"pts": 0.25}


def test_blend_alone_is_a_valid_factor_file_and_reaches_the_mean(tmp_path):
    root = _write_root(tmp_path, factors={"blend": {"reb": 0.0}})
    off, on = _sim(), _sim()
    cal.apply_nba_prop_calibration(off, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    cal.apply_nba_prop_calibration(on, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    assert off == _sim()
    assert on["players"]["home"][0]["reb_mean"] == pytest.approx(30 / 3)   # b = 0 -> the season per-game average
    assert on["players"]["away"][0]["reb_mean"] == 1.0                      # < MIN_GAMES: untouched


def test_blend_weight_outside_bounds_is_refused(tmp_path):
    root = _write_root(tmp_path, factors={"blend": {"pts": 1.5}})
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env=ON)
    assert out == _sim() and "outside" in s["reason"]


def test_file_switch_turns_it_on_with_the_env_var_unset(tmp_path):
    off, on = _sim(), _sim()
    cal.apply_nba_prop_calibration(off, league_code="nba", processed_root=_write_root(tmp_path, factors=FACTORS),
                                   build_ladder=_ladder, name_key=_key, env={})
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    s = cal.apply_nba_prop_calibration(on, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    assert off == _sim()                       # file present but not enabled -> off
    assert on != _sim() and s["applied"] and s["switch"] == "factor_file"


def test_env_kill_switch_wins_over_an_enabled_file(tmp_path):
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    for raw in ("0", "false", "off", "no"):
        out = _sim()
        s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key,
                                           env={cal.FLAG: raw})
        assert out == _sim() and s["reason"] == f"{cal.FLAG} off"


def test_enabled_must_be_the_json_literal_true(tmp_path):
    for val in ("true", 1, "yes", None):
        root = _write_root(tmp_path, factors={**FACTORS, "enabled": val})
        out = _sim()
        s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
        assert out == _sim() and "not enabled" in s["reason"]


def test_no_factor_file_with_env_unset_is_off(tmp_path):
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=tmp_path, build_ladder=_ladder, name_key=_key, env={})
    assert out == _sim() and "not enabled" in s["reason"]


def _write_prior(root, rows):
    # player_logs.csv holds every season (current and prior): APPEND to what _write_root wrote
    with (root / cal.PRIOR_FILE).open("a", encoding="utf-8") as fh:
        for d, name, mins, pts in rows:
            fh.write(f"{name},{d},{mins},{pts},4,2,1,1,0,1\n")
    cal._own_rates_cached.cache_clear()


PRIOR = {"enabled": True, "w": {"pts": 0.2}, "blend": {"pts": 0.5}, "sd_scale": {"pts": 1.0},
         "prior_season": {"w": {"pts": 0.3}, "blend": {"pts": 0.7}}}


def test_prior_season_fallback_applies_before_a_players_third_game(tmp_path):
    root = _write_root(tmp_path, factors=PRIOR, history=[])          # no current-season games at all
    # slate 2026-01-10 is in the 2025-26 season, so the PRIOR season is 2024-25
    _write_prior(root, [("2024-11-01", "B. Bench", 20, 10), ("2024-11-03", "B. Bench", 20, 10),
                        ("2024-11-05", "B. Bench", 20, 10),
                        ("2023-11-05", "B. Bench", 40, 99),          # two seasons back: outside the window
                        ("2025-11-05", "B. Bench", 40, 99)])         # current season: not "prior"
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    b = out["players"]["away"][0]
    shrunk = cal.shrink_mean(4.0, 10.0, 30 / 60, 0.3)                 # prior rate 30 pts / 60 min, PRIOR constants
    assert b["pts_mean"] == pytest.approx(0.7 * shrunk + 0.3 * 10.0)  # prior per-game avg 10
    assert b["nba_prop_calibration"]["source"] == "prior_season" and s["players_prior_season"] == 1
    a = out["players"]["home"][0]
    assert a["pts_mean"] == 30.0 and a["nba_prop_calibration"]["source"] is None   # no prior season (rookie): untouched


def test_current_season_wins_once_a_player_has_three_games(tmp_path):
    root = _write_root(tmp_path, factors=PRIOR)                       # A. Player has 3 current-season games
    _write_prior(root, [("2024-11-01", "A. Player", 30, 99)] * 3)
    out = _sim()
    cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    a = out["players"]["home"][0]
    own_rate, own_avg = 60 / 90, 60 / 3
    assert a["pts_mean"] == pytest.approx(0.5 * cal.shrink_mean(30.0, 30.0, own_rate, 0.2) + 0.5 * own_avg)
    assert a["nba_prop_calibration"]["source"] == "season"


def test_prior_season_window_is_the_previous_season_only():
    assert cal.season_start("2026-10-21") == "2026-08-01"   # opening night 2026-27 -> prior window 2025-08-01..2026-08-01


def _sim_file(tmp_path, stamp_block):
    p = tmp_path / "smart_sim_2026-10-05_PHI_NYK.json"
    payload = _sim()
    if stamp_block is not None:
        payload["nba_prop_calibration"] = stamp_block
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_pre_enable_sim_is_stale_once_calibration_is_on(tmp_path):
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    old = _sim_file(tmp_path, None)                                   # written before the enable: no stamp
    assert cal.sim_is_stale(old, league_code="nba", processed_root=root, env={}) is True


def test_sim_stamped_by_the_active_factor_file_is_fresh_and_a_changed_file_makes_it_stale(tmp_path):
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    assert s["factor_sha"] == cal.factor_stamp(root)
    p = tmp_path / "smart_sim_2026-10-05_X_Y.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    assert cal.sim_is_stale(p, league_code="nba", processed_root=root, env={}) is False
    _write_root(tmp_path, factors={**FACTORS, "enabled": True, "sd_scale": {"pts": 1.4}})   # constants changed
    assert cal.sim_is_stale(p, league_code="nba", processed_root=root, env={}) is True


def test_calibrated_sim_is_stale_when_calibration_is_switched_off_and_uncalibrated_is_not(tmp_path):
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    stamped = _sim_file(tmp_path, {"applied": True, "factor_sha": cal.factor_stamp(root)})
    assert cal.sim_is_stale(stamped, league_code="nba", processed_root=root, env={cal.FLAG: "0"}) is True
    plain = _sim_file(tmp_path, None)
    assert cal.sim_is_stale(plain, league_code="nba", processed_root=root, env={cal.FLAG: "0"}) is False


def test_stamp_is_written_even_when_no_player_qualifies_so_it_cannot_loop(tmp_path):
    root = _write_root(tmp_path, factors={"enabled": True, "w": {"pts": 0.2}}, history=[])
    out = _sim()
    s = cal.apply_nba_prop_calibration(out, league_code="nba", processed_root=root, build_ladder=_ladder, name_key=_key, env={})
    assert s["players"] == 0 and out["nba_prop_calibration"]["factor_sha"] == cal.factor_stamp(root)
    p = tmp_path / "smart_sim_2026-10-05_X_Y.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    assert cal.sim_is_stale(p, league_code="nba", processed_root=root, env={}) is False


def test_wnba_sims_are_never_judged_stale(tmp_path):
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    assert cal.sim_is_stale(_sim_file(tmp_path, None), league_code="wnba", processed_root=root, env={}) is False
    assert cal.sim_is_stale(tmp_path / "missing.json", league_code="nba", processed_root=root, env={}) is False


def test_sub_half_unit_shift_reaches_the_ladder_mean():
    vals = [0, 1, 1, 2, 2, 2, 3, 3, 4, 5] * 10                 # n = 100, mean 2.3
    old = [max(0, int(math.floor(v - 0.3 + 0.5))) for v in vals]   # the pre-2026-10-05 rule
    assert old == vals                                         # it moved nothing
    new = cal.shift_values(vals, -0.3)
    assert sum(new) / len(new) == pytest.approx(2.3 - 0.3)
    assert sum(cal.shift_values(vals, 0.37)) / len(vals) == pytest.approx(2.3 + 0.37)


def test_scale_keeps_the_mean_and_widens_by_k():
    import statistics
    vals = [8, 10, 12, 14, 15, 17, 18, 20, 22, 25, 27, 30] * 25
    for k in (1.25, 1.5, 0.9):
        out = cal.scale_values(vals, k)
        assert sum(out) / len(out) == pytest.approx(sum(vals) / len(vals), abs=1 / len(vals))
        assert statistics.pstdev(out) == pytest.approx(k * statistics.pstdev(vals), rel=0.02)


def test_transform_is_deterministic_and_carries_the_shift_exactly():
    vals = list(range(0, 12)) * 40
    a = cal.transform_values(vals, 0.42, 1.25)
    assert a == cal.transform_values(vals, 0.42, 1.25)
    assert sum(a) / len(a) == pytest.approx(sum(vals) / len(vals) + 0.42, abs=1.5 / len(vals))


def test_stamp_includes_the_transform_version_so_old_code_sims_go_stale(tmp_path, monkeypatch):
    root = _write_root(tmp_path, factors={**FACTORS, "enabled": True})
    new = cal.factor_stamp(root)
    monkeypatch.setattr(cal, "TRANSFORM_VERSION", "1")
    assert cal.factor_stamp(root) != new


def test_book_blend_endpoints_and_logit_symmetry():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("fitcal", Path(__file__).resolve().parents[1] / "scripts" / "fit_nba_prop_calibration.py")
    fitcal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fitcal)
    for space in ("logit", "prob"):
        assert fitcal.blend_p(0.6, 0.3, 0.0, space) == pytest.approx(0.6, abs=1e-6)   # w = 0 is the book
        assert fitcal.blend_p(0.6, 0.3, 1.0, space) == pytest.approx(0.3, abs=1e-6)   # w = 1 is the model
    assert fitcal.blend_p(0.5, 0.8, 0.5) == pytest.approx(1 - fitcal.blend_p(0.5, 0.2, 0.5))


# --- served probability: blend toward the de-vigged book -------------------------------------------------------------

def _write_blend(tmp_path, doc):
    (tmp_path / cal.BOOK_BLEND_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_book_blend_reachability_off_differs_from_on(tmp_path):
    root = _write_blend(tmp_path, {"enabled": True, "space": "logit", "w": {"pts": 0.0, "reb": 0.1}})
    on, meta_on = cal.served_prop_probability(0.70, 0.50, "pts", processed_root=root, env={})
    off, meta_off = cal.served_prop_probability(0.70, 0.50, "pts", processed_root=root,
                                                env={cal.BOOK_BLEND_FLAG: "0"})
    assert on != off
    assert on == pytest.approx(0.50) and meta_on["book_blend"] == "applied" and meta_on["p_model_raw"] == 0.7
    assert off == 0.70 and "off" in meta_off["book_blend"]


def test_book_blend_weight_interpolates_in_logit_space(tmp_path):
    root = _write_blend(tmp_path, {"enabled": True, "w": {"reb": 0.1}})
    p, meta = cal.served_prop_probability(0.70, 0.50, "REB", processed_root=root, env={})
    assert p == pytest.approx(1 / (1 + math.exp(-0.1 * math.log(0.7 / 0.3))))
    assert meta["book_blend_w"] == 0.1 and meta["p_book"] == 0.5


def test_book_blend_falls_back_to_model_with_a_reason(tmp_path):
    p, meta = cal.served_prop_probability(0.6, 0.5, "pts", processed_root=tmp_path, env={})
    assert p == 0.6 and meta["book_blend"] == "book-blend file absent"
    root = _write_blend(tmp_path, {"enabled": False, "w": {"pts": 0.0}})
    assert cal.served_prop_probability(0.6, 0.5, "pts", processed_root=root, env={})[1]["book_blend"] == "book-blend file not enabled"
    root = _write_blend(tmp_path, {"enabled": True, "w": {"pts": 1.5}})
    assert "outside" in cal.served_prop_probability(0.6, 0.5, "pts", processed_root=root, env={})[1]["book_blend"]
    root = _write_blend(tmp_path, {"enabled": True, "w": {"pts": 0.0}})
    assert cal.served_prop_probability(0.6, None, "pts", processed_root=root, env={}) == (0.6, {"p_model_raw": 0.6, "book_blend": "no two-sided book price for this line"})
    assert cal.served_prop_probability(0.6, 0.5, "stl", processed_root=root, env={})[1]["book_blend"] == "no weight for 'stl'"
    assert cal.served_prop_probability(None, 0.5, "pts", processed_root=root, env={})[0] is None


def test_preseason_or_unknown_slate_never_uses_season_to_date(tmp_path, monkeypatch):
    """Phase guard: a preseason slate (2026-10-05) gets NO own rates even with preseason-dated rows on file, and an
    unknown phase (no season table) is treated the same way -- never as regular season."""
    root = _write_root(tmp_path, history=[("2026-10-02", "A. Player", 30, 20, 10, 5)] * 3)
    rates, why = cal.own_rates(root, "2026-10-05", _key)
    assert rates == {} and "preseason" in why
    rates, why = cal.own_rates(root, "2026-10-25", _key)          # regular season, but those rows are preseason-dated
    assert rates == {} and "regular-season games 2026-10-20" in why
    import shutil
    from syndicate.features.shared import nba_season_phase as ph
    monkeypatch.setattr(ph, "_fetch_types", lambda year, timeout=10.0: None)   # offline: the table cannot be fetched
    shutil.rmtree(root / "_espn_cache")
    ph._types_cached.cache_clear()
    rates, why = cal.own_rates(root, "2026-01-10", _key)
    assert rates == {} and "unknown" in why

