"""The fair's own noise shrinks a MARKET-ONLY edge by the number of books that form it.

Lane `published-negative-ev` `[2026-10-06, user "Size by book count"]`. Measured on 623 settled paper
orders: market-only edges on 1-2-book lines lost -22.6% (88% of the whole loss), monotone in books
quoting. Pre-registered rule: `ev - 5.0 / sqrt(books)` for admission and Kelly. A property of the
LINE; model-backed rows are untouched; unknown book count = one book.
"""
from __future__ import annotations

import math

import pytest

from syndicate.features.shared import portfolio_commit as pc

FAIR_ENV = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"
NOISE_ENV = "SYNDICATE_PORTFOLIO_FAIR_NOISE_PP"


def _row(books=None, ev=4.5, **over):
    quote = {"price": -110}
    if books is not None:
        quote["books_quoting"] = books
    row = {"sport": "ncaaf", "quote": quote, "ev_pct": ev, "score": {"price_reliability": 1.0}}
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _market_fair_on(monkeypatch):
    monkeypatch.setenv(FAIR_ENV, "ncaaf")
    monkeypatch.delenv(NOISE_ENV, raising=False)


def test_reachability_off_and_on_differ_on_the_real_sizing_path(monkeypatch):
    monkeypatch.setenv(NOISE_ENV, "0")
    off = pc.sizing_inputs_from_row(_row(books=2))[0]
    monkeypatch.delenv(NOISE_ENV)
    on = pc.sizing_inputs_from_row(_row(books=2))[0]
    assert off.model_probability == pytest.approx(off.market_fair_probability)
    assert on.model_probability < off.model_probability


def test_the_kelly_probability_is_the_fair_less_its_noise_in_probability_points():
    inputs = pc.sizing_inputs_from_row(_row(books=4, ev=4.5))[0]
    profit = 100 / 110
    penalty = 5.0 / math.sqrt(4)
    expected = ((4.5 - penalty) / 100 + 1) / (profit + 1)
    assert inputs.model_probability == pytest.approx(expected)


def test_a_thin_line_is_refused_at_admission_and_a_deep_one_is_not():
    assert pc._effective_ev_pct(_row(books=1, ev=4.5)) == pytest.approx(-0.5)
    assert pc._effective_ev_pct(_row(books=2, ev=4.5)) == pytest.approx(4.5 - 5 / math.sqrt(2))
    assert pc._effective_ev_pct(_row(books=8, ev=4.5)) == pytest.approx(4.5 - 5 / math.sqrt(8))
    assert pc._effective_ev_pct(_row(books=8, ev=4.5)) >= 2.0 > pc._effective_ev_pct(_row(books=2, ev=4.5))


def test_an_unknown_book_count_is_one_book_never_permissive():
    assert pc._fair_noise_penalty_pct(_row(books=None)) == pytest.approx(5.0)
    assert pc._fair_noise_penalty_pct(_row(books=0)) == pytest.approx(5.0)


def test_a_model_backed_row_is_untouched():
    row = _row(books=1, model_edge_pct=3.0, projection={})
    assert pc._fair_noise_penalty_pct(row) == 0.0
    assert pc._effective_ev_pct(row) == 4.5


def test_the_kill_switch_and_a_bad_value(monkeypatch):
    monkeypatch.setenv(NOISE_ENV, "0")
    assert pc._fair_noise_penalty_pct(_row(books=1)) == 0.0
    monkeypatch.setenv(NOISE_ENV, "nonsense")
    assert pc._fair_noise_penalty_pct(_row(books=1)) == pytest.approx(pc.FAIR_NOISE_PP_DEFAULT)
