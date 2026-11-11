"""A Kalshi both-sides row explained by ANOTHER entry's exit grades (lane kalshi-grader-market-exits, after #783).

MEASURED 2026-11-11 on `KXNFLTOTAL-26OCT25SFATL-50`: entry 837e657b (0.1 NO, never exited) sat ungraded
`both_sides_held` for 16 days. The settlement row held NO 1.10 (837e657b's 0.1 + entry ffd5030f's 1.0) and YES 1.00,
which was ffd5030f's exit `x954102a3` closing its NO. ffd5030f was already graded, so `_both_sides_is_our_partial_close`
(which reads only the graded-now entries' exits) could not explain the YES leg. It was graded by hand.

Pinned here:
1. that shape grades the held entry from the venue's result at its own fill, and the switch off puts the refusal back;
2. an exit that only the archive still holds counts, and an unreadable archive refuses;
3. a target whose OWN exit is archived grades exit-aware, never as held;
4. a count we did not make, a second leg, an unreconciled exit or an unknown fill still refuses.
"""

from __future__ import annotations

import copy

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import venue_settlement as vs

TICKER = "KXNFLTOTAL-26OCT25SFATL-50"
HELD = "837e657b82f4375ad959e062"
OTHER = "ffd5030f0000000000000000"


def _row(**over):
    row = {
        "event_ticker": "KXNFLTOTAL-26OCT25SFATL",
        "ticker": TICKER,
        "market_result": "no",
        "no_count_fp": "1.10",
        "no_total_cost_dollars": "0.660000",
        "yes_count_fp": "1.00",
        "yes_total_cost_dollars": "0.300000",
        "revenue": 110,
        "fee_cost": "0.020000",
        "settled_time": "2026-10-26T04:10:00Z",
        "value": 0,
    }
    row.update(over)
    return row


def _order(key, **over):
    order = {
        "idempotency_key": key,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": TICKER,
        "status": "filled",
        "side": "under",
        "line": 49.5,
        "contracts": 0.1,
        "fill_price": 0.6,
        "fill_stake_dollars": 0.06,
        "fees_dollars": 0.001,
    }
    order.update(over)
    return order


def _graded_other(**over):
    """ffd5030f: 1 NO, sold through its exit, already graded."""
    base = dict(contracts=1, fill_stake_dollars=0.6, fees_dollars=0.01, outcome="won", pnl_dollars=0.05,
                settled_by="venue")
    base.update(over)
    return _order(OTHER, **base)


def _exit(entry_key=OTHER, **over):
    row = {
        "entry_key": entry_key,
        "exit_key": ex.exit_idempotency_key(entry_key),
        "entry_mode": "live",
        "mode": ex.EXIT_LIVE,
        "status": ex.EXIT_FILLED,
        "ticker": TICKER,
        "leg": "no",
        "contracts": 1.0,
        "entry_price": 0.6,
        "entry_fee_dollars": 0.01,
        "requested_contracts": 1,
        "filled_contracts": 1,
        "fill_price": 0.7,
        "exit_fee_dollars": 0.007,
    }
    row.update(over)
    return row


def _exits_state(*rows):
    return {"version": 1, "watch": {}, "exits": {r["exit_key"]: r for r in rows}}


@pytest.fixture
def ledger(monkeypatch):
    state = {"orders": [], "_exits": _exits_state(), "_archive": []}
    import syndicate.features.shared.execution_ledger as led

    monkeypatch.delenv(vs.MARKET_EXIT_CLOSE_ENV, raising=False)
    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    monkeypatch.setattr(ex, "load_state", lambda: copy.deepcopy(state["_exits"]))

    def _archived():
        if isinstance(state["_archive"], Exception):
            raise state["_archive"]
        return copy.deepcopy(state["_archive"])

    monkeypatch.setattr(ex, "archived_exit_rows", _archived)

    def _no_market_read(tickers):
        raise AssertionError("these entries grade from their settlement row, not the market read")

    monkeypatch.setattr(vs, "fetch_kalshi_market_results", _no_market_read)
    return state


def _settle(ledger, monkeypatch, orders, row, exits_state, archive=()):
    ledger["orders"] = [copy.deepcopy(o) for o in orders]
    ledger["_exits"] = exits_state
    ledger["_archive"] = archive if isinstance(archive, Exception) else [copy.deepcopy(r) for r in archive]
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: ([row], None))
    result = vs.settle_from_venue()
    return result, {o["idempotency_key"]: o for o in ledger["orders"]}


# ---------------------------------------------------------------------------
# 1. The 837e657b shape grades; off is today's refusal
# ---------------------------------------------------------------------------


def test_the_held_entry_grades_won_from_its_own_fill(ledger, monkeypatch, capsys):
    held = _order(HELD)
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), held], _row(), _exits_state(_exit()))
    o = orders[HELD]
    assert result["refused"] == {}
    assert result["exit_market_close"] == 1 and result["settled"] == 1
    assert "exit_partial_both_sides" not in result, "the target itself sold nothing"
    assert o["outcome"] == "won" and o["held_side"] == "no" and o["settled_by"] == "venue"
    assert o["venue_grade_basis"] == "market_exit_close"
    assert o["settled_at_venue"] == "2026-10-26T04:10:00Z"
    # Its own fill, never the market's: 0.06 at 0.60 wins 0.04, less the 0.001 fee.
    assert o["pnl_dollars"] == pytest.approx(vs._derived_pnl(held, "won")) == pytest.approx(0.039)
    assert orders[OTHER]["pnl_dollars"] == 0.05, "an already graded entry is never touched"
    assert "MARKET_EXIT_CLOSE ticker=KXNFLTOTAL-26OCT25SFATL-50 leg=no result=no targets=1 sold=0 held=1" in (
        capsys.readouterr().out
    )


