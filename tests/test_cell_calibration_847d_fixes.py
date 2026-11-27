"""todo #847 (d)'s three fixes before it loads (lane cell-calibration-847d-fixes, user "Yes, fix (d) first" 2026-11-27).

1. A row (d) calibrated takes neither the optimizer's `edge_shrink` nor (c)'s k again, in rank or stake.
2. While #835's `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION` is on, (c) and (d) leave NCAAF full-game live totals to it.
3. `live_gameline_ledger` records (d)'s stamp and the engine's number, and nothing at all while (d) is off.

The model engine standard's reachability rule first: each fix is driven through its REAL consumer with the switches
off and then on (`off != on`), and with every key absent each consumer returns exactly what it returned before.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import cell_calibration as cc
from syndicate.features.shared import daily_optimizer as opt
from syndicate.features.shared import optimizer_overlay as ov

S835 = "SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION"
KEYS = list(cc.SWITCHES.values()) + ["SYNDICATE_OPTIMIZER_OVERLAY", S835]
DIST = {"220": 40, "226": 60, "234": 60, "240": 40}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    cc.reset_cache()
    ov.reset_cache()
    yield
    cc.reset_cache()
    ov.reset_cache()


def _now():
    return datetime.now(timezone.utc)


def _write_table(tmp_path, cells):
    now = _now()
    payload = {"source": cc.SOURCE, "version": cc.VERSION, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "expires_at": (now + timedelta(hours=cc.TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "cells": {c: {"k": k, "games": 80, "dates": 9, "rows": 900, "post_sd": 0.05} for c, k in cells.items()}}
    path = tmp_path / cc.TABLE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    cc.reset_cache()


def _write_overlay(tmp_path, *, shrink=None, stake=None):
    now = _now()

    def entries(cells):
        return {c: {"factor": f, "w": 0.1, "ci95": [0, 0.2], "games": 80, "dates": 9} for c, f in (cells or {}).items()}

    payload = {"source": opt.SOURCE, "version": opt.OPTIMIZER_VERSION,
               "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "expires_at": (now + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "edge_shrink": entries(shrink), "stake_scale": entries(stake)}
    path = tmp_path / opt.OVERLAY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    ov.reset_cache()


def _switch(monkeypatch, *names):
    for name in names:
        monkeypatch.setenv(name, "on")
    cc.reset_cache()
    ov.reset_cache()


D_KEY = cc.SWITCHES[cc.USE_LIVE_PROB]
C_KEY = cc.SWITCHES[cc.USE_RANK_STAKE]


def _priced_live_row(sport="nhl", market="totals", side="over", line=229.5, market_prob=0.40):
    """A live board row priced by the REAL join: `price_distribution_market` then `_apply_verdict`."""
    from syndicate.features.shared.live_gameline_join import _apply_verdict, new_coverage, price_distribution_market

    verdict = price_distribution_market(dist=DIST, line=line, side=side, market=market, market_prob=market_prob,
                                        sims=2000, sport=sport, live_cell=(sport, market, "full"))
    row = {"kind": "game", "sport": sport, "market": market, "segment": "full", "side": side, "line": line,
           "game_state": "live", "quote": {"fair_probability": market_prob, "price": -110},
           "event_id": "e1", "home_team": "H", "away_team": "A", "books": ["pinnacle", "fanduel"],
           "game": {"state": "live", "home_score": 1, "away_score": 0}}
    hit = {"sport": sport, "sims_run": 2000, "game_pk": 7}
    _apply_verdict(row, {}, verdict, hit, new_coverage(), live_projected=verdict.get("model_prob"), sport=sport)
    return row, verdict


# ===================================================================== fix 1: no second calibration shrink


def test_fix1_reachability_through_the_real_join_off_is_the_shrink_and_on_is_not(tmp_path, monkeypatch):
    cell = "nhl|totals|full|live"
    _write_table(tmp_path, {cell: 0.3})
    _write_overlay(tmp_path, shrink={cell: 0.5})
    off_row, off_verdict = _priced_live_row()
    assert cc.LIVE_PROB_MARKER not in off_row["projection"]
    assert ov.cell_of_row(off_row) == cell  # the optimizer's cell IS the cell (d) stamps
    assert ov.factor_for_row(off_row) == 0.5

    _switch(monkeypatch, D_KEY)
    on_row, on_verdict = _priced_live_row()
    assert on_row["projection"][cc.LIVE_PROB_MARKER]["cell"] == cell
    assert abs(on_verdict["edge_pp"]) < abs(off_verdict["edge_pp"])  # (d) shrank the edge ...
    assert ov.factor_for_row(on_row) == 1.0  # ... so the optimizer does not shrink it again


def test_fix1_stake_scale_still_applies_to_a_calibrated_row(tmp_path, monkeypatch):
    cell = "nhl|totals|full|live"
    _write_table(tmp_path, {cell: 0.3})
    _write_overlay(tmp_path, shrink={cell: 0.6}, stake={cell: 0.8})
    off_row, _ = _priced_live_row()
    assert ov.factor_for_row(off_row) == pytest.approx(0.5)  # 0.6 x 0.8 = 0.48, floored
    _switch(monkeypatch, D_KEY)
    on_row, _ = _priced_live_row()
    assert ov.factor_for_row(on_row) == pytest.approx(0.8)  # the published-bets shortfall is other evidence


def test_fix1_c_k_is_not_applied_on_top_of_d_either(tmp_path, monkeypatch):
    cell = "ncaab|spreads|full|live"
    _write_table(tmp_path, {cell: 0.22})
    _write_overlay(tmp_path, shrink={cell: 0.5})
    row = {"kind": "game", "sport": "ncaab", "market": "spreads", "segment": "full", "side": "home",
           "game_state": "live", "projection": {"model_prob_over": 0.66, "side": "home"}}
    _switch(monkeypatch, C_KEY)
    assert ov.factor_for_row(row) == pytest.approx(0.22)  # (c) alone: today's queued behaviour
    stamped = {**row, "projection": {**row["projection"], cc.LIVE_PROB_MARKER: {"cell": cell, "k": 0.22}}}
    assert ov.factor_for_row(stamped) == 1.0


def test_fix1_reaches_the_stake_and_the_rank(tmp_path, monkeypatch):
    from syndicate.features.shared.layer2_board import _apply_skill_reliability
    from syndicate.features.shared.portfolio_commit import _sizing_model_edge, _sizing_skill_factor

    cell = "nhl|totals|full|live"
    _write_table(tmp_path, {cell: 0.3})
    _write_overlay(tmp_path, shrink={cell: 0.5})
    off_row, off_v = _priced_live_row()
    off_row["model_edge_pct"] = off_v["edge_pp"]
    off_skill = _sizing_skill_factor(off_row)
    _switch(monkeypatch, D_KEY)
    on_row, on_v = _priced_live_row()
    on_row["model_edge_pct"] = on_v["edge_pp"]
    # STAKE: the calibrated edge is sized at the row's skill factor WITHOUT the 0.5.
    assert _sizing_skill_factor(on_row) == pytest.approx(off_skill / 0.5)
    assert _sizing_model_edge(on_row) == pytest.approx(on_v["edge_pp"] * off_skill / 0.5)
    # RANK: the same factor, so the score keeps the calibrated value and no optimizer stamp.
    score = {"score": 4.0, "value_pct": 4.0}
    assert _apply_skill_reliability(score, off_row["projection"], off_row)["optimizer_factor"] == 0.5
    on_score = _apply_skill_reliability(score, on_row["projection"], on_row)
    assert "optimizer_factor" not in on_score


@pytest.mark.parametrize("stamp", [None, {}, {"cell": "x"}, {"k": None}, {"k": 0.0}, {"k": 1.5}, {"k": "0.3"}, 0.3])
def test_fix1_a_missing_or_malformed_stamp_keeps_the_shrink(tmp_path, stamp):
    cell = "nhl|totals|full|live"
    _write_overlay(tmp_path, shrink={cell: 0.5})
    row = {"kind": "game", "sport": "nhl", "market": "totals", "segment": "full", "side": "over",
           "game_state": "live", "projection": {"model_prob_over": 0.6, cc.LIVE_PROB_MARKER: stamp}}
    assert ov.factor_for_row(row) == 0.5


# ===================================================================== fix 2: NCAAF live totals belong to #835


def test_fix2_d_skips_ncaaf_full_game_live_totals_only_while_835_is_on(monkeypatch):
    table = {"ncaaf|totals|full|live": 0.10, "ncaaf|spreads|full|live": 0.52, "ncaaf|totals|h2|live": 0.4,
             "ncaaf|totals_alt|full|live": 0.10}
    _switch(monkeypatch, D_KEY)
    p, stamp = cc.live_probability("ncaaf", "totals", "full", 0.7, 0.5, table=table)  # #835 off: as on main
    assert p == pytest.approx(cc.calibrate(0.7, 0.5, 0.10)) and stamp["cell"] == "ncaaf|totals|full|live"
    monkeypatch.setenv(S835, "on")
    assert cc.live_probability("ncaaf", "totals", "full", 0.7, 0.5, table=table) is None
    assert cc.live_probability("ncaaf", "totals", "game", 0.7, 0.5, table=table) is None
    assert cc.live_probability("ncaaf", "totals_alt", "full", 0.7, 0.5, table=table) is None
    # #835 moves only the full-game draws: spreads and a segment total are still (d)'s.
    assert cc.live_probability("ncaaf", "spreads", "full", 0.7, 0.5, table=table) is not None
    assert cc.live_probability("ncaaf", "totals", "h2", 0.7, 0.5, table=table) is not None
    # Every #835 spelling of "on" counts, and "off" is off.
    for value, skipped in (("1", True), ("true", True), ("yes", True), ("off", False), ("", False)):
        monkeypatch.setenv(S835, value)
        assert (cc.live_probability("ncaaf", "totals", "full", 0.7, 0.5, table=table) is None) is skipped


def test_fix2_reachability_through_the_real_join(tmp_path, monkeypatch):
    _write_table(tmp_path, {"ncaaf|totals|full|live": 0.10})
    _switch(monkeypatch, D_KEY)
    row, verdict = _priced_live_row(sport="ncaaf")
    assert verdict["live_cell_calibration"]["cell"] == "ncaaf|totals|full|live"  # #835 off
    monkeypatch.setenv(S835, "on")
    row835, verdict835 = _priced_live_row(sport="ncaaf")
    assert verdict835["live_cell_calibration"] is None and cc.LIVE_PROB_MARKER not in row835["projection"]
    assert abs(verdict835["edge_pp"]) > abs(verdict["edge_pp"])


def test_fix2_c_keeps_the_optimizer_factor_on_the_cell_while_835_is_on(tmp_path, monkeypatch):
    cell = "ncaaf|totals|full|live"
    _write_table(tmp_path, {cell: 0.10, "ncaaf|totals|full|pregame": 0.10})
    _write_overlay(tmp_path, shrink={cell: 0.5})
    row = {"kind": "game", "sport": "ncaaf", "market": "totals", "segment": "full", "side": "over",
           "game_state": "live", "projection": {"model_prob_over": 0.6}}
    _switch(monkeypatch, C_KEY)
    assert ov.factor_for_row(row) == pytest.approx(0.10)  # #835 off: (c) as queued
    monkeypatch.setenv(S835, "on")
    assert ov.factor_for_row(row) == 0.5  # the optimizer's own factor, exactly as with (c) off
    # #835 is live-only: the pregame cell stays (c)'s.
    assert cc.rank_stake_factor("ncaaf|totals|full|pregame") == pytest.approx(0.10)


def test_fix2_never_reads_835_while_c_and_d_are_off(monkeypatch):
    import syndicate.features.ncaaf.live_total_dispersion as ltd

    def boom(*_a, **_k):
        raise AssertionError("#835's switch was read with (c) and (d) off")

    monkeypatch.setattr(ltd, "enabled", boom)
    table = {"ncaaf|totals|full|live": 0.10}
    assert cc.live_probability("ncaaf", "totals", "full", 0.7, 0.5, table=table) is None
    assert cc.rank_stake_factor("ncaaf|totals|full|live", table=table) is None


# ===================================================================== fix 3: the ledger marker


def test_fix3_off_writes_no_new_key_and_on_writes_the_stamp_and_the_engine_number(tmp_path, monkeypatch):
    from syndicate.features.shared.live_gameline_ledger import LEDGER_VERSION, build_records, record_key

    _write_table(tmp_path, {"nhl|totals|full|live": 0.3})
    off_row, off_v = _priced_live_row()
    off = build_records([off_row], sport="nhl", date_str="2026-11-27", generated_at="t")[0]
    assert "cell_cal" not in off and "model_home_win_prob_cell_uncalibrated" not in off
    assert off["v"] == LEDGER_VERSION == 7

    _switch(monkeypatch, D_KEY)
    on_row, on_v = _priced_live_row()
    on = build_records([on_row], sport="nhl", date_str="2026-11-27", generated_at="t")[0]
    assert on["cell_cal"] == {"cell": "nhl|totals|full|live", "k": 0.3, "k_sd": 0.05, "version": cc.VERSION}
    assert on["model_home_win_prob_cell_uncalibrated"] == pytest.approx(off["model_home_win_prob"])
    assert on["model_home_win_prob"] == pytest.approx(on_v["model_prob"]) != off["model_home_win_prob"]
    # Same identity, so the series dedupes across the switch; the only new keys are the two.
    assert record_key(on) == record_key(off) and on["v"] == off["v"]
    assert set(on) - set(off) == {"cell_cal", "model_home_win_prob_cell_uncalibrated"}


def test_fix3_the_moneyline_path_is_recorded_too(tmp_path, monkeypatch):
    from syndicate.features.shared.live_gameline_join import _apply_verdict, new_coverage, price_moneyline
    from syndicate.features.shared.live_gameline_ledger import build_records

    _write_table(tmp_path, {"soccer|h2h|full|live": 0.2})
    _switch(monkeypatch, D_KEY)
    verdict = price_moneyline(model_prob=0.80, market_prob=0.55, sims=2000, sport="soccer",
                              live_cell=("soccer", "h2h", "full_game"))
    row = {"kind": "game", "sport": "soccer", "market": "h2h", "segment": "full", "side": "home",
           "game_state": "live", "books": ["pinnacle"], "game": {"state": "live"}}
    _apply_verdict(row, {}, verdict, {"sport": "soccer", "sims_run": 2000, "game_pk": 9}, new_coverage(),
                   sport="soccer")
    rec = build_records([row], sport="soccer", date_str="2026-11-27", generated_at="t")[0]
    assert rec["cell_cal"]["cell"] == "soccer|h2h|full|live" and rec["cell_cal"]["k"] == 0.2
    assert rec["model_home_win_prob_cell_uncalibrated"] == pytest.approx(0.80, abs=0.01)


def test_fix3_a_refusal_record_never_carries_it():
    from syndicate.features.shared.live_gameline_join import REFUSAL_KEY
    from syndicate.features.shared.live_gameline_ledger import build_records

    row = {"kind": "game", "market": "h2h", "segment": "first5", "books": ["pinnacle"], "game": {"state": "live"},
           REFUSAL_KEY: {"observed_model_prob": 0.6, "observed_market_prob": 0.5, "observed_edge_pp": 10.0,
                         "withheld_reason": "segment_is_not_full_game", "segment": "first5"}}
    rec = build_records([row], sport="mlb", date_str="d", generated_at="t")[0]
    assert "cell_cal" not in rec
