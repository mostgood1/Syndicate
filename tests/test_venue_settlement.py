"""Settling from the venue, and every way that could quietly be wrong.

The point of this module is to DELETE an estimator: `paper_settlement` grades
against a status we resolve, and its own record shows 80 of 171 orders on one
date refusing with `unmapped_market`. So the tests that matter are not about
arithmetic -- they are about the three ways an authoritative source can be
turned back into a guess:

1. Grading from OUR `side`/`line` instead of the venue's statement of what we
   actually held. That reintroduces the exact join this replaces.
2. Reading a cumulative field as an event. `UserPosition.realized` is a running
   total; taking `afterPosition.realized` alone reports a position's whole
   history as one settlement.
3. Splitting a MARKET's P&L across several of our orders on it. The outcome is
   shared, the money is not.

Plus the contract this shares with the ledger: an order carrying an outcome is
never re-graded, because this writes into a money record.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import venue_settlement as vs


# ---------------------------------------------------------------------------
# Kalshi grading
# ---------------------------------------------------------------------------


def _k(**over):
    row = {
        "ticker": "KXNFLGAME-26AUG27-NE",
        "market_result": "yes",
        "yes_count_fp": "10.00",
        "no_count_fp": "0.00",
        "yes_total_cost_dollars": "5.4000",
        "no_total_cost_dollars": "0.0000",
        "revenue": 1000,
        "fee_cost": "0.3400",
        "settled_time": "2026-08-27T03:10:00Z",
    }
    row.update(over)
    return row


def test_a_held_yes_on_a_yes_market_is_a_win_with_the_venues_own_pnl():
    """P&L is revenue/100 - cost - fees, all three from the venue. Ten winning
    contracts pay $10.00 against $5.40 cost and $0.34 fees."""
    v = vs.grade_kalshi_settlement(_k())
    assert v["graded"] is True
    assert v["outcome"] == "won"
    assert v["pnl_dollars"] == pytest.approx(4.26)
    assert v["held_side"] == "yes"


def test_a_held_yes_on_a_no_market_is_a_loss():
    v = vs.grade_kalshi_settlement(_k(market_result="no", revenue=0))
    assert v["outcome"] == "lost"
    # Lost the cost basis and still paid the fee.
    assert v["pnl_dollars"] == pytest.approx(-5.74)


def test_the_outcome_comes_from_what_we_HELD_not_from_our_own_side_field():
    """The whole reason this module exists. A row where we held NO and the
    market resolved NO is a WIN, and nothing about our order's `side`/`line`
    is consulted to reach that."""
    v = vs.grade_kalshi_settlement(
        _k(market_result="no", yes_count_fp="0", no_count_fp="12", revenue=1200,
           yes_total_cost_dollars="0", no_total_cost_dollars="7.20")
    )
    assert v["outcome"] == "won"
    assert v["held_side"] == "no"


def test_a_cost_basis_sent_as_a_string_is_not_dropped():
    """Both venues send money as decimal strings in places. A float-only parse
    would silently treat cost as zero and report the gross payout as profit --
    a settled bet that looks twice as good as it was."""
    v = vs.grade_kalshi_settlement(_k(yes_total_cost_dollars="5.4000"))
    assert v["pnl_dollars"] == pytest.approx(4.26)
    assert vs._num("5.4000") == 5.4


def test_a_scalar_market_is_refused_by_name_rather_than_guessed():
    """`scalar` settles at a VALUE, not a side. Nothing here trades one, and
    inventing a side would be a coin flip recorded as a fact."""
    v = vs.grade_kalshi_settlement(_k(market_result="scalar"))
    assert v["graded"] is False
    assert "scalar" in v["reason"]


def test_holding_both_sides_refuses_rather_than_picking_one():
    v = vs.grade_kalshi_settlement(_k(yes_count_fp="5", no_count_fp="5"))
    assert v["graded"] is False
    assert v["reason"] == "both_sides_held"


def test_a_settlement_on_a_market_we_held_nothing_in_is_refused():
    v = vs.grade_kalshi_settlement(_k(yes_count_fp="0", no_count_fp="0"))
    assert v["graded"] is False
    assert v["reason"] == "no_position_held"


# ---------------------------------------------------------------------------
# Polymarket grading
# ---------------------------------------------------------------------------


def _p(before=3.0, after=12.6, side="POSITION_RESOLUTION_SIDE_LONG"):
    return {
        "marketSlug": "asc-nfl-ne-cle-2026-08-27",
        "side": side,
        "updateTime": "2026-08-27T03:10:00Z",
        "beforePosition": {"realized": {"value": str(before), "currency": "USD"}},
        "afterPosition": {"realized": {"value": str(after), "currency": "USD"}},
    }


def test_the_realized_DELTA_is_the_settlement_not_the_running_total():
    """`realized` is cumulative. Reading `afterPosition.realized` alone would
    report a position's entire trading history as this one settlement -- here
    $12.60 instead of the $9.60 this event actually booked."""
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=12.6))
    assert v["graded"] is True
    assert v["pnl_dollars"] == pytest.approx(9.6)
    assert v["outcome"] == "won"


def test_a_negative_realized_delta_is_a_loss():
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=-6.6))
    assert v["outcome"] == "lost"
    assert v["pnl_dollars"] == pytest.approx(-9.6)


def test_the_venues_own_word_for_a_void_is_a_push():
    v = vs.grade_polymarket_resolution(_p(before=3.0, after=3.0, side="POSITION_RESOLUTION_SIDE_NEUTRAL"))
    assert v["outcome"] == "push"


def test_a_resolution_with_no_realized_amount_is_refused():
    row = _p()
    row["afterPosition"] = {}
    v = vs.grade_polymarket_resolution(row)
    assert v["graded"] is False
    assert v["reason"] == "no_realized_amount"


# ---------------------------------------------------------------------------
# The join and the write
# ---------------------------------------------------------------------------


def _order(**over):
    order = {
        "idempotency_key": "k1",
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": "KXNFLGAME-26AUG27-NE",
        "status": "filled",
        "fill_stake_dollars": 5.40,
        "selected_date": "2026-08-26",
    }
    order.update(over)
    return order


@pytest.fixture
def ledger(monkeypatch):
    """An in-memory ledger, so no test touches disk or a venue."""
    state = {"orders": []}
    persisted = {"count": 0}

    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: persisted.__setitem__("count", persisted["count"] + 1))
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([], None))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    state["_persisted"] = persisted
    return state


def _kalshi_rows(monkeypatch, rows):
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: (rows, None))


def test_off_is_not_on_a_matching_settlement_grades_and_a_missing_one_does_not(ledger, monkeypatch):
    """Reachability before correctness. With no settlement the order is
    untouched; with one it gains an outcome. If both pass, the join is inert."""
    ledger["orders"] = [_order()]

    before = vs.settle_from_venue()
    assert before["settled"] == 0
    assert before["awaiting"] == 1
    assert "outcome" not in ledger["orders"][0]

    _kalshi_rows(monkeypatch, [_k()])
    after = vs.settle_from_venue()
    assert after["settled"] == 1
    assert ledger["orders"][0]["outcome"] == "won"
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(4.26)


def test_a_venue_settled_row_is_marked_as_authoritative(ledger, monkeypatch):
    """`settled_by` is what keeps an authoritative outcome distinguishable from
    an inferred one. An evaluation pass that cannot tell them apart is one that
    will eventually average them."""
    ledger["orders"] = [_order()]
    _kalshi_rows(monkeypatch, [_k()])
    vs.settle_from_venue()
    assert ledger["orders"][0]["settled_by"] == "venue"
    assert ledger["orders"][0]["settled_at_venue"] == "2026-08-27T03:10:00Z"


def test_an_already_settled_order_is_never_regraded(ledger, monkeypatch):
    """The contract `settle_orders` keeps, and for the same reason: re-running
    must not be able to change a bet that is already settled."""
    ledger["orders"] = [_order(outcome="lost", pnl_dollars=-5.40)]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 0
    assert result["already"] == 1
    assert ledger["orders"][0]["outcome"] == "lost"


def test_one_market_with_two_orders_shares_the_outcome_and_withholds_the_pnl(ledger, monkeypatch):
    """The market resolved one way for everyone, so the outcome applies to
    both. The row states the MARKET's P&L; splitting it across orders would be
    an invented number wearing an exact one's clothes."""
    ledger["orders"] = [_order(idempotency_key="a"), _order(idempotency_key="b")]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 2
    assert result["pnl_unattributed"] == 2
    assert all(o["outcome"] == "won" for o in ledger["orders"])
    assert all("pnl_dollars" not in o for o in ledger["orders"])


