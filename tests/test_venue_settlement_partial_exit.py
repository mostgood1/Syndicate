"""A PARTLY sold Kalshi entry settles through the exit-aware branch (todo #703,
lane kalshi-exit-path).

Kalshi books our close (`execution_exits.exit_order_body`) as a BUY of the
opposite leg, so a position partly sold settles with BOTH counts on its row and
`grade_kalshi_settlement` refuses it `both_sides_held`. MEASURED 2026-10-20 on
the fleet, `KXWNBAPTS-26OCT19ATLGS-GSKTHORNTON5-10`: 5 NO @ 0.90, 1 sold @ 0.87
-> `no_count_fp=5.00, yes_count_fp=1.00, market_result=no`, refused on every
pass. These tests pin:

1. that row grades through `_apply_exit_grade`, outcome from the exit's leg;
2. a both-sides row with NO exit (or a paper / unreconciled one) still refuses;
3. a both-sides row whose opposite count is not the exits' filled contracts
   still refuses, and so does a market where not every target was sold;
4. reachability: a real exits document on disk turns the refusal into a grade.
"""

from __future__ import annotations

import copy

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import venue_settlement as vs

TICKER = "KXWNBAPTS-26OCT19ATLGS-GSKTHORNTON5-10"
ENTRY = "ce69c6fa23fb5e89aa378b43"


def _row(**over):
    """The fleet's settlement row, verbatim but for the fields under test."""
    row = {
        "event_ticker": "KXWNBAPTS-26OCT19ATLGS",
        "ticker": TICKER,
        "market_result": "no",
        "no_count_fp": "5.00",
        "no_total_cost_dollars": "4.500000",
        "yes_count_fp": "1.00",
        "yes_total_cost_dollars": "0.130000",
        "revenue": 400,
        "fee_cost": "0.039500",
        "settled_time": "2026-10-20T02:30:56.780272Z",
        "value": 0,
    }
    row.update(over)
    return row


def _order(**over):
    order = {
        "idempotency_key": ENTRY,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": TICKER,
        "status": "filled",
        "side": "under",
        "line": 9.5,
        "fill_price": 0.9,
        "fill_stake_dollars": 4.5,
        "fees_dollars": 0.0315,
    }
    order.update(over)
    return order


def _exit(entry_key=ENTRY, **over):
    row = {
        "entry_key": entry_key,
        "exit_key": ex.exit_idempotency_key(entry_key),
        "entry_mode": "live",
        "mode": ex.EXIT_LIVE,
        "status": ex.EXIT_FILLED,
        "ticker": TICKER,
        "leg": "no",
        "contracts": 5.0,
        "entry_price": 0.9,
        "entry_fee_dollars": 0.0315,
        "requested_contracts": 1,
        "filled_contracts": 1,
        "fill_price": 0.87,
        "exit_fee_dollars": 0.008,
    }
    row.update(over)
    return row


def _exits_state(*rows):
    return {"version": 1, "watch": {}, "exits": {r["exit_key"]: r for r in rows}}


@pytest.fixture
def ledger(monkeypatch):
    state = {"orders": [], "_exits": _exits_state()}
    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    monkeypatch.setattr(ex, "load_state", lambda: copy.deepcopy(state["_exits"]))

    def _no_market_read(tickers):
        raise AssertionError("a partly sold entry must grade from its settlement row, not the market read")

    monkeypatch.setattr(vs, "fetch_kalshi_market_results", _no_market_read)
    return state


def _settle(ledger, monkeypatch, orders, row, exits_state):
    ledger["orders"] = [copy.deepcopy(o) for o in orders]
    ledger["_exits"] = exits_state
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([row], None))
    return vs.settle_from_venue(), ledger["orders"]


# ---------------------------------------------------------------------------
# 1. The partial sale grades
# ---------------------------------------------------------------------------


def test_the_grader_alone_still_refuses_the_row():
    """The fix is in settle_from_venue, not in the grader: the row, read by
    itself, IS two-sided and must keep saying so."""
    assert vs.grade_kalshi_settlement(_row()) == {"graded": False, "reason": "both_sides_held"}


def test_a_partly_sold_winner_grades_through_the_exit_branch(ledger, monkeypatch):
    """1 sold @ 0.87 (fee 0.008) + 4 settle NO at $1 - 4.50 - 0.0315 = 0.3305.

    The venue's own figure (revenue 4.00 - cost 4.63 - fees 0.0395 = -0.6695)
    is NOT this entry's P&L: the netted pair paid its $1 at trade time."""
    result, orders = _settle(ledger, monkeypatch, [_order()], _row(), _exits_state(_exit()))
    o = orders[0]
    assert result["refused"] == {}
    assert result["exit_adjusted"] == 1 and result["settled"] == 1
    assert result["exit_partial_both_sides"] == 1
    assert result["awaiting"] == 0
    assert o["outcome"] == "won"
    assert o["pnl_dollars"] == pytest.approx(0.3305)
    assert o["settled_by"] == "venue"
    assert o["held_side"] == "no"
    assert o["settled_at_venue"] == "2026-10-20T02:30:56.780272Z"
    applied = o["exit_applied"]
    assert applied["contracts_sold"] == 1 and applied["contracts_settled"] == 4
    assert applied["exit_key"] == ex.exit_idempotency_key(ENTRY)
    assert "venue_settlement_pnl_dollars" not in applied


def test_a_partly_sold_loser_keeps_only_the_sale(ledger, monkeypatch):
    """Market YES: 0.87 - 0.008 + 0 - 4.50 - 0.0315 = -3.6695."""
    _r, orders = _settle(
        ledger, monkeypatch, [_order()], _row(market_result="yes", revenue=100), _exits_state(_exit())
    )
    assert orders[0]["outcome"] == "lost"
    assert orders[0]["pnl_dollars"] == pytest.approx(-3.6695)


