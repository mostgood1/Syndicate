"""Per-cell calibrated model probability (todo #847, lane cell-calibration-847).

Pins the transform, the table rails, the fit floors, the pooling, and -- for each of the four uses -- that the
switch OFF serves exactly today's numbers and the switch ON reaches the consumer (`off != on`, the model engine
standard's reachability rule)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import cell_calibration as cc
from syndicate.features.shared import daily_optimizer as opt
from syndicate.features.shared import optimizer_overlay as ov

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
SWITCHES = list(cc.SWITCHES.values())


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for name in SWITCHES + ["SYNDICATE_OPTIMIZER_OVERLAY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    cc.reset_cache()
    ov.reset_cache()
    yield
    cc.reset_cache()
    ov.reset_cache()


def _table(cells: dict[str, float], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {"source": cc.SOURCE, "version": cc.VERSION, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (now + timedelta(hours=cc.TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cells": {c: {"k": k, "games": 80, "dates": 9, "rows": 900} for c, k in cells.items()}}


def _write_table(tmp_path, cells):
    path = tmp_path / cc.TABLE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_table(cells)), encoding="utf-8")
    cc.reset_cache()
    return path


# --------------------------------------------------------------------- transform


def test_k_one_is_the_raw_model_and_k_small_moves_toward_the_fair_without_flipping():
    assert cc.calibrate(0.70, 0.50, 1.0) == pytest.approx(0.70)
    half = cc.calibrate(0.70, 0.50, 0.5)
    assert 0.50 < half < 0.70
    assert cc.calibrate(0.30, 0.55, 0.25) < 0.55  # stays on the model's side of the fair
    assert cc.calibrate(0.30, 0.55, 0.25) > 0.30


def test_the_transform_is_the_logit_form():
    p, f, k = 0.8, 0.45, 0.3
    lf = math.log(f / (1 - f))
    expected = 1 / (1 + math.exp(-(lf + k * (math.log(p / (1 - p)) - lf))))
    assert cc.calibrate(p, f, k) == pytest.approx(expected)


@pytest.mark.parametrize("p,f", [(None, 0.5), (0.5, None), (0.0, 0.5), (1.0, 0.5), (0.5, 1.0), ("x", 0.5)])
def test_unusable_inputs_return_none(p, f):
    assert cc.calibrate(p, f, 0.5) is None


# --------------------------------------------------------------------- table rails


def test_validate_table_accepts_a_good_table_and_rejects_every_broken_rail():
    good = _table({"ncaab|spreads|full|live": 0.3}, now=NOW)
    assert cc.validate_table(good, now=NOW) == ({"ncaab|spreads|full|live": 0.3}, "ok")
    assert cc.validate_table(good, now=NOW + timedelta(hours=cc.TTL_HOURS + 1))[1] == "expired"
    assert cc.validate_table({**good, "source": "x"}, now=NOW)[1] == "unknown_source"
    for k in (0.05, 1.2, True):
        bad = _table({"ncaab|spreads|full|live": 0.3}, now=NOW)
        bad["cells"]["ncaab|spreads|full|live"]["k"] = k
        assert cc.validate_table(bad, now=NOW)[1] == "k_out_of_rails"
    thin = _table({"ncaab|spreads|full|live": 0.3}, now=NOW)
    thin["cells"]["ncaab|spreads|full|live"]["games"] = 10
    assert cc.validate_table(thin, now=NOW)[1] == "below_sample_floor"


def test_an_absent_table_serves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(cc.SWITCHES[cc.USE_RAIL], "on")
    assert cc.active_table() is None
    assert cc.stamp({"sport": "ncaab"}, 0.7, 0.5, use=cc.USE_RAIL, cell="ncaab|spreads|full|live") is None


# --------------------------------------------------------------------- fit


def test_fit_floors_drop_pre_fix_nba_and_pre_816_college_totals_only():
    assert cc.fit_floor("nba|totals|full|live") == "2026-11-19"
    assert cc.fit_floor("ncaab|totals|full|live") == "2026-11-17"
    assert cc.fit_floor("wncaab|totals_alt|h1|pregame") == "2026-11-17"
    assert cc.fit_floor("ncaab|spreads|full|live") is None
    games = [{"date": "2026-11-18", "key": "a", "cal": {"nba|totals|full|live": [3, 0.1, 0.01],
                                                       "nhl|sog|full|pregame": [3, 0.1, 0.01]}},
             {"date": "2026-11-19", "key": "b", "cal": {"nba|totals|full|live": [3, 0.1, 0.01]}}]
    out = cc.apply_floors(games)
    assert out[0]["cal"] == {"nhl|sog|full|pregame": [3, 0.1, 0.01]}
    assert out[1]["cal"] == {"nba|totals|full|live": [3, 0.1, 0.01]}


def _result(cell, w, ci, games=80):
    return {"cell": cell, "w": w, "ci95": ci, "games": games, "dates": 9, "rows": 900}


def test_pool_shrinks_toward_the_group_and_carries_the_group_means_variance():
    a, b = "x|spreads|full|live", "x|spreads|full|pregame"
    calib = [_result(a, 0.10, [-0.10, 0.30]), _result(b, 0.60, [0.40, 0.80])]
    sums = {a: (10.0, 1.0), b: (10.0, 6.0)}
    pooled = cc.pool(calib, sums)
    assert pooled[a]["group_w"] == pytest.approx(0.35)
    # Disagreeing cells: tau2 > 0, so each moves part of the way to the group mean.
    assert pooled[a]["tau2"] > 0
    assert 0.10 < pooled[a]["post_mean"] < 0.35 and 0.35 < pooled[b]["post_mean"] < 0.60
    se = 0.4 / (2 * 1.96)
    assert pooled[a]["post_sd"] > math.sqrt(1 / (1 / se**2 + 1 / pooled[a]["tau2"]))  # the Morris term is added


def test_pool_at_tau2_zero_serves_the_group_mean_with_its_own_variance():
    a, b = "x|totals|full|live", "x|totals|full|pregame"
    calib = [_result(a, 0.30, [0.10, 0.50]), _result(b, 0.31, [0.11, 0.51])]
    pooled = cc.pool(calib, {a: (10.0, 3.0), b: (10.0, 3.1)})
    se = 0.4 / (2 * 1.96)
    assert pooled[a]["tau2"] == 0.0
    assert pooled[a]["post_mean"] == pytest.approx(0.305)
    assert pooled[a]["post_sd"] == pytest.approx(math.sqrt(1 / (2 / se**2)))


def test_a_lone_cell_is_not_pooled():
    a = "y|h2h|full|live"
    pooled = cc.pool([_result(a, 0.2, [0.0, 0.4])], {a: (5.0, 1.0)})
    assert pooled[a]["post_mean"] == pytest.approx(0.2) and pooled[a]["pooled"] is False


def test_served_k_is_the_ci_upper_clipped_and_only_on_an_overconfident_verdict():
    entry = {"post_mean": 0.2, "post_sd": 0.05}
    assert cc.served_k(entry, "overconfident") == pytest.approx(0.298)
    assert cc.served_k(entry, "not_proven") is None
    assert cc.served_k({"post_mean": -0.5, "post_sd": 0.05}, "overconfident") == cc.K_FLOOR  # never zeroed
    assert cc.served_k({"post_mean": 0.9, "post_sd": 0.2}, "overconfident") is None  # k >= 1 is the raw model


def _synthetic_games(cell, n_games, w_true, start="2026-10-25", rows=30, seed=7):
    import random

    rng = random.Random(seed)
    games = []
    day0 = datetime.fromisoformat(start)
    for i in range(n_games):
        sdd = sdr = 0.0
        for _ in range(rows):
            d = rng.uniform(-0.15, 0.15)
            pm = 0.5
            y = 1 if rng.random() < pm + w_true * d else 0
            sdd += d * d
            sdr += d * (y - pm)
        games.append({"date": (day0 + timedelta(days=i % 20)).date().isoformat(), "key": f"g{i}",
                      "cal": {cell: [rows, sdd, sdr]}})
    return games


def test_fit_table_serves_an_overconfident_cell_and_never_a_floored_nba_one():
    games = _synthetic_games("ncaab|spreads|full|live", 160, 0.1) + _synthetic_games(
        "nba|spreads|full|live", 160, 0.1, seed=9)
    table = cc.fit_table(games, now=NOW, today="2026-11-18", resamples=300)
    assert "ncaab|spreads|full|live" in table["cells"]
    assert not any(c.startswith("nba|") for c in table["cells"])
    k = table["cells"]["ncaab|spreads|full|live"]["k"]
    assert cc.K_FLOOR <= k < 1.0
    assert cc.validate_table(table, now=NOW)[1] == "ok"


def test_held_out_brier_is_the_linear_twin_from_the_sums():
    games = [{"cal": {"c|m|full|live": [10, 2.0, 0.5]}}]
    out = cc.held_out_brier(games, {"c|m|full|live": 0.5})
    assert out["c|m|full|live"] == [[10.0, (0.25 - 1) * 2.0 - 2 * (0.5 - 1) * 0.5]]


# --------------------------------------------------------------------- (a) the rail's flag test


def _live_spread_row(**extra):
    row = {"kind": "game", "sport": "ncaab", "market": "spreads", "segment": "full", "side": "home",
           "game_state": "live", "quote": {"fair_probability": 0.50},
           "projection": {"live_model_prob_over": 0.70}, "live_gameline": {"total_mean": 140.0},
           "game": {"state": "live", "home_score": 40, "away_score": 38}}
    row.update(extra)
    return row


def test_a_rail_off_is_todays_row_and_on_stamps_the_calibrated_probability(tmp_path, monkeypatch):
    from syndicate.features.shared.layer2_board import _live_projection_columns

    _write_table(tmp_path, {"ncaab|spreads|full|live": 0.3})
    off = _live_projection_columns(_live_spread_row())
    assert off["live_model_probability"] == 0.70
    assert not any(key.startswith("live_cal") or key.endswith("_cal") for key in off)

    monkeypatch.setenv(cc.SWITCHES[cc.USE_RAIL], "on")
    cc.reset_cache()
    on = _live_projection_columns(_live_spread_row())
    assert on["live_model_probability"] == 0.70  # the raw number is unchanged
    assert on["live_model_probability_cal"] == pytest.approx(cc.calibrate(0.70, 0.50, 0.3), abs=1e-6)
    assert on["live_cal_k"] == 0.3 and on["live_cal_cell"] == "ncaab|spreads|full|live"
    assert {k: v for k, v in on.items() if not k.startswith("live_cal") and k != "live_model_probability_cal"} == off


def test_a_rail_unserved_cell_stays_raw_with_the_switch_on(tmp_path, monkeypatch):
    from syndicate.features.shared.layer2_board import _live_projection_columns

    _write_table(tmp_path, {"nhl|spreads|full|live": 0.3})
    monkeypatch.setenv(cc.SWITCHES[cc.USE_RAIL], "on")
    on = _live_projection_columns(_live_spread_row())
    assert "live_model_probability_cal" not in on


def test_a_rail_never_calibrates_a_live_probability_that_d_already_calibrated(tmp_path, monkeypatch):
    from syndicate.features.shared.layer2_board import _live_projection_columns

    _write_table(tmp_path, {"ncaab|spreads|full|live": 0.3})
    monkeypatch.setenv(cc.SWITCHES[cc.USE_RAIL], "on")
    row = _live_spread_row(projection={"live_model_prob_over": 0.70, cc.LIVE_PROB_MARKER: {"k": 0.3}})
    assert "live_model_probability_cal" not in _live_projection_columns(row)


def test_a_rail_fast_poll_rows_carry_the_calibrated_fields():
    from syndicate.features.shared.live_rail_rows import ROW_FIELDS, trim_row

    for key in ("live_model_probability_cal", "live_cal_k", "live_cal_cell"):
        assert key in ROW_FIELDS
    assert trim_row({"live_model_probability_cal": 0.55, "kind": "game"})["live_model_probability_cal"] == 0.55


def test_a_the_page_flag_test_reads_the_calibrated_number():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "syndicate/templates/intelligence.html").read_text(encoding="utf-8")
    body = html[html.index("function liveRowGap(item)"):html.index("function liveRowFreshEdge(")]
    assert "item.live_model_probability_cal" in body
    assert "gap: (calibrated - fair) * 100" in body


# --------------------------------------------------------------------- (b) the board's shown model numbers


def _board_row():
    return {"kind": "game", "sport": "ncaab", "market": "spreads", "segment": "full", "side": "home",
            "game_state": "live", "projection": {"model_prob_over": 0.66, "side": "home"}}


def test_b_display_off_is_todays_columns_and_on_adds_the_calibrated_pair(tmp_path, monkeypatch):
    from syndicate.features.shared.layer2_board import _layer2_board_columns

    _write_table(tmp_path, {"ncaab|spreads|full|live": 0.4})
    quote = {"fair_probability": 0.52, "price": -110}
    off = _layer2_board_columns(_board_row(), quote, {})
    assert off["confidence"] == pytest.approx(0.66)
    assert "model_probability_cal" not in off and "model_ev_cal_pct" not in off

    monkeypatch.setenv(cc.SWITCHES[cc.USE_DISPLAY], "on")
    cc.reset_cache()
    on = _layer2_board_columns(_board_row(), quote, {})
    p = cc.calibrate(0.66, 0.52, 0.4)
    assert on["confidence"] == off["confidence"]  # the raw sim column value is untouched
    assert on["model_probability_cal"] == pytest.approx(p, abs=1e-6)
    assert on["model_ev_cal_pct"] == pytest.approx(100 * (p * (1 + 100 / 110) - 1), abs=0.01)
    assert on["cal_k"] == 0.4 and on["cal_cell"] == "ncaab|spreads|full|live"
    assert "ev_vs_fair_pct" not in on or on.get("ev_vs_fair_pct") == off.get("ev_vs_fair_pct")


# --------------------------------------------------------------------- (c) rank and stake below the floor


def _write_overlay(tmp_path, cell, factor=0.5):
    now = datetime.now(timezone.utc)
    payload = {"source": opt.SOURCE, "version": opt.OPTIMIZER_VERSION,
               "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "expires_at": (now + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "edge_shrink": {cell: {"factor": factor, "w": 0.1, "ci95": [0, 0.2], "games": 80, "dates": 9}},
               "stake_scale": {}}
    path = tmp_path / opt.OVERLAY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    ov.reset_cache()


def test_c_rank_stake_off_keeps_the_half_floor_and_on_goes_to_the_cells_k(tmp_path, monkeypatch):
    cell = "ncaab|spreads|full|live"
    _write_overlay(tmp_path, cell, 0.5)
    _write_table(tmp_path, {cell: 0.22, "nhl|sog|full|pregame": 0.8})
    row = _board_row()
    assert ov.factor_for_row(row) == 0.5

    monkeypatch.setenv(cc.SWITCHES[cc.USE_RANK_STAKE], "on")
    cc.reset_cache()
    ov.reset_cache()
    assert ov.factor_for_row(row) == pytest.approx(0.22)
    # A cell whose k is at or above the floor keeps the optimizer's own factor.
    assert cc.rank_stake_factor("nhl|sog|full|pregame") is None


def test_c_the_overlay_kill_switch_still_kills_it(tmp_path, monkeypatch):
    cell = "ncaab|spreads|full|live"
    _write_overlay(tmp_path, cell, 0.5)
    _write_table(tmp_path, {cell: 0.22})
    monkeypatch.setenv(cc.SWITCHES[cc.USE_RANK_STAKE], "on")
    monkeypatch.setenv("SYNDICATE_OPTIMIZER_OVERLAY", "off")
    assert ov.factor_for_row(_board_row()) == 1.0


def test_c_the_factor_never_drops_below_k_floor():
    assert cc.rank_stake_factor("x|y|full|live", table={"x|y|full|live": 0.10}) is None  # switch off
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(cc.SWITCHES[cc.USE_RANK_STAKE], "on")
        assert cc.rank_stake_factor("x|y|full|live", table={"x|y|full|live": 0.10}) == cc.K_FLOOR


# --------------------------------------------------------------------- (d) the shared live probability


def test_d_live_probability_off_is_none_and_on_calibrates_a_served_cell(monkeypatch):
    table = {"nhl|spreads|full|live": 0.3, "ncaab|totals|full|live": 0.3}
    assert cc.live_probability("nhl", "spreads", "full", 0.7, 0.5, table=table) is None
    monkeypatch.setenv(cc.SWITCHES[cc.USE_LIVE_PROB], "on")
    p, meta = cc.live_probability("nhl", "spreads", "game", 0.7, 0.5, table=table)
    assert p == pytest.approx(cc.calibrate(0.7, 0.5, 0.3)) and meta["cell"] == "nhl|spreads|full|live"
    # #816 owns college totals: never a second calibration on top of it.
    assert cc.live_probability("ncaab", "totals", "full", 0.7, 0.5, table=table) is None
    assert cc.live_probability("nhl", "totals", "full", 0.7, 0.5, table=table) is None  # unserved cell


def test_every_switch_is_absent_off():
    for use in cc.SWITCHES:
        assert cc.enabled(use, env={}) is False
        assert cc.enabled(use, env={cc.SWITCHES[use]: "off"}) is False
        assert cc.enabled(use, env={cc.SWITCHES[use]: "on"}) is True


# --------------------------------------------------------------------- the cron writes the table


from tests.test_daily_optimizer import cron  # noqa: E402,F401  (the optimizer's own cron fixture)


def test_the_cron_writes_the_table_beside_the_optimizer_and_not_when_it_is_off(cron):
    pms, root = cron
    assert pms.main(["--weekly", "off", "--sports", "mlb", "--resamples", "50"]) == 0
    table = json.loads((root / cc.TABLE_PATH).read_text(encoding="utf-8"))
    assert table["source"] == cc.SOURCE and table["rule"]["k_floor"] == cc.K_FLOOR
    assert table["window"]["games"] == 1  # the same window of the same state the optimizer fitted
    assert cc.validate_table(table)[1] == "ok"
    (root / cc.TABLE_PATH).unlink()
    assert pms.main(["--weekly", "off", "--sports", "mlb", "--optimizer", "off", "--resamples", "50"]) == 0
    assert not (root / cc.TABLE_PATH).exists()


# --------------------------------------------------------------------- (d) wired into the live join


DIST = {"220": 40, "226": 60, "234": 60, "240": 40}


def _dist_kw(**extra):
    kw = {"dist": DIST, "line": 229.5, "side": "over", "market": "totals", "market_prob": 0.40, "sims": 2000,
          "sport": "nhl"}
    kw.update(extra)
    return kw


def test_d_the_distribution_pricer_off_is_todays_verdict_and_on_calibrates_it(tmp_path, monkeypatch):
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    _write_table(tmp_path, {"nhl|totals|full|live": 0.3})
    off = price_distribution_market(**_dist_kw(live_cell=("nhl", "totals", "full")))
    assert off == price_distribution_market(**_dist_kw())  # off: the cell argument changes nothing
    assert off["live_cell_calibration"] is None

    monkeypatch.setenv(cc.SWITCHES[cc.USE_LIVE_PROB], "on")
    cc.reset_cache()
    on = price_distribution_market(**_dist_kw(live_cell=("nhl", "totals", "full")))
    raw = off["model_prob"]
    assert on["model_prob_cell_uncalibrated"] == pytest.approx(raw)
    assert on["model_prob"] == pytest.approx(cc.calibrate(raw, 0.40, 0.3))
    assert abs(on["edge_pp"]) < abs(off["edge_pp"])
    assert on["live_cell_calibration"]["cell"] == "nhl|totals|full|live" and on["live_cell_calibration"]["k"] == 0.3
    # The gate's error shrinks with the edge (sim error times the slope, plus the fit's own error).
    assert on["prob_std_err"] < off["prob_std_err"]


def test_d_college_totals_stay_with_816(tmp_path, monkeypatch):
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    _write_table(tmp_path, {"ncaab|totals|full|live": 0.3})
    monkeypatch.setenv(cc.SWITCHES[cc.USE_LIVE_PROB], "on")
    v = price_distribution_market(**_dist_kw(sport="ncaab", live_cell=("ncaab", "totals", "full")))
    assert v["live_cell_calibration"] is None


def test_d_the_moneyline_pricer_off_is_todays_verdict_and_on_calibrates_it(tmp_path, monkeypatch):
    from syndicate.features.shared.live_gameline_join import price_moneyline

    _write_table(tmp_path, {"soccer|h2h|full|live": 0.2})
    kw = {"model_prob": 0.80, "market_prob": 0.55, "sims": 2000, "sport": "soccer",
          "live_cell": ("soccer", "h2h", "full_game")}
    off = price_moneyline(**kw)
    assert "live_cell_calibration" not in off
    monkeypatch.setenv(cc.SWITCHES[cc.USE_LIVE_PROB], "on")
    cc.reset_cache()
    on = price_moneyline(**kw)
    assert on["model_prob"] == pytest.approx(cc.calibrate(off["model_prob"], 0.55, 0.2))
    assert on["edge_pp"] < off["edge_pp"] and on["live_cell_calibration"]["cell"] == "soccer|h2h|full|live"


def test_d_apply_verdict_carries_the_stamp_so_a_never_applies_twice(tmp_path, monkeypatch):
    from syndicate.features.shared.layer2_board import _live_projection_columns
    from syndicate.features.shared.live_gameline_join import _apply_verdict, new_coverage, price_distribution_market

    _write_table(tmp_path, {"nhl|totals|full|live": 0.3})
    monkeypatch.setenv(cc.SWITCHES[cc.USE_LIVE_PROB], "on")
    monkeypatch.setenv(cc.SWITCHES[cc.USE_RAIL], "on")
    verdict = price_distribution_market(**_dist_kw(live_cell=("nhl", "totals", "full")))
    row = {"kind": "game", "sport": "nhl", "market": "totals", "segment": "full", "side": "over",
           "game_state": "live", "quote": {"fair_probability": 0.40}}
    hit = {"sport": "nhl", "sims_run": 2000}
    _apply_verdict(row, {}, verdict, hit, new_coverage(), live_projected=verdict.get("model_prob"), sport="nhl")
    assert row["projection"][cc.LIVE_PROB_MARKER]["k"] == 0.3
    cols = _live_projection_columns(row)
    assert cols["live_model_probability"] == pytest.approx(verdict["model_prob"])
    assert "live_model_probability_cal" not in cols


def test_hf_grades_a_frozen_tables_k_exactly_without_refitting():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "fit_cell_calibration", Path(__file__).resolve().parents[1] / "scripts" / "fit_cell_calibration.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    state = {"games": {"g1": {"date": "2026-11-20", "cal": {"x|m|full|live": [10, 2.0, 0.1]}},
                       "g2": {"date": "2026-11-21", "cal": {"x|m|full|live": [10, 2.0, 0.2]}},
                       "g3": {"date": "2026-11-12", "cal": {"x|m|full|live": [10, 2.0, 0.2]}}}}
    frozen = {"cells": {"x|m|full|live": {"k": 0.5}}, "diagnostics": []}
    out = mod.grade(state, frozen, "2026-11-19", "2026-11-25")
    assert list(out) == ["held_out", "served"]
    assert out["held_out"]["games"] == 2
    expected = sum((0.25 - 1) * 2.0 - 2 * (0.5 - 1) * sdr for sdr in (0.1, 0.2)) / 20
    assert out["served"]["d_brier_per_row"] == pytest.approx(expected, abs=1e-6)
    import json as _json

    table = _json.loads((Path(__file__).resolve().parents[1]
                         / ".syndicate/findings_2026-11-18_cell_calibration_frozen_table.json").read_text(encoding="utf-8"))
    assert len(table["cells"]) == 41 and cc.validate_table(
        {**_table({c: e["k"] for c, e in table["cells"].items()})})[1] == "ok"