def test_a_settlement_matching_no_order_is_counted_not_dropped(ledger, monkeypatch):
    """"Nothing settled" and "we cannot see what settled" are opposite facts."""
    ledger["orders"] = [_order(venue_ticker="SOMETHING-ELSE")]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["unjoinable"] == 1
    assert result["awaiting"] == 1
    assert result["settled"] == 0


def test_a_paper_order_is_never_touched(ledger, monkeypatch):
    """This grades the LIVE book. A paper row settled from the live venue would
    put a real outcome under a banner promising no money moved."""
    ledger["orders"] = [_order(mode="paper")]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue()
    assert result["settled"] == 0
    assert "outcome" not in ledger["orders"][0]


def test_a_rejected_order_has_no_position_to_settle(ledger, monkeypatch):
    ledger["orders"] = [_order(status="rejected", error="http_404 market_not_found")]
    _kalshi_rows(monkeypatch, [_k()])
    assert vs.settle_from_venue()["settled"] == 0


def test_the_join_survives_a_case_difference_in_the_ticker(ledger, monkeypatch):
    ledger["orders"] = [_order(venue_ticker="kxnflgame-26aug27-ne")]
    _kalshi_rows(monkeypatch, [_k()])
    assert vs.settle_from_venue()["settled"] == 1


def test_a_venue_error_is_reported_and_does_not_stop_the_other_venue(ledger, monkeypatch):
    """Settlement runs inside the execution tick. One venue being down must not
    cost the other's settlements, and must never stop orders being placed."""
    ledger["orders"] = [_order(venue="polymarket", venue_ticker="asc-nfl-ne-cle-2026-08-27")]
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([], "http_401: bad key"))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([_p()], None))
    result = vs.settle_from_venue()
    assert result["errors"]["kalshi"].startswith("http_401")
    assert result["settled"] == 1
    assert ledger["orders"][0]["outcome"] == "won"


def test_nothing_is_persisted_when_nothing_graded(ledger, monkeypatch):
    """A write to a money record for no reason is a write that can fail for no
    reason."""
    ledger["orders"] = [_order()]
    vs.settle_from_venue()
    assert ledger["_persisted"]["count"] == 0
    _kalshi_rows(monkeypatch, [_k()])
    vs.settle_from_venue()
    assert ledger["_persisted"]["count"] == 1


def test_dry_run_grades_in_memory_without_persisting(ledger, monkeypatch):
    ledger["orders"] = [_order()]
    _kalshi_rows(monkeypatch, [_k()])
    result = vs.settle_from_venue(dry_run=True)
    assert result["settled"] == 1
    assert ledger["_persisted"]["count"] == 0
