"""The INFERENCE fallback knows a live Kalshi entry was sold first.

`paper_settlement.settle_orders` grades a live order itself once the 24h venue
grace has passed. Before lane kalshi-exit-settlement it booked hold-to-settle
money even when `execution_exits` had sold the contracts -- the gap left open
after `venue_settlement` became exit-aware. Same rules as the venue path:

* no exit, or a PAPER exit -> graded exactly as before;
* a LIVE exit filled -> P&L from both fills, outcome still the game's;
* a LIVE exit of unknown fate, or an unreadable exits doc -> wait.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import paper_settlement as ps

KEY = "a" * 24


def _stamp(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _order(**over):
    order = {
        "idempotency_key": KEY,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": "KX-TEST",
        "status": "filled",
        "selected_date": "2026-08-26",
        "submitted_at": _stamp(30),  # past the 24h venue grace
        "fill_price": 0.54,
        "fill_stake_dollars": 5.40,  # 10 contracts
        "fees_dollars": 0.10,
        "market": "player_points",
        "side": "Over",
        "line": 17.5,
    }
    order.update(over)
    return order


def _exit(**over):
    row = {
        "entry_key": KEY,
        "exit_key": ex.exit_idempotency_key(KEY),
        "mode": ex.EXIT_LIVE,
        "status": ex.EXIT_FILLED,
        "ticker": "KX-TEST",
        "leg": "yes",
        "contracts": 10.0,
        "entry_price": 0.54,
        "entry_fee_dollars": 0.10,
        "filled_contracts": 10,
        "fill_price": 0.80,
        "exit_fee_dollars": 0.12,
    }
    row.update(over)
    return row


def _doc(*rows):
    return {"version": 1, "watch": {}, "exits": {r["exit_key"]: r for r in rows}}


def _won(order):
    return {"current_value": 25.0, "is_final": True, "started": True}


def _lost(order):
    return {"current_value": 10.0, "is_final": True, "started": True}


@pytest.fixture
def ledger(monkeypatch):
    state = {"orders": []}
    exits = {"doc": _doc(), "reads": 0}
    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.delenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", raising=False)

    def _load_state():
        exits["reads"] += 1
        return copy.deepcopy(exits["doc"])

    monkeypatch.setattr(ex, "load_state", _load_state)
    state["_exits"] = exits
    return state


def _settle(ledger, orders, doc, resolver=_won):
    ledger["orders"] = [copy.deepcopy(o) for o in orders]
    ledger["_exits"]["doc"] = doc
    result = ps.settle_orders("2026-08-26", resolver=resolver)
    return result, ledger["orders"]


def _no_clock(orders):
    out = []
    for o in orders:
        row = {k: v for k, v in o.items() if k != "graded_at"}
        if isinstance(row.get("closing_mark"), dict):
            row["closing_mark"] = {k: v for k, v in row["closing_mark"].items() if k != "checked_at"}
        out.append(row)
    return out


def test_no_exit_and_paper_exits_grade_exactly_as_before(ledger):
    entry = _order()
    _r0, baseline = _settle(ledger, [entry], _doc())
    assert baseline[0]["outcome"] == "won" and "exit_applied" not in baseline[0]
    for doc in (
        _doc(_exit(mode=ex.EXIT_PAPER, status=ex.EXIT_PAPER_FILLED, realized_pnl_dollars=2.38)),
        _doc(_exit(status=ex.EXIT_DEAD, filled_contracts=0)),
        _doc(_exit(status=ex.EXIT_REJECTED, filled_contracts=0)),
    ):
        _r, orders = _settle(ledger, [entry], doc)
        assert _no_clock(orders) == _no_clock(baseline)


def test_a_fully_sold_entry_books_the_sale(ledger):
    """Sold 10 at 80c; the game then went the other way. Inference must book
    10*0.80 - 0.12 - 5.40 - 0.10 = +2.38, not the -5.50 hold loss."""
    result, orders = _settle(ledger, [_order()], _doc(_exit()), resolver=_lost)
    o = orders[0]
    assert result["graded"] == 1
    assert o["outcome"] == "lost"  # the game's result is untouched
    assert o["pnl_dollars"] == pytest.approx(2.38)
    assert o["pnl_gross_dollars"] == pytest.approx(8.0 - 5.40)
    assert o["exit_applied"]["contracts_sold"] == 10
    assert "settled_by" not in o  # still an INFERRED grade


def test_a_partly_sold_winner_settles_only_the_remainder(ledger):
    """4 sold at 80c (fee 0.05), 6 held to a win: 3.20 - 0.05 + 6 - 5.40 - 0.10 = 3.65."""
    _r, orders = _settle(ledger, [_order()], _doc(_exit(filled_contracts=4, exit_fee_dollars=0.05)))
    assert orders[0]["pnl_dollars"] == pytest.approx(3.65)


@pytest.mark.parametrize("status", [ex.EXIT_SUBMITTED, ex.EXIT_FAILED, "something_new"])
def test_a_live_exit_of_unknown_fate_defers(ledger, status):
    result, orders = _settle(ledger, [_order()], _doc(_exit(status=status, fill_price=None)))
    assert result["graded"] == 0
    assert result["ungraded"].get("awaiting_exit_reconcile") == 1
    assert "outcome" not in orders[0]


def test_an_unreadable_exits_doc_defers_kalshi_and_only_kalshi(ledger, monkeypatch):
    def _boom():
        raise RuntimeError("execution_exits_unreadable")

    monkeypatch.setattr(ex, "load_state", _boom)
    poly = _order(idempotency_key="p" * 24, venue="polymarket", venue_ticker="aec-x")
    result, orders = _settle(ledger, [_order(), poly], _doc())
    assert result["ungraded"].get("awaiting_exit_unreadable") == 1
    assert "outcome" not in orders[0]
    assert orders[1]["outcome"] == "won"


def test_the_exits_doc_is_not_read_unless_a_live_kalshi_row_passes_the_grace(ledger):
    """Paper rows and fresh live rows never pay for the read."""
    fresh = _order(submitted_at=_stamp(1))
    paper = _order(idempotency_key="b" * 24, mode="paper", venue="paper:kalshi")
    _settle(ledger, [fresh, paper], _doc(_exit()))
    assert ledger["_exits"]["reads"] == 0


def test_reachability_a_real_exits_doc_on_disk_changes_the_inferred_grade(ledger, monkeypatch, tmp_path):
    """off != on through the REAL execution_exits load_state/_persist pair."""
    monkeypatch.undo()
    import syndicate.features.shared.execution_ledger as led

    state = {"orders": [_order()]}
    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.delenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", raising=False)
    path = tmp_path / "execution_exits.json"
    monkeypatch.setattr(ex, "exits_path", lambda: path)

    ps.settle_orders("2026-08-26", resolver=_lost)  # OFF: no document
    off_pnl = state["orders"][0]["pnl_dollars"]
    assert off_pnl < 0 and "exit_applied" not in state["orders"][0]

    state["orders"] = [_order()]
    ex._persist(_doc(_exit()))  # ON: the exit tick's own writer
    ps.settle_orders("2026-08-26", resolver=_lost)
    assert state["orders"][0]["pnl_dollars"] == pytest.approx(2.38)
