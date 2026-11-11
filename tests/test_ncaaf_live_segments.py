"""NCAAF live SEGMENTS (h1 h2 q1-q4) for the board's Live column, display only (todo #785, lane
ncaaf-live-segment-display).

Measured on the fleet 2026-11-11 00:08-04:45Z: 43 NCAAF board joins refused 2,825 of 4,892 live game rows
`segment_is_not_full_game`, and no NCAAF segment row ever showed a Live proj. Two gaps: `ncaaf/live_resim` published
no `projection.segments`, and `board_enrichment` built segment indexes for NCAAB/WNCAAB/NBA only.

These pin:
  * the BINNING: the score already on the board split by quarter (linescores read only where the score cannot
    separate them), plus the sim's quarters from the resume point, plus overtime for h2 only -- exactly
    `segment_actuals.SEGMENT_PERIODS["ncaaf"]`; a missing or impossible linescore is a NAMED refusal, never a zero;
  * draw by draw, q1 + q2 = h1 and h1 + h2 = the full game (the calibrators are identity);
  * the switch: off restores the old lane byte for byte AND the board's old refusal label (off != on), through the
    env, the producer and `board_enrichment`'s own index builder;
  * nothing prices: a segment row carries the number for DISPLAY, refuses `segment_pricing_disabled`, and carries
    no edge and no `live_aware`; a segment MONEYLINE shows nothing (football quarters tie too often for a
    two-sided "P(home leads)"), and a settled segment shows nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from syndicate.features.ncaaf import live_resim
from syndicate.features.ncaaf.live_resim import (
    LIVE_SEGMENTS_ENV,
    NcaafLiveGameState,
    build_game_lens,
    build_live_lens_snapshot,
    live_segment_frames,
    live_segments_enabled,
    live_state_from_espn_event,
    resim_live_game,
)
from syndicate.features.shared import board_enrichment
from syndicate.features.shared import live_gameline_join as lgj
from syndicate.features.shared.layer2_board import _live_projection_columns

HOME, AWAY = "Bowling Green", "Kent State"
PRICING_FIELDS = ("model_edge_pct", "edge_vs_market_pct", "edge_vs_line", "model_ev_pct", "live_aware")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (LIVE_SEGMENTS_ENV, "NCAAF_LIVE_TOTAL_BIAS_POINTS", "NCAAF_LIVE_TOTAL_SPREAD_SCALE",
                "NCAAF_LIVE_MARGIN_BIAS_POINTS", "NCAAF_LIVE_MARGIN_SPREAD_SCALE", "NCAAF_LIVE_RESIM_SIMS",
                lgj.LANE_AGE_GATE_ENV, lgj.MAX_LANE_AGE_ENV, lgj.COLLEGE_SEGMENT_PRICING_ENV):
        monkeypatch.delenv(key, raising=False)


def _state(period, clock, home, away, home_ls=(), away_ls=(), owner="home"):
    return NcaafLiveGameState(away_team=AWAY, home_team=HOME, period=period, clock_seconds=clock,
                              home_score=home, away_score=away, possession_owner=owner,
                              home_linescores=tuple(home_ls), away_linescores=tuple(away_ls))


def _frame(frames, name):
    f = frames[name]
    return (f.known_home, f.known_away), f.sim_quarters, f.settled, round(f.remaining_fraction, 4)


# ------------------------------------------------------------------------------------------------- the binning

def test_the_segment_table_is_the_one_settlement_grades():
    from syndicate.features.shared.segment_actuals import SEGMENT_PERIODS

    assert set(live_resim.LIVE_SEGMENTS) == set(SEGMENT_PERIODS["ncaaf"])
    assert SEGMENT_PERIODS["ncaaf"]["h2"] == (3, 4, None) and SEGMENT_PERIODS["ncaaf"]["q4"] == (4,)


def test_mid_first_quarter_needs_no_linescore():
    frames, refused = live_segment_frames(_state(1, 500, 7, 3))
    assert refused == {}
    assert _frame(frames, "q1") == ((7, 3), (1,), False, round(500 / 900, 4))
    assert _frame(frames, "h1") == ((7, 3), (1, 2), False, round(1400 / 1800, 4))
    assert _frame(frames, "q2") == ((0, 0), (2,), False, 1.0)
    assert _frame(frames, "h2") == ((0, 0), (3, 4), False, 1.0)
    assert frames["h2"].includes_overtime and not frames["q4"].includes_overtime


def test_mid_second_quarter_splits_the_score_by_the_first_quarters_linescore():
    frames, refused = live_segment_frames(_state(2, 400, 10, 7, (7, 3), (0, 7)))
    assert refused == {}
    assert _frame(frames, "q1") == ((7, 0), (), True, 0.0)          # over: the real Q1, a point mass
    assert _frame(frames, "q2") == ((3, 7), (2,), False, round(400 / 900, 4))
    assert _frame(frames, "h1") == ((10, 7), (2,), False, round(400 / 1800, 4))


def test_h1_in_the_second_quarter_is_the_whole_score_even_without_a_linescore():
    frames, refused = live_segment_frames(_state(2, 400, 10, 7))
    assert _frame(frames, "h1")[0] == (10, 7)
    # Q1 and Q2 cannot be told apart without Q1's linescore: refused by NAME, never a zero.
    assert refused == {"q1": "linescore_missing", "q2": "linescore_missing"}
    assert "q1" not in frames and "q2" not in frames


def test_halftime_settles_the_first_half_and_leaves_the_second_open():
    frames, _ = live_segment_frames(_state(2, 0, 17, 14, (7, 10), (7, 7)))
    assert _frame(frames, "h1") == ((17, 14), (2,), True, 0.0)
    assert _frame(frames, "q2") == ((10, 7), (2,), True, 0.0)
    assert _frame(frames, "h2") == ((0, 0), (3, 4), False, 1.0)


def test_third_quarter_takes_the_halftime_score_off_the_second_half():
    frames, refused = live_segment_frames(_state(3, 600, 24, 14, (7, 10, 7), (7, 7, 0)))
    assert refused == {}
    assert _frame(frames, "h2") == ((7, 0), (3, 4), False, round(1500 / 1800, 4))
    assert _frame(frames, "q3") == ((7, 0), (3,), False, round(600 / 900, 4))
    assert _frame(frames, "h1") == ((17, 14), (), True, 0.0)


def test_mid_fourth_quarter():
    frames, _ = live_segment_frames(_state(4, 120, 31, 21, (7, 10, 7, 7), (7, 7, 0, 7)))
    assert _frame(frames, "q4") == ((7, 7), (4,), False, round(120 / 900, 4))
    assert _frame(frames, "h2") == ((14, 7), (4,), False, round(120 / 1800, 4))
    # h2 takes every overtime period, so it is never settled while the game is live.
    assert not frames["h2"].settled


def test_a_hole_and_a_linescore_past_the_score_are_named_refusals():
    _frames, refused = live_segment_frames(_state(3, 600, 24, 14, (7, None, 7), (7, 7, 0)))
    assert refused["h2"] == "linescore_missing" and refused["q2"] == "linescore_missing"
    frames, refused = live_segment_frames(_state(2, 400, 7, 0, (14,), (0,)))
    assert refused["q2"] == "linescores_exceed_score" and refused["q1"] == "linescores_exceed_score"
    assert "h1" in frames                                              # needs no linescore at all


def test_the_espn_record_carries_its_linescores_holes_kept():
    row = {"in_progress": True, "final": False, "period": 3, "clock": "10:00", "home_score": 24, "away_score": 14,
           "home_linescores": [7, 10, 7], "away_linescores": [7, None, "x"]}
    state = live_state_from_espn_event(row, away_team=AWAY, home_team=HOME)
    assert state.home_linescores == (7, 10, 7) and state.away_linescores == (7, None, None)
    bare = live_state_from_espn_event({k: v for k, v in row.items() if "linescores" not in k},
                                      away_team=AWAY, home_team=HOME)
    assert bare.home_linescores == () and bare.away_linescores == ()


# ------------------------------------------------------------------------------------------------- the draws

def _fake_sim(quarter_log, final):
    def simulate(sim_input, profile=None):  # noqa: ARG001
        return SimpleNamespace(quarter_log=tuple(quarter_log), final_score=dict(final))
    return simulate


def _ratings():
    return dict(home_offense=1.0, home_defense=1.0, away_offense=0.0, away_defense=0.0)


def test_one_draw_with_overtime_lands_in_each_segment_as_it_settles(monkeypatch):
    # Resume Q3 5:00 at 14-10 (Q1 7-3, Q2 7-7, Q3 so far 0-0). The draw: Q3 rest 0-7, Q4 3-0 -> 17-17, OT home +6.
    monkeypatch.setattr(live_resim, "simulate_game", _fake_sim(
        [{"quarter": 3, "home_points": 0, "away_points": 7}, {"quarter": 4, "home_points": 3, "away_points": 0}],
        {"home": 23, "away": 17}))
    state = _state(3, 300, 14, 10, (7, 7, 0), (3, 7, 0))
    result = resim_live_game(state, sims=4, **_ratings())
    seg = result["segments"]
    assert seg["q3"]["total_dist"] == {"7": 4} and seg["q3"]["margin_dist"] == {"-7": 4}
    assert seg["q4"]["total_dist"] == {"3": 4} and seg["q4"]["margin_dist"] == {"3": 4}   # regulation only
    assert seg["h2"]["total_dist"] == {"16": 4} and seg["h2"]["margin_dist"] == {"2": 4}  # q3 + q4 + OT 6-0
    assert seg["h1"]["total_dist"] == {"24": 4} and seg["h1"]["settled"] is True
    assert seg["h1"]["home_points_mean"] + seg["h2"]["home_points_mean"] == 23
    assert seg["h1"]["away_points_mean"] + seg["h2"]["away_points_mean"] == 17
    assert seg["h2"]["includesOvertime"] is True and seg["q4"]["includesOvertime"] is False
    assert all(block["marginAnchored"] is False for block in seg.values())
    assert result["segments_refused"] == {}


def test_the_shipped_function_keeps_q4s_histogram_for_the_grade_and_only_the_lane_drops_it(monkeypatch):
    monkeypatch.setattr(live_resim, "simulate_game", _fake_sim(
        [{"quarter": 3, "home_points": 0, "away_points": 7}, {"quarter": 4, "home_points": 3, "away_points": 0}],
        {"home": 23, "away": 17}))
    state = _state(3, 300, 14, 10, (7, 7, 0), (3, 7, 0))
    result = resim_live_game(state, sims=4, **_ratings())
    assert result["segments"]["q4"]["total_dist"] == {"3": 4}
    (lane,) = build_game_lens(state, result)
    segments = lane["projection"]["segments"]
    assert segments["q4"]["total_dist"] == {} and segments["q4"]["total_mean"] == 3.0
    assert segments["q4"]["margin_dist"] == {"3": 4}
    assert segments["q1"]["total_dist"] == {} and segments["q1"]["total_mean"] is None   # q1: nothing at all
    assert all("totalDistWithheld" not in block for name, block in segments.items() if name not in ("q1", "q4"))
    assert segments["q1"]["margin_dist"] == {"4": 4}                  # margins all passed: kept


def test_in_the_first_quarter_q1_totals_show_nothing_and_h1_totals_show(monkeypatch):
    """q1's totals failed their only grade (kickoff, 0.186, mean +1.41 high): the lane drops both numbers."""
    monkeypatch.setattr(live_resim, "simulate_game", _fake_sim(
        [{"quarter": 1, "home_points": 3, "away_points": 0}, {"quarter": 2, "home_points": 7, "away_points": 7},
         {"quarter": 3, "home_points": 0, "away_points": 3}, {"quarter": 4, "home_points": 7, "away_points": 0}],
        {"home": 24, "away": 10}))
    as_of = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    row = {"in_progress": True, "final": False, "period": 1, "clock": "8:00", "home_score": 7, "away_score": 0,
           "possession_owner": "home", "situation": {}, "home_linescores": [7], "away_linescores": [0], "as_of": as_of}
    snapshot = build_live_lens_snapshot("2026-11-11", games=[{"away_team": AWAY, "home_team": HOME, "live_key": "k"}],
                                        live_index={"k": row}, ratings={HOME.lower(): (1.0, 1.0), AWAY.lower(): (0.0, 0.0)},
                                        sims=8)
    grid = [r for r in _grid() if r["segment"] in ("q1", "h1") and r["market"] == "totals"]
    grid = [{**grid[0], "segment": "q1", "line": 9.5}, {**grid[0], "segment": "h1", "line": 26.5}]
    _attach_through_the_board(monkeypatch, snapshot, grid)
    q1_row, h1_row = grid
    assert lgj.LIVE_DISPLAY_KEY not in q1_row
    assert h1_row[lgj.LIVE_DISPLAY_KEY]["total_mean"] == 24.0          # 7-0 + Q1 rest 3-0 + Q2 7-7