def test_a_yes_result_grades_the_held_no_lost(ledger, monkeypatch):
    held = _order(HELD)
    _result, orders = _settle(ledger, monkeypatch, [_graded_other(), held], _row(market_result="yes"),
                              _exits_state(_exit()))
    assert orders[HELD]["outcome"] == "lost"
    assert orders[HELD]["pnl_dollars"] == pytest.approx(-0.061)


def test_off_is_the_measured_refusal(ledger, monkeypatch):
    """Reachability: the switch off leaves 837e657b ungraded `both_sides_held`, as it sat for 16 days."""
    monkeypatch.setenv(vs.MARKET_EXIT_CLOSE_ENV, "off")
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(), _exits_state(_exit()))
    assert result["refused"] == {"both_sides_held": 1}
    assert "exit_market_close" not in result
    assert orders[HELD].get("outcome") is None


# ---------------------------------------------------------------------------
# 2. The archive
# ---------------------------------------------------------------------------


def test_an_exit_only_the_archive_holds_still_explains_the_row(ledger, monkeypatch):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(), _exits_state(),
                             archive=[_exit()])
    assert result["exit_market_close"] == 1
    assert orders[HELD]["outcome"] == "won"


def test_an_unreadable_archive_refuses(ledger, monkeypatch):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(), _exits_state(),
                             archive=OSError("disk"))
    assert result["refused"] == {"both_sides_held": 1}
    assert result["errors"]["exits_archive"].startswith("OSError")
    assert orders[HELD].get("outcome") is None


def test_a_paper_exit_in_the_archive_is_not_ours(ledger, monkeypatch):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(), _exits_state(),
                             archive=[_exit(mode="paper")])
    assert result["refused"] == {"both_sides_held": 1}
    assert orders[HELD].get("outcome") is None


# ---------------------------------------------------------------------------
# 3. A target that itself sold, its exit archived
# ---------------------------------------------------------------------------


def test_a_target_whose_own_exit_is_archived_grades_exit_aware_not_held(ledger, monkeypatch):
    """HELD bought 2 NO and sold 1; OTHER bought 1 NO and sold 1. Row: NO 3, YES 2."""
    held = _order(HELD, contracts=2, fill_stake_dollars=1.2, fees_dollars=0.02)
    own_exit = _exit(HELD, contracts=2.0, entry_fee_dollars=0.02, fill_price=0.8, exit_fee_dollars=0.006)
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), held], _row(no_count_fp="3.00", yes_count_fp="2.00"),
                             _exits_state(_exit()), archive=[own_exit])
    o = orders[HELD]
    assert result["exit_market_close"] == 1 and result["exit_adjusted"] == 1
    assert o["outcome"] == "won" and o.get("exit_applied"), "graded through the sale"
    pnl, _detail = vs.exit_adjusted_pnl(held, "won", own_exit)
    assert o["pnl_dollars"] == pytest.approx(pnl)
    assert o["pnl_dollars"] != pytest.approx(vs._derived_pnl(held, "won")), "never graded as if it held both"


# ---------------------------------------------------------------------------
# 4. Still refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("over", [
    {"yes_count_fp": "2.00"},   # a YES count our exits did not make
    {"no_count_fp": "1.30"},    # a NO count our entries did not make
    {"no_count_fp": "1.00"},
])
def test_a_count_we_did_not_make_refuses(ledger, monkeypatch, over):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(**over), _exits_state(_exit()))
    assert result["refused"] == {"both_sides_held": 1}
    assert orders[HELD].get("outcome") is None


def test_our_order_on_the_other_leg_refuses(ledger, monkeypatch):
    yes_entry = _order("aaaa00000000000000000000", side="over", contracts=1, outcome="lost", pnl_dollars=-0.4)
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD), yes_entry],
                             _row(yes_count_fp="2.00"), _exits_state(_exit()))
    assert "exit_market_close" not in result
    assert orders[HELD].get("outcome") is None


def test_an_unreconciled_exit_refuses(ledger, monkeypatch):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(),
                             _exits_state(_exit(status="submitted")))
    assert "exit_market_close" not in result
    assert orders[HELD].get("outcome") is None


def test_an_entry_whose_fill_is_not_known_yet_refuses(ledger, monkeypatch):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD), _order("bbbb00000000000000000000",
                             status="submitted", contracts=None)], _row(), _exits_state(_exit()))
    assert "exit_market_close" not in result
    assert orders[HELD].get("outcome") is None


def test_a_rejected_order_holds_nothing_and_does_not_block(ledger, monkeypatch):
    rejected = _order("cccc00000000000000000000", status="rejected", contracts=0)
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD), rejected], _row(),
                             _exits_state(_exit()))
    assert result["exit_market_close"] == 1
    assert orders[HELD]["outcome"] == "won"
    assert orders["cccc00000000000000000000"].get("outcome") is None


def test_no_exit_at_all_is_a_real_two_sided_row(ledger, monkeypatch):
    result, orders = _settle(ledger, monkeypatch, [_graded_other(), _order(HELD)], _row(), _exits_state())
    assert result["refused"] == {"both_sides_held": 1}
    assert orders[HELD].get("outcome") is None
