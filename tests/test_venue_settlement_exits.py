"""Settlement that knows a position was SOLD first (lane kalshi-exit-settlement).

`execution_exits` can sell a held Kalshi contract before the market settles.
Kalshi's settlement row then describes only what was still held -- the
remainder, or nothing -- so grading the entry from that row alone would book
hold-to-settle money for contracts we no longer owned. These tests pin:

1. NO EXIT, NO CHANGE: an entry with no exit (or only a PAPER exit, which is
   counterfactual) grades byte-for-byte as it did before exits existed.
2. A FILLED LIVE exit books sale proceeds - entry cost - both fees for the sold
   contracts, plus settlement on the unsold remainder only.
3. A live exit whose fate is unknown DEFERS the grade; an unreadable exit
   document defers every Kalshi grade.
4. Reachability: a real `execution_exits.json` on disk changes the grade
   (off != on), through the real `load_state` and `settle_from_venue`.
"""

from __future__ import annotations

import copy

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import venue_settlement as vs

TICKER = "KXNFLGAME-26AUG27-NE"


def _k(**over):
    row = {
        "ticker": TICKER,
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


def _order(**over):
    order = {
        "idempotency_key": "a" * 24,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": TICKER,
        "status": "filled",
        "side": "over",
        "fill_price": 0.54,
        "fill_stake_dollars": 5.40,  # 10 contracts at 54c
        "fees_dollars": 0.10,
        "selected_date": "2026-08-26",
    }
    order.update(over)
    return order


def _exit(entry_key="a" * 24, **over):
    row = {
        "entry_key": entry_key,
        "exit_key": ex.exit_idempotency_key(entry_key),
        "entry_mode": "live",
        "mode": ex.EXIT_LIVE,
        "status": ex.EXIT_FILLED,
        "ticker": TICKER,
        "leg": "yes",
        "contracts": 10.0,
        "entry_price": 0.54,
        "entry_fee_dollars": 0.10,
        "requested_contracts": 10,
        "filled_contracts": 10,
        "fill_price": 0.80,
        "exit_fee_dollars": 0.12,
    }
    row.update(over)
    return row


def _exits_state(*rows):
    return {"version": 1, "watch": {}, "exits": {r["exit_key"]: r for r in rows}}


@pytest.fixture
def ledger(monkeypatch):
    """In-memory ledger and exits document; no venue, no disk."""
    state = {"orders": []}
    exits = {"state": _exits_state()}

    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([], None))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    monkeypatch.setattr(ex, "load_state", lambda: copy.deepcopy(exits["state"]))

    def _no_market_read(tickers):
        raise AssertionError("the market-result read must only run for a position sold to zero")

    monkeypatch.setattr(vs, "fetch_kalshi_market_results", _no_market_read)
    state["_exits"] = exits
    return state


def _rows(monkeypatch, rows):
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: (rows, None))


def _graded(ledger, monkeypatch, orders, rows, exits_state=None):
    ledger["orders"] = [copy.deepcopy(o) for o in orders]
    if exits_state is not None:
        ledger["_exits"]["state"] = exits_state
    _rows(monkeypatch, rows)
    result = vs.settle_from_venue()
    return result, ledger["orders"]


def _without_clock(orders):
    return [{k: v for k, v in o.items() if k != "graded_at"} for o in orders]


# ---------------------------------------------------------------------------
# 1. No exit, no change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "orders",
    [
        [_order()],  # one order: the venue's own P&L
        [  # two orders on one side: each derived from its own fill
            _order(idempotency_key="a" * 24, fill_stake_dollars=4.0, fill_price=0.40),
            _order(idempotency_key="b" * 24, fill_stake_dollars=2.0, fill_price=0.50),
        ],
    ],
)
def test_an_entry_with_no_exit_grades_exactly_as_before(ledger, monkeypatch, orders):
    """Baseline: no exits document at all. Then: a document holding a PAPER exit
    for this very entry, a DEAD and a REJECTED live exit, and a filled live exit
    for some OTHER entry. None of them may move a single field."""
    _r0, baseline = _graded(ledger, monkeypatch, orders, [_k()], _exits_state())
    noise = _exits_state(
        _exit(mode=ex.EXIT_PAPER, status=ex.EXIT_PAPER_FILLED, realized_pnl_dollars=2.0),
        _exit(entry_key="b" * 24, status=ex.EXIT_DEAD, filled_contracts=0),
        _exit(entry_key="c" * 24),
    )
    # The paper row and a live row cannot share a key, so the DEAD/REJECTED
    # case for entry "a" runs separately below.
    _r1, with_noise = _graded(ledger, monkeypatch, orders, [_k()], noise)
    assert _without_clock(with_noise) == _without_clock(baseline)
    assert _r1["exit_adjusted"] == 0 and _r1["exit_deferred"] == 0

    for status in (ex.EXIT_DEAD, ex.EXIT_REJECTED):
        _r2, dead = _graded(
            ledger, monkeypatch, orders, [_k()], _exits_state(_exit(status=status, filled_contracts=0))
        )
        assert _without_clock(dead) == _without_clock(baseline), status