def test_a_draw_whose_log_overshoots_the_final_is_counted_not_binned(monkeypatch):
    monkeypatch.setattr(live_resim, "simulate_game", _fake_sim(
        [{"quarter": 3, "home_points": 30, "away_points": 0}], {"home": 20, "away": 10}))
    result = resim_live_game(_state(3, 300, 14, 10, (7, 7, 0), (3, 7, 0)), sims=4, **_ratings())
    assert result["segments"] == {} and result["segments_refused"]["_unusable_sims"] == "4"
    assert result["sims_run"] == 4                                    # the full game is untouched


def test_on_the_real_engine_the_halves_add_up_to_the_full_game_draw_by_draw():
    state = _state(2, 200, 10, 7, (7, 3), (0, 7))
    result = resim_live_game(state, sims=20, **_ratings())
    seg, n = result["segments"], result["sims_run"]
    for block in seg.values():
        assert block["sims"] == n == sum(block["total_dist"].values()) == sum(block["margin_dist"].values())
    assert seg["h1"]["total_mean"] + seg["h2"]["total_mean"] == pytest.approx(result["total_mean"], abs=2e-3)
    assert seg["q1"]["total_mean"] + seg["q2"]["total_mean"] == pytest.approx(seg["h1"]["total_mean"], abs=2e-3)
    assert seg["q1"]["total_dist"] == {"7": n}                        # settled Q1: the real 7-0, every draw
    assert min(int(k) for k in seg["h1"]["total_dist"]) >= 17          # nothing already scored is lost


