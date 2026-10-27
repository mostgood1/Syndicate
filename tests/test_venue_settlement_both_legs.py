"""Kalshi tickers where we held BOTH legs, or one leg under two labels
(lane kalshi-both-leg-grading).

MEASURED 2026-10-23 on the fleet ledger. Live in-game entries, before the
one-entry-per-game-axis fix (81aaf6e5), left five filled orders ungraded for
days:

* `KXNBASPREAD-26OCT23ATLCHA-ATL9` yes + no, `KXNBATOTAL-26OCT23ATLCHA-230`
  yes + no -- a genuine both-legs holding, refused `both_sides_held`;
* `KXNBATOTAL-26OCT23NYKBOS-220` yes -- a FALSE ambiguity: a pregame `over`
  on the same ticker is the same YES leg, but raw labels {"over","yes"}
  refused `ambiguous_multi_side`.

These tests pin the per-leg grading, its reachability (before vs after), and
that the 08-27 "both teams won" guard still refuses what it should.
"""

from __future__ import annotations

import copy

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import venue_settlement as vs

ATL9 = "KXNBASPREAD-26OCT23ATLCHA-ATL9"
T230 = "KXNBATOTAL-26OCT23ATLCHA-230"
NYK220 = "KXNBATOTAL-26OCT23NYKBOS-220"
SETTLED = "2026-10-24T02:10:00Z"


def _order(key, ticker, side, price, fees, contracts=1, market="totals", line=229.5, **over):
    order = {
        "idempotency_key": key,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": ticker,
        "status": "filled",
        "side": side,
        "market": market,
        "line": line,
        "contracts": contracts,
        "fill_price": price,
        "fill_stake_dollars": round(price * contracts, 4),
        "fees_dollars": fees,
    }
    order.update(over)
    return order


def _row(ticker, result, yes_ct, no_ct, yes_cost, no_cost, fees):
    revenue = 100 * (yes_ct if result == "yes" else no_ct)
    return {
        "ticker": ticker,
        "market_result": result,
        "yes_count_fp": f"{yes_ct:.2f}",
        "no_count_fp": f"{no_ct:.2f}",
        "yes_total_cost_dollars": f"{yes_cost:.6f}",
        "no_total_cost_dollars": f"{no_cost:.6f}",
        "revenue": revenue,
        "fee_cost": f"{fees:.6f}",
        "settled_time": SETTLED,
    }


# The fleet's own orders, verbatim but for idempotency keys.
def _atl9():
    return [
        _order("atl9-yes", ATL9, "yes", 0.45, 0.0174, market="spreads", line=8.5),
        _order("atl9-no", ATL9, "no", 0.40, 0.0168, market="spreads", line=8.5),
    ]


def _t230():
    return [
        _order("t230-yes", T230, "yes", 0.43, 0.0172),
        _order("t230-no", T230, "no", 0.41, 0.0170),
    ]


def _nyk220():
    return [
        _order(
            "nyk-pregame-over", NYK220, "over", 0.55, 0.1906, contracts=11, market="totals_alt",
            line=219.5, outcome="lost", pnl_dollars=-6.2406, settled_by="venue",
        ),
        _order("nyk-live-yes", NYK220, "yes", 0.40, 0.0168, line=219.5),
    ]


@pytest.fixture
def ledger(monkeypatch):
    state = {"orders": []}
    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([], None))
    monkeypatch.setattr(ex, "load_state", lambda: {"version": 1, "watch": {}, "exits": {}})
    monkeypatch.setattr(vs, "fetch_kalshi_market_results", lambda tickers: ({}, None))
    return state


def _settle(ledger, monkeypatch, orders, rows):
    ledger["orders"] = [copy.deepcopy(o) for o in orders]
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: (list(rows), None))
    return vs.settle_from_venue(), {o["idempotency_key"]: o for o in ledger["orders"]}


def _legacy(monkeypatch):
    """The code as it was: raw side labels, and no both-legs path."""
    monkeypatch.setattr(
        vs, "_order_side_key", lambda venue, order: str(order.get("side") or "").strip().lower()
    )
    monkeypatch.setattr(vs, "_both_legs_grades", lambda *a, **k: None)


# --- the exact fleet shapes ------------------------------------------------


def test_atl9_both_legs_grade_per_leg_and_net_the_spread(ledger, monkeypatch):
    row = _row(ATL9, "yes", 1, 1, 0.45, 0.40, 0.0342)
    result, orders = _settle(ledger, monkeypatch, _atl9(), [row])

    assert orders["atl9-yes"]["outcome"] == "won"
    assert orders["atl9-no"]["outcome"] == "lost"
    assert orders["atl9-yes"]["held_side"] == "yes"
    assert orders["atl9-no"]["held_side"] == "no"
    assert orders["atl9-yes"]["pnl_dollars"] == pytest.approx(0.55 - 0.0174, abs=1e-4)
    assert orders["atl9-no"]["pnl_dollars"] == pytest.approx(-0.40 - 0.0168, abs=1e-4)
    net = orders["atl9-yes"]["pnl_dollars"] + orders["atl9-no"]["pnl_dollars"]
    # $1 back on $0.85 of cost, less fees: inside the +0.12..+0.16 band less fees.
    assert net == pytest.approx(0.15 - 0.0342, abs=1e-4)
    assert result["both_legs_graded"] == 2
    assert result["refused"] == {}