def test_the_no_exit_baseline_is_the_venues_own_pnl(ledger, monkeypatch):
    """Anchor the parity test to the pre-existing number, so 'identical' cannot
    mean 'identically wrong'."""
    _r, orders = _graded(ledger, monkeypatch, [_order()], [_k()], _exits_state())
    assert orders[0]["outcome"] == "won"
    assert orders[0]["pnl_dollars"] == pytest.approx(4.26)
    assert "exit_applied" not in orders[0]


def test_a_paper_exit_never_changes_the_grade(ledger, monkeypatch):
    """Paper exits are counterfactual: the venue still holds every contract.
    A paper 'sale' at 80c on a market that then resolved NO must still grade as
    the full hold-to-settle loss."""
    row = _k(market_result="no", revenue=0)
    _r0, baseline = _graded(ledger, monkeypatch, [_order()], [row], _exits_state())
    paper = _exits_state(_exit(mode=ex.EXIT_PAPER, status=ex.EXIT_PAPER_FILLED, realized_pnl_dollars=2.38))
    _r, orders = _graded(ledger, monkeypatch, [_order()], [row], paper)
    assert _without_clock(orders) == _without_clock(baseline)
    assert orders[0]["outcome"] == "lost"
    assert orders[0]["pnl_dollars"] < 0  # the full loss, not the paper sale's +2.38
    assert "exit_applied" not in orders[0]


# ---------------------------------------------------------------------------
# 2. A filled live exit
# ---------------------------------------------------------------------------


def test_a_fully_sold_entry_books_the_sale_not_the_settlement(ledger, monkeypatch):
    """Sold all 10 at 80c. Kalshi's row holds nothing (`no_position_held`) and
    the market went NO. Hold-to-settle would say -5.74; the money actually made
    is 10*0.80 - 0.12 exit fee - 5.40 cost - 0.10 entry fee = +2.38."""
    row = _k(market_result="no", yes_count_fp="0.00", yes_total_cost_dollars="0", revenue=0, fee_cost="0")
    result, orders = _graded(ledger, monkeypatch, [_order()], [row], _exits_state(_exit()))
    o = orders[0]
    assert result["exit_adjusted"] == 1 and result["settled"] == 1
    assert o["outcome"] == "lost"  # the MARKET's result, from the leg we held
    assert o["held_side"] == "yes"
    assert o["settled_by"] == "venue"
    assert o["pnl_dollars"] == pytest.approx(2.38)
    applied = o["exit_applied"]
    assert applied["contracts_sold"] == 10 and applied["contracts_settled"] == 0
    assert applied["exit_key"] == ex.exit_idempotency_key("a" * 24)
    assert o["fees_dollars"] == 0.10  # the entry fee is not overwritten


def test_a_partly_sold_winner_settles_only_the_remainder(ledger, monkeypatch):
    """Sold 4 of 10 at 80c (fee 0.05); the venue settles the other 6 YES.
    pnl = 4*0.80 - 0.05 + 6*1.00 - 5.40 - 0.10 = 3.65. The venue's own figure
    covers the 6 held and is kept for audit only."""
    row = _k(yes_count_fp="6.00", yes_total_cost_dollars="3.2400", revenue=600, fee_cost="0.06")
    result, orders = _graded(
        ledger, monkeypatch, [_order()], [row], _exits_state(_exit(filled_contracts=4, exit_fee_dollars=0.05))
    )
    o = orders[0]
    assert result["exit_adjusted"] == 1
    assert o["outcome"] == "won"
    assert o["pnl_dollars"] == pytest.approx(3.65)
    assert o["exit_applied"]["contracts_settled"] == 6
    assert o["exit_applied"]["settlement_dollars"] == pytest.approx(6.0)
    assert o["exit_applied"]["venue_settlement_pnl_dollars"] == pytest.approx(6.0 - 3.24 - 0.06)