# ------------------------------------------------------------------------------------------------- the switch

@pytest.mark.parametrize("value", ["0", "false", "OFF", "no"])
def test_off_restores_the_old_lane_byte_for_byte(monkeypatch, value):
    monkeypatch.setattr(live_resim, "simulate_game", _fake_sim(
        [{"quarter": 2, "home_points": 3, "away_points": 0}, {"quarter": 3, "home_points": 7, "away_points": 7},
         {"quarter": 4, "home_points": 0, "away_points": 3}], {"home": 23, "away": 17}))
    state = _state(2, 400, 13, 7, (7, 6), (7, 0))
    on = resim_live_game(state, sims=4, **_ratings())
    monkeypatch.setenv(LIVE_SEGMENTS_ENV, value)
    assert live_segments_enabled() is False
    off = resim_live_game(state, sims=4, **_ratings())
    assert "segments" not in off and "segments_refused" not in off
    assert {k: v for k, v in on.items() if not k.startswith("segments")} == off
    (lane_off,) = build_game_lens(state, off)
    (lane_on,) = build_game_lens(state, on)
    assert "segments" not in lane_off["projection"] and set(lane_on["projection"]["segments"]) == set(live_resim.LIVE_SEGMENTS)
    lane_on["projection"].pop("segments")
    assert lane_on == lane_off                                        # off != on, and ONLY in the segment key


