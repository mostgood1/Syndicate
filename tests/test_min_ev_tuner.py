"""min_ev_tuner: per-cell min_ev proposals from settled ROI + CLV (lane min-ev-tuner-shadow)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import min_ev_tuner as T
from syndicate.features.shared.season_phase import season_phase

NOW = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)


def _order(i: int, *, won: bool, clv: float | None, venue="paper:kalshi", sport="ncaaf",
           market="totals", date="2026-10-10", ev=2.0, stake=10.0, scope="same_book", event=None):
    mark = None if clv is None else {"clv_pct": clv, "close_book_scope": scope}
    return {
        "idempotency_key": f"k{i}",
        "event_id": event or f"e{i}",
        "venue": venue,
        "mode": "paper" if venue.startswith("paper") else "live",
        "sport": sport,
        "market": market,
        "selected_date": date,
        "status": "filled",
        "outcome": "won" if won else "lost",
        "pnl_dollars": 9.0 if won else -stake,
        "fill_stake_dollars": stake,
        "ev_pct": ev,
        "graded_at": f"{date}T23:{i % 60:02d}:00Z",
        "closing_mark": mark,
    }


def _losing_cell(n=60, ev=2.0):
    # Mostly losses with CLV consistently negative: both significantly negative.
    return [_order(i, won=(i % 5 == 0), clv=-2.0 - (i % 3) * 0.5, ev=ev) for i in range(n)]


def _winning_cell(n=60, ev=2.0):
    return [_order(i, won=(i % 5 != 0), clv=2.0 + (i % 3) * 0.5, ev=ev) for i in range(n)]


@pytest.fixture
def memory_state(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(T, "load_state", lambda: dict(store.get("s") or {}))
    monkeypatch.setattr(T, "_save_state", lambda state: store.__setitem__("s", dict(state)))
    monkeypatch.setattr(T, "_LAST_RUN_DATE_IN_PROCESS", {})
    for key in [k for k in __import__("os").environ if k.startswith("SYNDICATE_MIN_EV_TUNER")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_MIN_EV_PCT", raising=False)
    import syndicate.features.shared.portfolio_settings as ps

    monkeypatch.setattr(ps, "_read_stored", lambda: ({}, None))
    return store


# --- reachability: off != shadow --------------------------------------------


def test_off_writes_nothing_and_shadow_writes_state(memory_state, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "off")
    off = T.maybe_run_nightly(now=NOW)
    assert off == {"ran": False, "reason": "off"}
    assert "s" not in memory_state

    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "shadow")
    result = T.run_nightly(orders_loader=_losing_cell, now=NOW)
    assert result["ran"] is True
    state = memory_state["s"]
    assert state["mode"] == "shadow"
    assert state["cells"]["kalshi|ncaaf|totals|regular"]["action"] == T.ACTION_RAISE


def test_absent_or_unknown_mode_is_shadow_never_apply(monkeypatch):
    monkeypatch.delenv("SYNDICATE_MIN_EV_TUNER", raising=False)
    assert T.tuner_mode() == T.MODE_SHADOW
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "aply")
    assert T.tuner_mode() == T.MODE_SHADOW
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    assert T.tuner_mode() == T.MODE_APPLY


def test_shadow_never_changes_the_cut_line_apply_does():
    state = {"cells": {"kalshi|ncaaf|totals|regular": {"min_ev_pct": 2.5}}}
    row = {"venue": "kalshi", "sport": "ncaaf", "market": "totals"}
    shadow = T.effective_min_ev_pct(row, base_min_ev_pct=2.0, selected_date="2026-10-10", state=state, mode="shadow")
    apply = T.effective_min_ev_pct(row, base_min_ev_pct=2.0, selected_date="2026-10-10", state=state, mode="apply")
    assert shadow == (2.0, "base")
    assert apply == (2.5, "tuned_cell")
    assert shadow != apply


# --- decisions ---------------------------------------------------------------


def test_both_negative_raises_one_step(memory_state):
    out = T.compute_proposals(_losing_cell(), state={}, base_min_ev_pct=2.0)
    cell = out["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["min_ev_pct"], cell["previous_min_ev_pct"]) == ("raise", 2.5, 2.0)


def test_both_positive_lowers_one_step(memory_state):
    out = T.compute_proposals(_winning_cell(), state={}, base_min_ev_pct=2.0)
    cell = out["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["min_ev_pct"]) == ("lower", 1.5)


def test_a_cell_lost_by_its_high_ev_rows_does_not_raise_the_cut(memory_state):
    # learnings 2026-09-29: ROI has run ANTI-correlated with claimed EV. The
    # rows a raise would remove (EV in [2, 3)) are winning; the losers sit at
    # 5%. The whole cell is significantly negative -- and the cut must hold.
    marginal = [_order(i, won=(i % 5 != 0), clv=1.0 + (i % 3) * 0.5, ev=2.0 + (i % 5) * 0.1) for i in range(45)]
    high = [_order(100 + i, won=(i % 10 == 0), clv=-2.0 - (i % 3) * 0.5, ev=5.0) for i in range(150)]
    cell = T.compute_proposals(marginal + high, state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert cell["evidence"]["roi_t"] <= -2 and cell["evidence"]["clv_t"] <= -2
    assert cell["action"] != T.ACTION_RAISE
    low, high = cell["marginal"]["band"]
    assert 2.0 <= low < 2.5 and high < 5.0  # the 2%-EV rows, never the 5% losers


def test_roi_alone_does_not_move(memory_state):
    rows = [_order(i, won=(i % 5 == 0), clv=(1.0 if i % 2 else -1.0)) for i in range(60)]
    cell = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert cell["action"] == "hold"
    assert cell["min_ev_pct"] is None  # never moved -> keeps following the base


def test_min_sample_holds(memory_state):
    cell = T.compute_proposals(_losing_cell(20), state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["reason"]) == ("hold", "insufficient_events")


def test_significance_is_counted_in_events_not_rows(memory_state):
    # 60 losing rows on only 6 games: below the 40-event minimum however many rows.
    rows = [_order(i, won=False, clv=-2.0, event=f"g{i % 6}") for i in range(60)]
    cell = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert cell["evidence"]["events"] == 6
    assert cell["reason"] == "insufficient_events"


def test_ceiling_and_floor_bound_the_step(memory_state):
    at_ceiling = {"cells": {"kalshi|ncaaf|totals|regular": {"min_ev_pct": 6.0}}}
    cell = T.compute_proposals(_losing_cell(ev=6.5), state=at_ceiling, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["reason"], cell["min_ev_pct"]) == ("hold", "at_ceiling", 6.0)
    at_floor = {"cells": {"kalshi|ncaaf|totals|regular": {"min_ev_pct": 0.0}}}
    cell = T.compute_proposals(_winning_cell(ev=0.0), state=at_floor, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["reason"]) == ("hold", "at_floor")


def test_the_first_raise_from_a_zero_base_is_applied_not_refused(memory_state):
    # Production's base is 0.0 (2026-10-19). A raise from it must yield an
    # override `effective_min_ev_pct` honours in apply mode.
    rows = _losing_cell(ev=0.0)
    out = T.compute_proposals(rows, state={}, base_min_ev_pct=0.0)
    cell = out["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["min_ev_pct"]) == ("raise", 0.5)
    row = {"venue": "kalshi", "sport": "ncaaf", "market": "totals"}
    assert T.effective_min_ev_pct(row, base_min_ev_pct=0.0, selected_date="2026-10-10", state=out, mode="apply") == (0.5, "tuned_cell")


def test_band_anchors_where_the_cell_is_actually_cut_not_at_a_zero_base(memory_state):
    # Production 2026-10-19: base 0.0, but rows reach the ledger at EV ~2+ (other
    # gates bind first). Anchored at 0.0 the band [0, 1) is empty and nothing can
    # ever move; anchored at the effective cut it measures the rows a raise removes.
    rows = _losing_cell(ev=2.2)
    cell = T.compute_proposals(rows, state={}, base_min_ev_pct=0.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert cell["effective_cut_pct"] == 2.2
    assert cell["marginal"]["band"] == [2.2, 3.2]
    assert (cell["action"], cell["min_ev_pct"]) == ("raise", 2.7)


def test_no_lower_when_another_gate_is_binding(memory_state):
    rows = _winning_cell(ev=2.2)
    cell = T.compute_proposals(rows, state={}, base_min_ev_pct=0.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["reason"], cell["min_ev_pct"]) == ("hold", "cut_not_binding", None)


def test_cooldown_needs_new_events_before_a_second_move(memory_state):
    rows = _losing_cell()
    first = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)
    second = T.compute_proposals(rows, state=first, base_min_ev_pct=2.0)
    cell = second["cells"]["kalshi|ncaaf|totals|regular"]
    assert (cell["action"], cell["reason"], cell["min_ev_pct"]) == ("hold", "cooldown_awaiting_new_events", 2.5)
    more = rows + [_order(100 + i, won=(i % 5 == 0), clv=-2.5 - (i % 2), date="2026-10-11", ev=2.5) for i in range(45)]
    third = T.compute_proposals(more, state=second, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert (third["action"], third["min_ev_pct"]) == ("raise", 3.0)


def test_other_book_close_does_not_count_by_default(memory_state):
    rows = [_order(i, won=(i % 5 == 0), clv=-3.0, scope="different_book_close") for i in range(60)]
    cell = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert cell["reason"] == "insufficient_clv_events"


# --- cells -------------------------------------------------------------------


def test_phases_are_never_pooled_and_unknown_is_not_regular():
    assert T.cell_key("kalshi", "nba", "h2h", "2026-10-15").endswith("|preseason")
    assert T.cell_key("kalshi", "nba", "h2h", "2026-10-25").endswith("|regular")
    assert T.cell_key("kalshi", "mlb", "batter_hits", "2026-12-15") is None  # off-season
    assert T.cell_key("kalshi", "curling", "h2h", "2026-10-15") is None  # no calendar
    assert season_phase("soccer", "2026-07-01") == "regular"


def test_sportsbook_rows_and_rows_without_ev_are_out_of_scope(memory_state):
    rows = _losing_cell() + [_order(500, won=True, clv=1.0, venue="paper:prophetx")]
    rebuilt = _order(501, won=True, clv=None, venue="kalshi")
    rebuilt["ev_pct"] = None
    out = T.compute_proposals(rows + [rebuilt], state={}, base_min_ev_pct=2.0)
    assert out["skipped"] == {"no_ev_pct": 1, "venue_not_tuned": 1}
    assert set(out["cells"]) == {"kalshi|ncaaf|totals|regular"}


def test_a_paper_twin_of_a_filled_live_bet_counts_once():
    # Since 1006cb75 paper books record alongside live: the bet live placed on
    # kalshi has a paper:kalshi twin with the same position_key and date.
    live = _order(1, won=True, clv=1.0, venue="kalshi")
    twin = _order(2, won=True, clv=1.0, venue="paper:kalshi")
    loner = _order(3, won=False, clv=-1.0, venue="paper:kalshi")
    other_day = _order(4, won=False, clv=-1.0, venue="paper:kalshi", date="2026-10-11")
    live["position_key"] = twin["position_key"] = other_day["position_key"] = "pk-twin"
    loner["position_key"] = "pk-loner"

    cells, skipped = T.collect_cells([live, twin], evidence_modes=("live", "paper"))
    assert cells == {"kalshi|ncaaf|totals|regular": [live]}
    assert skipped == {"paper_twin_of_live": 1}

    cells, skipped = T.collect_cells([live, twin, loner, other_day], evidence_modes=("live", "paper"))
    # The loner has no live twin; other_day shares the key on a different date.
    assert cells == {"kalshi|ncaaf|totals|regular": [live, loner, other_day]}
    assert skipped == {"paper_twin_of_live": 1}

    # With paper-only evidence the twin is the only copy, so it stays.
    cells, skipped = T.collect_cells([live, twin], evidence_modes=("paper",))
    assert cells == {"kalshi|ncaaf|totals|regular": [twin]}
    assert skipped == {"mode_not_in_evidence": 1}

    # A live order that never filled is not the real bet; the paper row stays.
    unfilled = dict(live, status="rejected")
    cells, skipped = T.collect_cells([unfilled, twin], evidence_modes=("live", "paper"))
    assert cells == {"kalshi|ncaaf|totals|regular": [twin]}
    assert skipped == {"not_settled": 1}


def _sim_sized_cell():
    # One bet per game. 70% of bets win (+0.9 a unit) at a $10 EV-only stake;
    # the 30% that lose carried $100 because the sim added $90 on top
    # (sim_share_of_stake 0.9). Per bet: +33% flat. Per dollar: deeply negative.
    rows = []
    for i in range(60):
        loses = i % 10 < 3
        stake = 100.0 if loses else 10.0
        row = _order(i, won=not loses, clv=-2.0 - (i % 3) * 0.5, stake=stake)
        row["pnl_dollars"] = -stake if loses else 0.9 * stake
        row["sim_share_of_stake"] = 0.9 if loses else 0.0
        rows.append(row)
    return rows


def test_dollar_basis_t_sign_matches_stake_weighted_roi():
    ev = T.cell_evidence(_sim_sized_cell(), trailing_events=150, clv_scopes=("same_book",), roi_basis="dollars")
    assert ev["roi_basis"] == "dollars"
    assert ev["roi_pct"] < 0 and ev["roi_t"] < 0
    assert ev["roi_pct"] == ev["dollar_roi_pct"]


def test_the_cut_is_graded_per_bet_not_on_the_sims_sizing(memory_state, monkeypatch):
    # findings_2026-10-19_ev_overstatement_decomp: 58-69% of each band's dollars are
    # sim-added stake the sim has not earned (w = -0.27). A cell lost only by that
    # stake must not have its EV cut raised: every bet in it was worth taking.
    rows = _sim_sized_cell()
    flat = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert flat["marginal"]["roi_basis"] == "flat"
    assert flat["marginal"]["roi_pct"] > 0 and flat["marginal"]["dollar_roi_pct"] < 0
    assert flat["marginal"]["ev_only_roi_pct"] > 0  # the EV-only dollars won too
    assert flat["action"] != T.ACTION_RAISE

    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER_ROI_BASIS", "dollars")
    dollars = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"]["kalshi|ncaaf|totals|regular"]
    assert dollars["action"] == T.ACTION_RAISE  # reachability: the basis switch changes the decision


def test_roi_basis_absent_or_unknown_is_flat(monkeypatch):
    monkeypatch.delenv("SYNDICATE_MIN_EV_TUNER_ROI_BASIS", raising=False)
    assert T.roi_basis() == "flat"
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER_ROI_BASIS", "dollar")
    assert T.roi_basis() == "flat"


# --- the worker hook ---------------------------------------------------------


def test_hook_runs_once_per_day_after_the_hour(memory_state, monkeypatch):
    calls = []
    monkeypatch.setattr(T, "run_nightly", lambda now=None: calls.append(now) or {"ran": True})
    early = datetime(2026, 10, 20, 11, 59, tzinfo=timezone.utc)
    assert T.maybe_run_nightly(now=early)["reason"] == "before_run_hour"
    assert T.maybe_run_nightly(now=NOW) == {"ran": True}
    assert T.maybe_run_nightly(now=NOW)["reason"] == "already_ran_today"
    assert len(calls) == 1


def test_persisted_date_stops_a_second_run_after_restart(memory_state):
    T.run_nightly(orders_loader=_losing_cell, now=NOW)
    again = T.run_nightly(orders_loader=_losing_cell, now=NOW)
    assert again == {"ran": False, "reason": "already_ran_today"}


def test_audit_records_each_move(memory_state, capsys):
    T.run_nightly(orders_loader=_losing_cell, now=NOW)
    audit = memory_state["s"]["audit"]
    assert len(audit) == 1
    assert audit[0]["cell"] == "kalshi|ncaaf|totals|regular"
    assert (audit[0]["from"], audit[0]["to"], audit[0]["mode"]) == (2.0, 2.5, "shadow")
    out = capsys.readouterr().out
    assert "MIN_EV_TUNER mode=shadow" in out and "MIN_EV_TUNER_MOVE" in out


def test_a_loader_failure_never_raises(memory_state, capsys):
    def boom():
        raise RuntimeError("ledger down")

    result = T.run_nightly(orders_loader=boom, now=NOW)
    assert result["reason"] == "error"
    assert "MIN_EV_TUNER_FAILED" in capsys.readouterr().out
    assert "s" not in memory_state