def test_a_partly_sold_loser_keeps_the_sale_proceeds(ledger, monkeypatch):
    """Same sale, market NO: 4*0.80 - 0.05 + 0 - 5.40 - 0.10 = -2.35."""
    row = _k(market_result="no", yes_count_fp="6.00", yes_total_cost_dollars="3.2400", revenue=0)
    _r, orders = _graded(
        ledger, monkeypatch, [_order()], [row], _exits_state(_exit(filled_contracts=4, exit_fee_dollars=0.05))
    )
    assert orders[0]["outcome"] == "lost"
    assert orders[0]["pnl_dollars"] == pytest.approx(-2.35)


def test_a_missing_exit_fee_is_estimated_at_the_full_rate_and_said(ledger, monkeypatch):
    row = _k(market_result="no", yes_count_fp="0.00", revenue=0)
    _r, orders = _graded(ledger, monkeypatch, [_order()], [row], _exits_state(_exit(exit_fee_dollars=None)))
    applied = orders[0]["exit_applied"]
    assert applied["exit_fee_estimated"] is True
    expected_fee = ex.estimate_kalshi_fee(TICKER, 10, 0.80)
    assert applied["exit_fee_dollars"] == pytest.approx(expected_fee)
    assert orders[0]["pnl_dollars"] == pytest.approx(8.0 - expected_fee - 5.40 - 0.10)


def test_a_sold_entry_beside_an_unsold_sibling_grades_each_from_its_own_fills(ledger, monkeypatch):
    """Two orders on one market; only one was sold. The unsold one keeps the
    per-order derived arithmetic it always had."""
    a = _order(idempotency_key="a" * 24)
    b = _order(idempotency_key="b" * 24, fill_stake_dollars=2.0, fill_price=0.50, fees_dollars=None)
    result, orders = _graded(ledger, monkeypatch, [a, b], [_k()], _exits_state(_exit()))
    assert result["exit_adjusted"] == 1 and result["pnl_derived"] == 1
    assert orders[0]["pnl_dollars"] == pytest.approx(8.0 - 0.12 - 5.40 - 0.10)
    assert orders[1]["pnl_dollars"] == pytest.approx(2.0)
    assert "exit_applied" not in orders[1]


def test_the_impossible_pnl_repair_leaves_a_sold_entry_alone(ledger, monkeypatch):
    """`outcome=lost` with a PROFIT is exactly what `_pnl_exceeds_own_fill`
    flags -- and exactly what a profitable sale on a losing market is. The next
    tick must not 'correct' it back to the hold-to-settle loss."""
    row = _k(market_result="no", yes_count_fp="0.00", revenue=0)
    _graded(ledger, monkeypatch, [_order()], [row], _exits_state(_exit()))
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(2.38)
    again = vs.settle_from_venue()
    assert "repaired_pnl" not in again
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(2.38)


def test_sold_to_zero_with_NO_settlement_row_reads_the_market_result(ledger, monkeypatch):
    """A position sold to zero may never appear in `/portfolio/settlements`.
    Its money is fixed; only the market result is missing, and the public market
    read supplies it. Absent a result, it waits."""
    calls = []

    def _results(tickers):
        calls.append(list(tickers))
        return {TICKER.casefold(): {"result": "", "status": "active"}}, None

    monkeypatch.setattr(vs, "fetch_kalshi_market_results", _results)
    result, orders = _graded(ledger, monkeypatch, [_order()], [], _exits_state(_exit()))
    assert calls == [[TICKER]]
    assert "outcome" not in orders[0]
    assert result["awaiting"] == 1

    monkeypatch.setattr(
        vs, "fetch_kalshi_market_results",
        lambda tickers: ({TICKER.casefold(): {"result": "no", "status": "finalized"}}, None),
    )
    result = vs.settle_from_venue()
    assert result["exit_adjusted"] == 1 and result["awaiting"] == 0
    assert ledger["orders"][0]["outcome"] == "lost"
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(2.38)