def test_absent_and_unrecognised_values_are_on():
    assert live_segments_enabled({}) is True
    assert live_segments_enabled({LIVE_SEGMENTS_ENV: ""}) is True
    assert live_segments_enabled({LIVE_SEGMENTS_ENV: "1"}) is True


# ------------------------------------------------------------------------------------------------- the board

def _producer_snapshot(monkeypatch):
    """The REAL producer path (`build_live_lens_snapshot`) on a fake engine: Q2 6:40, 10-7, Q1 7-0. Odd seeds score
    the rest of Q2 7-3 (h1 17-10, final 27-17), even seeds 0-3 (h1 10-10, final 20-17); Q3 7-0 and Q4 3-7 always."""
    def simulate(sim_input, profile=None):  # noqa: ARG001
        odd = sim_input.seed % 2 == 1
        q2 = (7, 3) if odd else (0, 3)
        log = ({"quarter": 2, "home_points": q2[0], "away_points": q2[1]},
               {"quarter": 3, "home_points": 7, "away_points": 0}, {"quarter": 4, "home_points": 3, "away_points": 7})
        return SimpleNamespace(quarter_log=log, final_score={"home": 10 + q2[0] + 10, "away": 7 + q2[1] + 7})

    monkeypatch.setattr(live_resim, "simulate_game", simulate)
    as_of = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    row = {"in_progress": True, "final": False, "period": 2, "clock": "6:40", "home_score": 10, "away_score": 7,
           "possession_owner": "home", "situation": {}, "home_linescores": [7, 3], "away_linescores": [0, 7],
           "as_of": as_of}
    ratings = {HOME.lower(): (1.0, 1.0), AWAY.lower(): (0.0, 0.0)}
    return build_live_lens_snapshot("2026-11-11", games=[{"away_team": AWAY, "home_team": HOME, "live_key": "k"}],
                                    live_index={"k": row}, ratings=ratings, sims=8)