def test_a_yes_holding_partly_sold_reads_the_no_count(ledger, monkeypatch):
    """The mirror image: a YES holding is closed by buying NO."""
    row = _row(market_result="yes", yes_count_fp="5.00", no_count_fp="2.00")
    _r, orders = _settle(
        ledger,
        monkeypatch,
        [_order(side="over")],
        row,
        _exits_state(_exit(leg="yes", filled_contracts=2, fill_price=0.95)),
    )
    # 2*0.95 - 0.008 + 3*1 - 4.50 - 0.0315 = 0.3605
    assert orders[0]["outcome"] == "won"
    assert orders[0]["pnl_dollars"] == pytest.approx(0.3605)


# ---------------------------------------------------------------------------
# 2./3. A genuine both-sides holding still refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exits_state",
    [
        _exits_state(),  # no exit at all
        _exits_state(_exit(mode="paper")),  # a paper exit is counterfactual
        _exits_state(_exit(status=ex.EXIT_REJECTED)),  # nothing traded
        _exits_state(_exit(entry_key="b" * 24)),  # another entry's exit
    ],
    ids=["no_exit", "paper_exit", "rejected_exit", "other_entry"],
)
def test_a_both_sides_row_with_no_live_sale_still_refuses(ledger, monkeypatch, exits_state):
    result, orders = _settle(ledger, monkeypatch, [_order()], _row(), exits_state)
    assert result["refused"] == {"both_sides_held": 1}
    assert "exit_partial_both_sides" not in result
    assert not orders[0].get("outcome")


@pytest.mark.parametrize("status", ["submitted", "failed"])
def test_a_both_sides_row_with_an_unreconciled_exit_still_refuses(ledger, monkeypatch, status):
    result, orders = _settle(ledger, monkeypatch, [_order()], _row(), _exits_state(_exit(status=status)))
    assert result["refused"] == {"both_sides_held": 1}
    assert not orders[0].get("outcome")


@pytest.mark.parametrize(
    "row, exit_over",
    [
        (_row(yes_count_fp="2.00"), {}),  # venue holds more YES than we sold
        (_row(yes_count_fp="1.00"), {"filled_contracts": 2}),  # sold more than the row shows
        # opposite count matches the sale, but we hold fewer than we sold
        (_row(no_count_fp="1.00", yes_count_fp="4.00"), {"filled_contracts": 4}),
        (_row(yes_count_fp="1.00"), {"leg": "yes"}),  # exit says YES held; the NO count is 5
        (_row(yes_count_fp="1.00"), {"leg": ""}),  # leg unreadable
    ],
    ids=["extra_opposite", "oversold", "count_on_our_leg", "leg_mismatch", "leg_absent"],
)
def test_a_both_sides_row_whose_counts_do_not_match_the_exit_still_refuses(ledger, monkeypatch, row, exit_over):
    result, orders = _settle(ledger, monkeypatch, [_order()], row, _exits_state(_exit(**exit_over)))
    assert result["refused"] == {"both_sides_held": 1}
    assert not orders[0].get("outcome")


def test_a_market_where_not_every_target_was_sold_still_refuses(ledger, monkeypatch):
    """A second, UNSOLD entry on the same market: the row cannot be split
    between them, so nothing on it grades."""
    orders = [_order(), _order(idempotency_key="c" * 24, fill_stake_dollars=1.8)]
    result, graded = _settle(ledger, monkeypatch, orders, _row(no_count_fp="7.00"), _exits_state(_exit()))
    assert result["refused"] == {"both_sides_held": 1}
    assert not any(o.get("outcome") for o in graded)


def test_two_sold_targets_must_sum_to_the_opposite_count(ledger, monkeypatch):
    second = "d" * 24
    orders = [_order(), _order(idempotency_key=second)]
    exits = _exits_state(_exit(), _exit(entry_key=second, filled_contracts=2))
    result, graded = _settle(ledger, monkeypatch, orders, _row(no_count_fp="10.00", yes_count_fp="3.00"), exits)
    assert result["exit_adjusted"] == 2 and result["refused"] == {}
    assert [o["outcome"] for o in graded] == ["won", "won"]

    result, graded = _settle(ledger, monkeypatch, orders, _row(no_count_fp="10.00", yes_count_fp="2.00"), exits)
    assert result["refused"] == {"both_sides_held": 1}
    assert not any(o.get("outcome") for o in graded)


# ---------------------------------------------------------------------------
# 4. Reachability: the real document on disk
# ---------------------------------------------------------------------------


def test_reachability_a_real_exits_document_turns_the_refusal_into_a_grade(ledger, monkeypatch, tmp_path):
    """off != on through the REAL `load_state`/`_persist` pair: the same ledger
    and the fleet's settlement row refuse with no exit on disk and grade once
    the exit tick's own writer has put the filled live exit there."""
    monkeypatch.undo()
    import syndicate.features.shared.execution_ledger as led

    path = tmp_path / "execution_exits.json"
    monkeypatch.setattr(ex, "exits_path", lambda: path)
    state = {"orders": [_order()]}
    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([_row()], None))

    off = vs.settle_from_venue()
    assert off["refused"] == {"both_sides_held": 1}
    assert off["awaiting"] == 1
    assert "outcome" not in state["orders"][0]

    ex._persist(_exits_state(_exit()))
    assert path.exists()
    on = vs.settle_from_venue()
    assert on["refused"] == {}
    assert on["exit_adjusted"] == 1 and on["awaiting"] == 0
    assert state["orders"][0]["outcome"] == "won"
    assert state["orders"][0]["pnl_dollars"] == pytest.approx(0.3305)