def test_atlcha_230_both_legs_grade_when_no_wins(ledger, monkeypatch):
    row = _row(T230, "no", 1, 1, 0.43, 0.41, 0.0342)
    result, orders = _settle(ledger, monkeypatch, _t230(), [row])

    assert orders["t230-yes"]["outcome"] == "lost"
    assert orders["t230-no"]["outcome"] == "won"
    net = orders["t230-yes"]["pnl_dollars"] + orders["t230-no"]["pnl_dollars"]
    assert net == pytest.approx(0.16 - 0.0342, abs=1e-4)
    assert result["refused"] == {}


def test_nykbos_220_over_and_yes_are_one_leg(ledger, monkeypatch):
    row = _row(NYK220, "no", 12, 0, 6.45, 0.0, 0.2074)
    result, orders = _settle(ledger, monkeypatch, _nyk220(), [row])

    live = orders["nyk-live-yes"]
    assert live["outcome"] == "lost"
    assert live["held_side"] == "yes"
    # The row's P&L is the whole 12-contract position; this order's own fill
    # is 1 contract, so the venue figure must not land on it.
    assert live["pnl_dollars"] == pytest.approx(-0.40 - 0.0168, abs=1e-4)
    assert orders["nyk-pregame-over"]["pnl_dollars"] == -6.2406  # untouched
    assert "ambiguous_multi_side" not in result["refused"]


def test_the_grades_survive_the_next_tick(ledger, monkeypatch):
    """The repair runs first every tick; it must not clear per-leg grades that
    can all be true, or settle and repair would fight forever."""
    rows = [
        _row(ATL9, "yes", 1, 1, 0.45, 0.40, 0.0342),
        _row(NYK220, "no", 12, 0, 6.45, 0.0, 0.2074),
    ]
    _settle(ledger, monkeypatch, _atl9() + _nyk220(), rows)
    graded = copy.deepcopy(ledger["orders"])

    second = vs.settle_from_venue()

    assert "repaired" not in second
    assert ledger["orders"] == graded


# --- reachability: off != on -----------------------------------------------


@pytest.mark.parametrize(
    "orders,row,reason",
    [
        (_atl9, _row(ATL9, "yes", 1, 1, 0.45, 0.40, 0.0342), "both_sides_held"),
        (_t230, _row(T230, "no", 1, 1, 0.43, 0.41, 0.0342), "both_sides_held"),
        (_nyk220, _row(NYK220, "no", 12, 0, 6.45, 0.0, 0.2074), "ambiguous_multi_side"),
    ],
)
def test_before_the_fix_these_rows_refused(ledger, monkeypatch, orders, row, reason):
    _legacy(monkeypatch)
    result, graded = _settle(ledger, monkeypatch, orders(), [row])

    assert result["refused"].get(reason)
    assert result["settled"] == 0
    assert all(not o.get("outcome") or o["idempotency_key"] == "nyk-pregame-over" for o in graded.values())


# --- the 08-27 guard still refuses -----------------------------------------


def test_the_grader_alone_still_refuses_both_sides():
    assert vs.grade_kalshi_settlement(_row(ATL9, "yes", 1, 1, 0.45, 0.40, 0.0342)) == {
        "graded": False,
        "reason": "both_sides_held",
    }


def test_a_count_we_did_not_make_still_refuses(ledger, monkeypatch):
    row = _row(ATL9, "yes", 3, 1, 1.35, 0.40, 0.05)
    result, orders = _settle(ledger, monkeypatch, _atl9(), [row])

    assert result["refused"] == {"both_sides_held": 1}
    assert not any(o.get("outcome") for o in orders.values())


def test_a_prior_grade_that_contradicts_the_result_still_refuses(ledger, monkeypatch):
    """A leg already graded WON while the row says the OTHER leg won: grading
    the rest would put both legs at WON."""
    orders = _atl9()
    orders[1].update(outcome="won", settled_by="inferred", pnl_dollars=0.58)
    result, graded = _settle(ledger, monkeypatch, orders, [_row(ATL9, "yes", 1, 1, 0.45, 0.40, 0.0342)])

    assert graded["atl9-yes"].get("outcome") is None
    assert result["refused"] == {"both_sides_held": 1}


def test_both_legs_won_is_still_repaired(ledger, monkeypatch):
    """The 08-27 shape on a Kalshi ticker: one verdict shared across legs."""
    orders = _atl9()
    for o in orders:
        o.update(outcome="won", settled_by="venue", pnl_dollars=0.5, held_side="yes")
    ledger["orders"] = orders

    repaired = vs.repair_multi_side_grades()

    assert repaired["cleared"] == 2
    assert not any(o.get("outcome") for o in ledger["orders"])


def test_unmappable_labels_still_count_as_two_sides():
    assert vs._order_side_key("kalshi", {"side": "home", "market": "totals"}) == "home"
    assert vs._order_side_key("kalshi", {"side": "over", "market": "totals_alt"}) == "yes"
    assert vs._order_side_key("polymarket", {"side": "over"}) == "over"


@pytest.mark.parametrize(
    "by_leg,ok",
    [
        ({"yes": {"won"}, "no": {"lost"}}, True),
        ({"yes": {"won"}, "no": {"won"}}, False),
        ({"yes": {"lost"}, "no": {"lost"}}, False),
        ({"yes": {"won", "lost"}}, False),
        ({"yes": {"push"}}, False),
        ({"home": {"won"}, "away": {"lost"}}, False),
    ],
)
def test_legs_consistent(by_leg, ok):
    assert vs._kalshi_legs_consistent(by_leg) is ok
