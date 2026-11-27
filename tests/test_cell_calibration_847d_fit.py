"""todo #847 (d) fit fix (lane cell-calibration-847d-fit-fix, user "Yes, both" 2026-11-27, findings section 8.3 option i).

Once (d) loads, the daily refit would grade (d)'s own calibrated number, so k drifts to 1 and the cell leaves the table.
The fix keeps the number from BEFORE (d) beside every number (d) moved, and the refit reads it:

    pricer (`edge_pp_cell_uncalibrated`) -> projection (`edge_vs_market_pct_cell_uncalibrated`)
    -> board candidate (`model_edge_pct_cell_uncalibrated`) -> recorder (`mu`)
    -> `daily_optimizer.wrap_grade` grades a fit copy (`me` := `mu`) -> `accumulate`'s calibration sums
    -> `fit_calibration` (w*, edge_shrink) and `cell_calibration.fit_table` (k)

and #780's width fitter reads the ledger's `model_home_win_prob_cell_uncalibrated`.

The model engine standard's order: reachability first, through the REAL chain (off != on), then the claim the fix exists
for -- with (d) on, the refit's sums are EXACTLY the sums it gets with (d) off -- then inertness: with the (c) and (d)
keys absent, whatever #835 says, no new key appears anywhere.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import cell_calibration as cc
from syndicate.features.shared import daily_optimizer as opt
from syndicate.features.shared import layer2_board as board
from syndicate.features.shared import live_gameline_join as join
from syndicate.features.shared import model_scorecard as msc
from syndicate.features.shared import opportunity_population_ledger as recorder
from syndicate.features.shared import optimizer_overlay as ov

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bs = _load_script("bucket_search")

S835 = "SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION"
KEYS = list(cc.SWITCHES.values()) + ["SYNDICATE_OPTIMIZER_OVERLAY", "SYNDICATE_PRICING_CALIBRATION", S835]
D_KEY = cc.SWITCHES[cc.USE_LIVE_PROB]
C_KEY = cc.SWITCHES[cc.USE_RANK_STAKE]
CELL = "nhl|totals|full|live"
LINE = 229.5
KICKOFF = "2026-11-20T01:00:00Z"   # 2026-11-19 Central
DAY = "2026-11-19"


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


def _write_table(tmp_path, cells):
    now = datetime.now(timezone.utc)
    payload = {"source": cc.SOURCE, "version": cc.VERSION, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "expires_at": (now + timedelta(hours=cc.TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "cells": {c: {"k": k, "games": 80, "dates": 9, "rows": 900, "post_sd": 0.05} for c, k in cells.items()}}
    path = tmp_path / cc.TABLE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    cc.reset_cache()


def _d_on(monkeypatch, tmp_path, k=0.3):
    _write_table(tmp_path, {CELL: k})
    monkeypatch.setenv(D_KEY, "on")
    cc.reset_cache()


def _grid_row(dist, *, event_id="e1", market_prob=0.5):
    """One two-sided live totals market, priced by the REAL join (`price_distribution_market` + `_apply_verdict`)."""
    verdict = join.price_distribution_market(dist=dist, line=LINE, side="over", market="totals",
                                             market_prob=market_prob, sims=2000, sport="nhl",
                                             live_cell=("nhl", "totals", "full"))
    row = {"sport": "nhl", "event_id": event_id, "kind": "game", "market": "totals", "segment": "full", "line": LINE,
           "home_team": "Home Team", "away_team": "Away Team", "commence_time": KICKOFF, "game_state": "live",
           "sides": ["over", "under"], "books_quoting": 2,
           "cells": {"draftkings": {"over": {"price": -110}, "under": {"price": -110}},
                     "fanduel": {"over": {"price": -110}, "under": {"price": -110}}},
           "best": {"over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
                    "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0}}}
    projection = {"side": "over", "market_fair_prob_over": market_prob}
    join._apply_verdict(row, projection, verdict, {"sport": "nhl", "sims_run": 2000, "game_pk": 7},
                        join.new_coverage(), live_projected=verdict.get("model_prob"), sport="nhl")
    return row, verdict


def _candidates(rows):
    sink = []
    board.build_layer2_rows(rows, population_sink=sink.extend)
    return sink


def _records(candidates):
    out = []
    for i, candidate in enumerate(candidates):
        key = recorder.population_key(candidate)
        assert key, "the fixture must produce recordable candidates"
        out.append(recorder.population_record(candidate, key, f"2026-11-20T02:{i:02d}:00Z", sport="nhl"))
    return out


def _chips(total=231):
    return {DAY: [{"sport": "nhl", "state": "final", "matchup": "Away Team @ Home Team",
                   "away": {"name": "Away Team", "key": "away team", "score": total - 120},
                   "home": {"name": "Home Team", "key": "home team", "score": 120}}]}


def _optimizer_cal(records, chips):
    """The calibration sums the optimizer commits for this game, through the REAL `wrap_grade`."""
    state = {"pub": {}}
    wrapped = opt.wrap_grade(bs.grade_population, state, game_key=msc.game_key)
    graded, _ungraded = wrapped(records, chips)
    entries = list(state["candidates"].values())
    assert len(entries) == 1
    return graded, entries[0]["cal"]


DIST = {"220": 40, "226": 60, "234": 60, "240": 40}          # P(over 229.5) = 0.5 raw
DIST_FOR = {"220": 25, "226": 55, "234": 70, "240": 50}      # P(over) = 0.6 raw: a priced edge either way


# ===================================================================== the spellings the modules share


def test_the_field_names_the_modules_share_are_spelled_the_same():
    assert board._PROJECTION_CELL_UNCALIBRATED_EDGE_KEY == join.PROJECTION_CELL_UNCALIBRATED_EDGE_KEY
    assert board._PROJECTION_CELL_UNCALIBRATED_PROB_KEY == join.PROJECTION_CELL_UNCALIBRATED_PROB_KEY
    assert recorder._CANDIDATE_CELL_UNCALIBRATED_KEY == board.MODEL_EDGE_CELL_UNCALIBRATED_KEY
    assert recorder.MODEL_EDGE_CELL_UNCALIBRATED_FIELD == opt.FIT_EDGE_FIELD


# ===================================================================== reachability, through the real chain


def test_reachability_the_number_before_d_travels_pricer_projection_candidate_record(tmp_path, monkeypatch):
    off_row, off_verdict = _grid_row(DIST_FOR)
    off = _candidates([off_row])
    _d_on(monkeypatch, tmp_path)
    on_row, on_verdict = _grid_row(DIST_FOR)
    on = _candidates([on_row])

    # pricer: (d) moved the edge, and kept the one from before it, EXACTLY the (d)-off verdict's
    assert on_verdict["live_cell_calibration"]["cell"] == CELL
    assert on_verdict["edge_pp"] != off_verdict["edge_pp"]
    assert on_verdict[join.CELL_UNCALIBRATED_EDGE_KEY] == off_verdict["edge_pp"]
    assert join.CELL_UNCALIBRATED_EDGE_KEY not in off_verdict
    # projection
    assert on_row["projection"][join.PROJECTION_CELL_UNCALIBRATED_EDGE_KEY] == off_row["projection"]["edge_vs_market_pct"]
    assert on_row["projection"][join.PROJECTION_CELL_UNCALIBRATED_PROB_KEY] == off_row["projection"]["live_model_prob_over"]
    # candidate, per side, sign included
    by_side_off = {c["side"]: c for c in off}
    by_side_on = {c["side"]: c for c in on}
    assert set(by_side_on) == {"over", "under"}
    for side in ("over", "under"):
        assert by_side_on[side]["model_edge_pct"] != by_side_off[side]["model_edge_pct"]       # (d) is on
        assert by_side_on[side][board.MODEL_EDGE_CELL_UNCALIBRATED_KEY] == by_side_off[side]["model_edge_pct"]
        assert board.MODEL_EDGE_CELL_UNCALIBRATED_KEY not in by_side_off[side]
    # recorder
    rec_off, rec_on = _records(off), _records(on)
    for a, b in zip(sorted(rec_off, key=lambda r: r["k"]), sorted(rec_on, key=lambda r: r["k"])):
        assert "mu" not in a
        assert b["mu"] == a["me"] and b["me"] != a["me"]


def test_reachability_the_refit_reads_the_number_before_d_and_the_scorecard_still_grades_the_served_one(tmp_path, monkeypatch):
    off_row, _ = _grid_row(DIST_FOR)
    rec_off = _records(_candidates([off_row]))
    _d_on(monkeypatch, tmp_path)
    on_row, _ = _grid_row(DIST_FOR)
    rec_on = _records(_candidates([on_row]))

    graded_off, cal_off = _optimizer_cal(rec_off, _chips())
    graded_on, cal_on = _optimizer_cal(rec_on, _chips())
    assert graded_on and graded_off and cal_off[CELL][0] == 2
    # THE CLAIM: with (d) on, the refit's sums are exactly the sums it had with (d) off.
    assert cal_on == cal_off
    # off != on for the FIX itself: without the fit copy the same graded rows give different sums.
    served_cal, _ = opt.accumulate(graded_on)
    assert served_cal != cal_on
    # and what `wrap_grade` RETURNS -- what the scorecard publishes -- is still the served number.
    assert sorted(r["p_model"] for r in graded_on) != sorted(r["p_model"] for r in graded_off)
    served_on = {round(r["p_market"] + r["model_edge_pct"] / 100.0, 9) for r in graded_on}
    assert served_on == {round(r["p_model"], 9) for r in graded_on}


def test_reachability_fit_table_serves_the_same_k_with_d_on_as_with_d_off(tmp_path, monkeypatch):
    """Through `cell_calibration.fit_table` itself: the k the daily refit would serve does not move toward 1."""
    def games(cal):
        return [{"key": f"nhl|g{i}", "date": (datetime(2026, 11, 1) + timedelta(days=i % 20)).strftime("%Y-%m-%d"),
                 "cal": cal} for i in range(60)]

    rows = []
    for i, dist in enumerate((DIST_FOR, {"220": 50, "226": 60, "234": 50, "240": 40},
                              {"220": 20, "226": 50, "234": 70, "240": 60})):
        rows.append(dist)
    off = [_grid_row(d, event_id=f"e{i}")[0] for i, d in enumerate(rows)]
    rec_off = _records(_candidates(off))
    _d_on(monkeypatch, tmp_path)
    on = [_grid_row(d, event_id=f"e{i}")[0] for i, d in enumerate(rows)]
    rec_on = _records(_candidates(on))
    now = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)

    def table(records):
        cal = {}
        for event in ("e0", "e1", "e2"):
            subset = [r for r in records if f"{event}|" in r["k"]]
            _, game_cal = _optimizer_cal(subset, _chips())
            for cell, acc in game_cal.items():
                total = cal.setdefault(cell, [0, 0.0, 0.0])
                total[0] += acc[0]
                total[1] += acc[1]
                total[2] += acc[2]
        return cc.fit_table(games(cal), now=now, today="2026-11-27", resamples=200)

    t_off, t_on = table(rec_off), table(rec_on)
    assert t_off["diagnostics"] and t_on["diagnostics"] == t_off["diagnostics"]


def test_a_row_whose_number_before_d_was_implausible_stays_out_of_the_refit(tmp_path, monkeypatch):
    """Raw 0.9 against an even market is refused by the board's plausibility test; (d)'s 0.66 is not. Before (d) the
    row reached the refit with no model edge, so after (d) it must not reach it with one."""
    extreme = {"220": 10, "240": 90}
    off_row, _ = _grid_row(extreme)
    off = {c["side"]: c for c in _candidates([off_row])}
    _d_on(monkeypatch, tmp_path)
    on_row, _ = _grid_row(extreme)
    on = {c["side"]: c for c in _candidates([on_row])}
    assert off["over"]["model_edge_pct"] is None                      # refused before (d)
    assert on["over"]["model_edge_pct"] is not None                   # (d)'s number is plausible
    assert on["over"][board.MODEL_EDGE_CELL_UNCALIBRATED_KEY] is None  # and the refit sees what it saw before (d)
    rec_off, rec_on = _records(list(off.values())), _records(list(on.values()))
    assert _optimizer_cal(rec_on, _chips())[1] == _optimizer_cal(rec_off, _chips())[1]


def test_a_number_before_d_that_would_not_have_been_priced_records_none():
    out = {"model_prob_cell_uncalibrated": 0.52, "live_cell_calibration": {"cell": CELL, "k": 0.3}}
    join._keep_cell_uncalibrated_edge(out, 0.50, 0.05, 2.0, rounded=True, floor=0.0)   # 2 pts < 2 x 5 pts
    assert out[join.CELL_UNCALIBRATED_EDGE_KEY] is None
    join._keep_cell_uncalibrated_edge(out, 0.50, 0.001, 2.0, rounded=True, floor=0.0)
    assert out[join.CELL_UNCALIBRATED_EDGE_KEY] == 2.0
    unstamped = {"model_prob_cell_uncalibrated": None, "live_cell_calibration": None}
    join._keep_cell_uncalibrated_edge(unstamped, 0.50, 0.001, 2.0, rounded=True, floor=0.0)
    assert join.CELL_UNCALIBRATED_EDGE_KEY not in unstamped


def test_the_moneyline_pricer_keeps_its_unrounded_edge_and_its_floor(tmp_path, monkeypatch):
    cell = "nhl|h2h|full|live"
    off = join.price_moneyline(model_prob=0.6234, market_prob=0.5, sims=4000, sport="nhl",
                               live_cell=("nhl", "h2h", "full"))
    _write_table(tmp_path, {cell: 0.3})
    monkeypatch.setenv(D_KEY, "on")
    cc.reset_cache()
    on = join.price_moneyline(model_prob=0.6234, market_prob=0.5, sims=4000, sport="nhl",
                              live_cell=("nhl", "h2h", "full"))
    assert on["live_cell_calibration"]["cell"] == cell and on["edge_pp"] != off["edge_pp"]
    assert on[join.CELL_UNCALIBRATED_EDGE_KEY] == off["edge_pp"]      # unrounded, exactly
    assert join.CELL_UNCALIBRATED_EDGE_KEY not in off


def test_the_certainty_refusal_blanks_the_number_before_d_as_it_blanked_the_edge(tmp_path, monkeypatch):
    _d_on(monkeypatch, tmp_path)
    verdict = join.price_distribution_market(dist=DIST_FOR, line=LINE, side="over", market="totals", market_prob=0.5,
                                             sims=2000, sport="nhl", live_cell=("nhl", "totals", "full"))
    assert verdict.get(join.CELL_UNCALIBRATED_EDGE_KEY) is not None
    row = {"sport": "nhl", "market": "totals", "segment": "full"}
    join._apply_verdict(row, {"model_prob_over": 1.0, "market_fair_prob_over": 0.5}, verdict, {"sport": "nhl"},
                        join.new_coverage(), live_projected=verdict.get("model_prob"), sport="nhl")
    assert row["projection"]["edge_vs_market_pct"] is None
    assert row["projection"][join.PROJECTION_CELL_UNCALIBRATED_EDGE_KEY] is None


# ===================================================================== #780's width fitter


def test_the_width_fitter_reads_the_number_before_d_after_the_engine_numbers_it_already_preferred():
    fit = _load_script("live_totals_width_fit")
    base = {"model_home_win_prob": 0.55}
    assert fit.fit_prob(dict(base)) == 0.55
    assert fit.fit_prob({**base, "cell_cal": {"k": 0.3}, "model_home_win_prob_cell_uncalibrated": 0.7}) == 0.7
    assert fit.fit_prob({**base, "cell_cal": {"k": 0.3}}) is None          # moved, with no engine number beside it
    # before #780's k wins: the number before (d) is AFTER k
    assert fit.fit_prob({**base, "model_home_win_prob_unscaled": 0.8, "prob_scale": 1.5,
                         "cell_cal": {"k": 0.3}, "model_home_win_prob_cell_uncalibrated": 0.7}) == 0.8
    assert fit.fit_prob({**base, "model_home_win_prob_uncalibrated": 0.66, "total_cal": {"a": 1}}) == 0.66
    assert fit.fit_prob({**base, "cell_cal": {"k": 0.3}, "model_home_win_prob_cell_uncalibrated": 0.7},
                        source="recorded") == 0.55
    assert fit.fit_prob({**base, "cell_cal": {"k": 0.3}, "model_home_win_prob_cell_uncalibrated": 0.7},
                        source="ac") == 0.7


def test_reachability_the_width_fitter_reads_the_same_number_through_the_real_ledger_with_d_on_and_off(tmp_path,
                                                                                                    monkeypatch):
    from syndicate.features.shared import live_gameline_ledger as ledger

    fit = _load_script("live_totals_width_fit")

    def ledger_probs():
        row, _ = _grid_row(DIST_FOR)
        records = ledger.build_records([row], sport="nhl", date_str=DAY)
        assert records, "the fixture row must reach the ledger"
        return [(fit.fit_prob(r), r.get("model_home_win_prob")) for r in records]

    off = ledger_probs()
    _d_on(monkeypatch, tmp_path)
    on = ledger_probs()
    assert [p for p, _ in on] == [p for p, _ in off]                 # the fitter's number did not move
    assert [rec for _, rec in on] != [rec for _, rec in off]         # the recorded one did


# ===================================================================== inert with the (c) and (d) keys absent


@pytest.mark.parametrize("s835", [None, "on", "1"])
def test_with_c_and_d_absent_no_new_key_appears_anywhere_whatever_835_says(tmp_path, monkeypatch, s835):
    _write_table(tmp_path, {CELL: 0.3})      # a served table on disk, so only the switches decide
    if s835 is not None:
        monkeypatch.setenv(S835, s835)
    row, verdict = _grid_row(DIST_FOR)
    candidates = _candidates([row])
    records = _records(candidates)
    blob = json.dumps([row, verdict, candidates, records], sort_keys=True, default=str)
    for key in (join.CELL_UNCALIBRATED_EDGE_KEY, join.PROJECTION_CELL_UNCALIBRATED_EDGE_KEY,
                join.PROJECTION_CELL_UNCALIBRATED_PROB_KEY, board.MODEL_EDGE_CELL_UNCALIBRATED_KEY):
        assert f'"{key}"' not in blob
    assert all("mu" not in r for r in records)
    assert opt.fit_records(records) is None
    graded, cal = _optimizer_cal(records, _chips())
    assert cal == opt.accumulate(graded)[0]


def test_c_on_alone_adds_nothing_either(tmp_path, monkeypatch):
    _write_table(tmp_path, {CELL: 0.3})
    monkeypatch.setenv(C_KEY, "on")
    cc.reset_cache()
    row, verdict = _grid_row(DIST_FOR)
    records = _records(_candidates([row]))
    assert join.CELL_UNCALIBRATED_EDGE_KEY not in verdict and all("mu" not in r for r in records)


# ===================================================================== the cron's own path: stored records, then graded


def _cron_cal(records, chips):
    """The cron's path, not a shortcut: `merge_board_date` stores each record through `strip_record`, then
    `grade_pending` grades the STORED records through the optimizer's `wrap_grade`, then `commit` keeps the sums."""
    state = msc.empty_state("sig")
    msc.merge_board_date(state, DAY, records, today="2026-11-27", central_date=bs.SCORECARD.central_date,
                         fetched_at="2026-11-27T12:00:00Z")
    opt_state = opt.empty_state("sig")
    grade = opt.wrap_grade(bs.grade_population, opt_state, game_key=msc.game_key)
    msc.grade_pending(state, today="2026-11-27", grade=grade, chips_for=lambda day: chips[day],
                      central_date=bs.SCORECARD.central_date)
    opt.commit(opt_state, state["games"])
    games = list(opt_state["games"].values())
    assert len(games) == 1, "the fixture game must be committed"
    return games[0]["cal"]