def _grid():
    now = datetime.now(timezone.utc).isoformat()

    def row(segment, market, line):
        sides = ["over", "under"] if market == "totals" else ["home", "away"]
        return {"kind": "game", "sport": "ncaaf", "market": market, "segment": segment, "line": line,
                "sides": sides, "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0, "updated_at": now,
                "game": {"state": "live"}, "projection": {"market_fair_prob_over": 0.5}}

    return [row("h1", "totals", 26.5), row("q3", "totals", 13.5), row("h1", "spreads", 3.5),
            row("h1", "h2h", None), row("q1", "totals", 6.5), row("q4", "totals", 9.5)]


def _attach_through_the_board(monkeypatch, snapshot, grid):
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: snapshot)
    return board_enrichment.attach_live_gamelines_for_sport(grid, sport="ncaaf", selected_date="2026-11-11")


def test_the_board_shows_segment_totals_for_display_and_prices_nothing(monkeypatch):
    snapshot = _producer_snapshot(monkeypatch)
    lane = snapshot["games"][0]["gameLens"][0]
    assert lane["source"] == "live_resim" and set(lane["projection"]["segments"]) == set(live_resim.LIVE_SEGMENTS)
    grid = _grid()
    coverage = _attach_through_the_board(monkeypatch, snapshot, grid)
    assert coverage["segment_index_sizes"] == {s: 1 for s in live_resim.LIVE_SEGMENTS}
    assert coverage["segment_pricing_enabled"] is False
    h1_tot, q3_tot, h1_spr, h1_ml, q1_tot, q4_tot = grid
    # h1: 10-7 on the board + Q2 rest 7-3 (half the draws) or 0-3 -> 27 / 20, mean 23.5; q3: 7-0, every draw.
    assert h1_tot[lgj.LIVE_DISPLAY_KEY]["segment"] == "h1" and h1_tot[lgj.LIVE_DISPLAY_KEY]["total_mean"] == 23.5
    assert h1_tot[lgj.LIVE_DISPLAY_KEY]["basis"] == lgj.REASON_SEGMENT_PRICING_DISABLED
    assert q3_tot[lgj.LIVE_DISPLAY_KEY]["total_mean"] == 7.0
    assert _live_projection_columns({**h1_tot, "side": "over"})["live_total"] == 23.5
    # q4's totals histogram failed its grade (0.240): the lane withholds it, so the row shows the live total and NO
    # probability -- the producer's choice, read off the real lane, not a join rule.
    q4_block = lane["projection"]["segments"]["q4"]
    assert q4_block["total_dist"] == {} and q4_block["totalDistWithheld"].startswith("q4_totals_failed")
    assert q4_tot[lgj.LIVE_DISPLAY_KEY]["total_mean"] == 10.0 and q4_tot[lgj.LIVE_DISPLAY_KEY]["prob_over"] is None
    q4_cols = _live_projection_columns({**q4_tot, "side": "over"})
    assert q4_cols["live_total"] == 10.0 and q4_cols.get("live_model_probability") is None
    # Spreads (user "Yes, add spreads"; every segment margin passed its grade): the h1 margin is +7 in half the draws
    # and 0 in the rest, so home covers the away-frame line 3.5 in half -> P(home) 0.5; the away side restates it.
    spread = h1_spr[lgj.LIVE_DISPLAY_KEY]
    assert spread["segment"] == "h1" and spread["basis"] == lgj.REASON_SEGMENT_PRICING_DISABLED
    assert spread["prob_over"] == pytest.approx(0.5, abs=1e-6)
    home = _live_projection_columns({**h1_spr, "side": "home"})["live_model_probability"]
    away = _live_projection_columns({**h1_spr, "side": "away"})["live_model_probability"]
    assert home == pytest.approx(spread["prob_over"], abs=1e-4) and away == pytest.approx(1.0 - home, abs=1e-4)
    # Not shown: a segment moneyline (unanchored, and a quarter ties too often), a settled segment.
    for row in (h1_ml, q1_tot):
        assert lgj.LIVE_DISPLAY_KEY not in row
    for row in grid:
        for field in PRICING_FIELDS:
            assert row.get(field) is None and (row.get("projection") or {}).get(field) is None, field
        assert "live_gameline" not in row
    why = coverage["withheld_by_reason"]
    assert why.get(lgj.REASON_SEGMENT_PRICING_DISABLED) == 6 and lgj.REASON_SEGMENT_NOT_FULL_GAME not in why