def test_a_partly_sold_entry_waits_for_its_settlement_row(ledger, monkeypatch):
    """Contracts are still held, so the venue WILL settle them -- no market read."""
    result, orders = _graded(ledger, monkeypatch, [_order()], [], _exits_state(_exit(filled_contracts=4)))
    assert "outcome" not in orders[0]
    assert result["awaiting"] == 1


# ---------------------------------------------------------------------------
# 3. Unknown means wait
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [ex.EXIT_SUBMITTED, ex.EXIT_FAILED, "something_new"])
def test_a_live_exit_of_unknown_fate_defers_the_grade(ledger, monkeypatch, status):
    result, orders = _graded(
        ledger, monkeypatch, [_order()], [_k()], _exits_state(_exit(status=status, fill_price=None))
    )
    assert "outcome" not in orders[0]
    assert result["exit_deferred"] == 1
    assert result["awaiting"] == 1
    assert result["settled"] == 0


def test_a_deferred_entry_grades_once_the_exit_reconciles(ledger, monkeypatch):
    _graded(ledger, monkeypatch, [_order()], [_k(market_result="no", yes_count_fp="0.00", revenue=0)],
            _exits_state(_exit(status=ex.EXIT_SUBMITTED)))
    assert "outcome" not in ledger["orders"][0]
    ledger["_exits"]["state"] = _exits_state(_exit())
    vs.settle_from_venue()
    assert ledger["orders"][0]["pnl_dollars"] == pytest.approx(2.38)


def test_an_unreadable_exits_document_defers_kalshi_and_only_kalshi(ledger, monkeypatch):
    def _boom():
        raise RuntimeError("execution_exits_unreadable")

    monkeypatch.setattr(ex, "load_state", _boom)
    poly = {
        "idempotency_key": "p" * 24, "mode": "live", "venue": "polymarket",
        "venue_ticker": "aec-mlb-x", "status": "filled", "fill_stake_dollars": 3.0,
        "selected_date": "2026-08-26",
    }
    ledger["orders"] = [_order(), poly]
    _rows(monkeypatch, [_k()])
    monkeypatch.setattr(
        vs, "fetch_polymarket_resolutions",
        lambda **kw: ([{
            "marketSlug": "aec-mlb-x", "side": "POSITION_RESOLUTION_SIDE_LONG",
            "beforePosition": {"realized": {"value": "1.0"}},
            "afterPosition": {"realized": {"value": "3.0"}},
            "updateTime": "2026-08-27T03:10:00Z",
        }], None),
    )
    result = vs.settle_from_venue()
    assert "execution_exits_unreadable" in result["errors"]["exits"]
    assert "outcome" not in ledger["orders"][0]
    assert result["exit_deferred"] == 1
    assert ledger["orders"][1]["outcome"] == "won"


# ---------------------------------------------------------------------------
# 4. Reachability: the real document on disk
# ---------------------------------------------------------------------------


def test_reachability_a_real_exits_document_on_disk_changes_the_grade(ledger, monkeypatch, tmp_path):
    """off != on through the REAL `load_state`/`_persist` pair, not a stub: the
    same ledger and settlement row grade differently once the exit tick's own
    writer has put a filled live exit on disk under its exit key."""
    monkeypatch.undo()  # drop the fixture's load_state stub; re-stub only the venue + ledger
    import syndicate.features.shared.execution_ledger as led

    path = tmp_path / "execution_exits.json"
    monkeypatch.setattr(ex, "exits_path", lambda: path)
    state = {"orders": [_order()]}
    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    row = _k(market_result="no", yes_count_fp="0.00", revenue=0)
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([row], None))

    # OFF: no document. The sold-to-zero row refuses, exactly as before exits.
    off = vs.settle_from_venue()
    assert off["refused"] == {"no_position_held": 1}
    assert "outcome" not in state["orders"][0]

    # ON: the exit tick's writer persists a filled live exit.
    ex._persist(_exits_state(_exit()))
    assert path.exists()
    on = vs.settle_from_venue()
    assert on["exit_adjusted"] == 1
    assert state["orders"][0]["pnl_dollars"] == pytest.approx(2.38)


def test_live_blockers_no_longer_name_venue_settlement():
    assert not any("settlement" in b for b in ex.LIVE_BLOCKERS)
    # The sell body was accepted and filled on a real sale 2026-10-19 22:42:59Z.
    assert not any("sell body" in b for b in ex.LIVE_BLOCKERS)