def test_reachability_the_fit_survives_the_cron_storing_and_grading_its_records(tmp_path, monkeypatch):
    off_row, _ = _grid_row(DIST_FOR)
    rec_off = _records(_candidates([off_row]))
    _d_on(monkeypatch, tmp_path)
    on_row, _ = _grid_row(DIST_FOR)
    rec_on = _records(_candidates([on_row]))
    cal_off, cal_on = _cron_cal(rec_off, _chips()), _cron_cal(rec_on, _chips())
    assert cal_off[CELL][0] == 2
    assert cal_on == cal_off
    # and the scorecard's stored records keep `mu`, None included
    assert msc.strip_record({"k": "x", "me": 1.0, "mu": None}) == {"k": "x", "me": 1.0, "mu": None}
    assert msc.strip_record({"k": "x", "me": 1.0, "mu": 2.5}) == {"k": "x", "me": 1.0, "mu": 2.5}
    assert msc.strip_record({"k": "x", "me": 1.0, "mp": None}) == {"k": "x", "me": 1.0}


def test_the_cron_keeps_a_none_number_before_d_so_an_implausible_row_stays_out(tmp_path, monkeypatch):
    extreme = {"220": 10, "240": 90}
    rec_off = _records(_candidates([_grid_row(extreme)[0]]))
    _d_on(monkeypatch, tmp_path)
    rec_on = _records(_candidates([_grid_row(extreme)[0]]))
    assert any(r.get("mu", 0) is None for r in rec_on)
    assert _cron_cal(rec_on, _chips()) == _cron_cal(rec_off, _chips())


def test_the_committed_game_says_how_many_records_were_refit_and_says_nothing_otherwise(tmp_path, monkeypatch):
    def committed(records):
        state = msc.empty_state("sig")
        msc.merge_board_date(state, DAY, records, today="2026-11-27", central_date=bs.SCORECARD.central_date,
                             fetched_at="2026-11-27T12:00:00Z")
        opt_state = opt.empty_state("sig")
        grade = opt.wrap_grade(bs.grade_population, opt_state, game_key=msc.game_key)
        chips = _chips()
        msc.grade_pending(state, today="2026-11-27", grade=grade, chips_for=lambda day: chips[day],
                          central_date=bs.SCORECARD.central_date)
        opt.commit(opt_state, state["games"])
        return list(opt_state["games"].values())[0]

    assert "fit_mu" not in committed(_records(_candidates([_grid_row(DIST_FOR)[0]])))
    _d_on(monkeypatch, tmp_path)
    assert committed(_records(_candidates([_grid_row(DIST_FOR)[0]])))["fit_mu"] == 2