def test_the_spread_number_comes_from_the_raw_margin_table_and_only_from_it(monkeypatch):
    """off != on for spreads: without ncaaf in `_RAW_MARGIN_DISPLAY_SPORTS` the same row shows nothing (the segment
    margin is unanchored), and the totals rows beside it are unaffected."""
    snapshot = _producer_snapshot(monkeypatch)
    monkeypatch.setattr(lgj, "_RAW_MARGIN_DISPLAY_SPORTS", frozenset({"nba"}))
    grid = _grid()
    _attach_through_the_board(monkeypatch, snapshot, grid)
    h1_tot, _q3, h1_spr, _ml, _q1, _q4 = grid
    assert lgj.LIVE_DISPLAY_KEY not in h1_spr
    assert h1_tot[lgj.LIVE_DISPLAY_KEY]["total_mean"] == 23.5


def test_off_through_the_env_restores_the_old_board_reading(monkeypatch):
    monkeypatch.setenv(LIVE_SEGMENTS_ENV, "0")
    snapshot = _producer_snapshot(monkeypatch)
    assert "segments" not in snapshot["games"][0]["gameLens"][0]["projection"]
    grid = _grid()
    coverage = _attach_through_the_board(monkeypatch, snapshot, grid)
    assert "segment_index_sizes" not in coverage
    assert all(lgj.LIVE_DISPLAY_KEY not in row for row in grid)
    assert coverage["withheld_by_reason"] == {lgj.REASON_SEGMENT_NOT_FULL_GAME: 6}


def test_a_segment_lane_past_the_ncaaf_lane_ceiling_shows_nothing(monkeypatch):
    snapshot = _producer_snapshot(monkeypatch)
    old = (datetime.now(timezone.utc) - timedelta(seconds=lgj._MAX_LANE_AGE_SECONDS_BY_SPORT["ncaaf"] + 60)).isoformat()
    snapshot["games"][0]["gameLens"][0]["liveStateAsOf"] = old
    grid = _grid()
    _attach_through_the_board(monkeypatch, snapshot, grid)
    assert all(lgj.LIVE_DISPLAY_KEY not in row for row in grid)
