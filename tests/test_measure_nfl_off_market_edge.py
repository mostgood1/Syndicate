"""Unit tests for scripts/measure_nfl_off_market_edge.py -- the per-line edge definitions and settlement."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "measure_nfl_off_market_edge.py"
_spec = importlib.util.spec_from_file_location("nfl_off_market", _PATH)
om = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(om)  # type: ignore[union-attr]

# three books agree at -110/-110; "soft" hangs +120 on the over
BOOKS = {"a": {"over": -110, "under": -110}, "b": {"over": -110, "under": -110},
         "c": {"over": -110, "under": -110}, "soft": {"over": 120, "under": -150}}


def _bets(outcome="over", stale=None, books=BOOKS):
    return om.evaluate_group(books, outcome_side=outcome, gid="g1", kind="prop", meta={"season": 2024, "market": "x"},
                             stale_books=stale)


def test_median_already_ignores_one_outlier_when_the_others_agree():
    # three agreeing books: the board median is unmoved by the outlier, so board == leave-one-out
    rows = {(r["def"], r["side"]): r for r in _bets()}
    assert rows[("board", "over")]["book"] == "soft" and rows[("loo", "over")]["book"] == "soft"
    assert rows[("board", "over")]["fair"] == pytest.approx(0.5) == rows[("loo", "over")]["fair"]


def test_leave_one_out_differs_when_the_other_books_split():
    split = {"a": {"over": -110, "under": -110}, "b": {"over": 105, "under": -125},
             "soft": {"over": 120, "under": -150}}
    rows = {(r["def"], r["side"]): r for r in _bets(books=split)}
    # the outlier is the middle of three under the board definition, so it drags its own fair down
    assert rows[("loo", "over")]["fair"] > rows[("board", "over")]["fair"]
    assert rows[("loo", "over")]["ev"] > rows[("board", "over")]["ev"] > 0


def test_settlement_is_flat_one_unit_at_the_best_price():
    over = [r for r in _bets("over") if r["side"] == "over"]
    assert all(r["won"] and r["pnl"] == pytest.approx(1.2) for r in over)
    lost = [r for r in _bets("under") if r["side"] == "over"]
    assert all((not r["won"]) and r["pnl"] == -1.0 for r in lost)


def test_only_positive_claimed_ev_is_a_bet():
    assert not [r for r in _bets() if r["side"] == "under"]   # every under is at or below fair


def test_fresh_definition_drops_stale_books():
    rows = _bets(stale={"soft"})
    fresh = [r for r in rows if r["def"] == "fresh"]
    assert not fresh                                    # without the stale outlier there is no edge
    board = [r for r in rows if r["def"] == "board" and r["side"] == "over"]
    assert board and board[0]["best_stale"] is True


def test_needs_three_two_sided_books():
    thin = {"a": {"over": -110, "under": -110}, "soft": {"over": 120, "under": -150}}
    assert _bets(books=thin) == []
    assert om.evaluate_group(BOOKS, outcome_side=None, gid="g", kind="prop", meta={}) == []   # push / no result
