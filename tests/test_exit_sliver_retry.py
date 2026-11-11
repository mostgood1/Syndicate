"""A sliver-filled take-profit exit is SOLD and still OPEN (todo #783, user 2026-11-11 "Record, exits keep going").

MEASURED: exit `x403f59b5` (entry `970ec063`, 1 NO) was filled 0.01 of 1 contract on 2026-10-25 and recorded
`dead`; 7 live exits went that way since 10-25, two on 6- and 8-contract holdings. Now the sliver is recorded
(so settlement can explain the opposite leg it left), the exit stays open for the whole contracts still held,
and later fills accumulate on the same row.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import kalshi_orders as ko
from syndicate.features.shared import venue_settlement as vs
from tests.test_execution_exits import NOW, TODAY, _arm_live, _decision, _market, _order, _position, _quotes


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    monkeypatch.delenv(ko.FRACTIONAL_COUNTS_ENV, raising=False)
    for name in ("SYNDICATE_EXIT_MODE", "SYNDICATE_EXIT_LIVE_ARMED", "SYNDICATE_EXECUTION_LIVE_ARMED",
                 "SYNDICATE_EXECUTION_KILL_SWITCH", "SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "SYNDICATE_EXIT_FAIR_MARGIN",
                 "SYNDICATE_EXIT_LIVE_PHASES"):
        monkeypatch.delenv(name, raising=False)


def _venue(order_id, *, count, status="canceled", fee="0.000200"):
    """A Kalshi order as the venue reports a close of our NO: `buy yes`, the cost quoted on YES at 0.04."""
    return {"order_id": order_id, "status": status, "fill_count_fp": f"{count:.2f}",
            "taker_fill_cost_dollars": f"{count * 0.04:.6f}", "taker_fees_dollars": fee, "outcome_side": "yes"}


def _send(order):
    def send(body):
        send.bodies.append(body)
        return ex._exit_view({**order, "outcome_side": "yes"})
    send.bodies = []
    return send


def _sliver(monkeypatch, state=None):
    _arm_live(monkeypatch)
    state = state or ex._empty_state()
    send = _send(_venue("o-sliver", count=0.01))
    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=send, persist=lambda s: None)
    return state, out["row"], send


def test_a_sliver_is_recorded_as_sold_and_the_exit_stays_open(monkeypatch):
    _state, row, send = _sliver(monkeypatch)
    assert send.bodies[0]["count"] == "5.00"
    assert row["status"] == ex.EXIT_FILLED, "the measured defect recorded this `dead`"
    assert row["filled_contracts"] == pytest.approx(0.01)
    assert row["fill_price"] == pytest.approx(0.96), "NO sold at 1 - 0.04"
    assert row["exit_fee_dollars"] == pytest.approx(0.0002)
    assert ex.is_sliver_exit(row)


def test_off_is_the_measured_defect(monkeypatch):
    """Reachability through the exit path: with the parser switch off the sliver reads `dead` / 0 again."""
    monkeypatch.setenv(ko.FRACTIONAL_COUNTS_ENV, "off")
    _state, row, _send_fn = _sliver(monkeypatch)
    assert row["status"] == ex.EXIT_DEAD and row["filled_contracts"] == 0
    assert not ex.is_sliver_exit(row)


def test_the_next_fill_accumulates_on_the_same_row_and_then_the_exit_is_done(monkeypatch):
    state, _row, _send1 = _sliver(monkeypatch)
    send = _send(_venue("o-rest", count=4, status="executed", fee="0.030000"))
    out = ex.place_exit(state, _position(), _decision(), sellable=4.99, send=send, persist=lambda s: None)
    row = out["row"]
    assert send.bodies[0]["count"] == "4.00", "whole contracts still held: floor(4.99)"
    assert row["status"] == ex.EXIT_FILLED
    assert row["filled_contracts"] == pytest.approx(4.01)
    assert row["fill_price"] == pytest.approx(0.96)
    assert row["exit_fee_dollars"] == pytest.approx(0.0302)
    assert row["attempt_filled_contracts"] == 4
    assert row["prior_attempts"][-1]["filled_contracts"] == pytest.approx(0.01)
    assert not ex.is_sliver_exit(row)
    again = ex.place_exit(state, _position(), _decision(), sellable=0.99, send=_send({}), persist=lambda s: None)
    assert again["refused"] == "duplicate", "one whole contract or more sold is a finished sale, as before"


def test_an_attempt_that_trades_nothing_leaves_the_sliver_standing(monkeypatch):
    state, _row, _send1 = _sliver(monkeypatch)
    send = _send({"order_id": "o-miss", "status": "canceled", "fill_count_fp": "0.00"})
    row = ex.place_exit(state, _position(), _decision(), sellable=4.99, send=send, persist=lambda s: None)["row"]
    assert row["status"] == ex.EXIT_FILLED and row["attempt_filled_contracts"] == 0
    assert row["filled_contracts"] == pytest.approx(0.01) and row["fill_price"] == pytest.approx(0.96)
    assert row["exit_fee_dollars"] == pytest.approx(0.0002)
    assert ex.is_sliver_exit(row)


def test_settlement_explains_the_accumulated_sale(monkeypatch):
    """The settlement row's opposite leg is everything the exit bought: 0.01 + 4."""
    state, _row, _send1 = _sliver(monkeypatch)
    send = _send(_venue("o-rest", count=4, status="executed", fee="0.030000"))
    row = ex.place_exit(state, _position(), _decision(), sellable=4.99, send=send, persist=lambda s: None)["row"]
    entry = _order(outcome=None)
    effect, exit_row = vs.exit_for_order(entry, {row["exit_key"]: row})
    assert effect == "sold"
    settlement = {"ticker": entry["venue_ticker"], "market_result": "no", "no_count_fp": "5.00", "yes_count_fp": "4.01"}
    assert vs._both_sides_is_our_partial_close(settlement, [(effect, exit_row)])
    pnl, detail = vs.exit_adjusted_pnl(entry, "won", exit_row)
    assert detail["contracts_sold"] == pytest.approx(4.01)
    assert pnl == pytest.approx(4.01 * 0.96 - 0.0302 + 0.99 * 1.0 - 4.5 - 0.0315, abs=1e-3)


def _tick(monkeypatch, state, venue_held, sent):
    _arm_live(monkeypatch)
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    ex._persist(state)
    monkeypatch.setattr(ex, "send_exit_order", lambda body: sent.append(body) or ex._exit_view(
        {**_venue(f"o{len(sent)}", count=float(body["count"]), status="executed", fee="0.010000"), "outcome_side": "yes"}))
    venue = {"status": "ok", "positions": {_order()["venue_ticker"]: -venue_held}}
    return ex.run_exit_tick(today=TODAY, orders=[_order()], quotes=_quotes([_market()]),
                            venue_positions=lambda: venue, now=NOW)


def test_the_tick_resends_a_sliver_exit_for_the_whole_contracts_left(monkeypatch):
    state, _row, _send1 = _sliver(monkeypatch)
    sent = []
    s = _tick(monkeypatch, state, 4.99, sent)
    assert s["live_exits"] == {"placed": 1} and sent[0]["count"] == "4.00"
    row = next(iter(ex.load_state()["exits"].values()))
    assert row["filled_contracts"] == pytest.approx(4.01) and not ex.is_sliver_exit(row)


def test_sliver_attempts_count_against_the_cap(monkeypatch):
    state, row, _send1 = _sliver(monkeypatch)
    row["prior_attempts"] = [{"status": "dead"}, {"status": "dead"}]
    sent = []
    s = _tick(monkeypatch, state, 4.99, sent)
    assert sent == [] and s["live_exits"] == {"unfilled_retry_limit": 1}


def test_a_one_contract_sliver_is_not_resent(monkeypatch):
    """1 held, 0.01 sold: nothing whole is left, so no order and no per-tick refusal."""
    _arm_live(monkeypatch)
    one = dict(fill_stake_dollars=0.90, requested_stake_dollars=0.90, fees_dollars=0.0063)
    position = _position(**one)
    state = ex._empty_state()
    send = _send(_venue("o-sliver", count=0.01))
    ex.place_exit(state, position, _decision(), sellable=1.0, send=send, persist=lambda s: None)
    sent = []
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    ex._persist(state)
    monkeypatch.setattr(ex, "send_exit_order", lambda body: sent.append(body) or {})
    venue = {"status": "ok", "positions": {_order()["venue_ticker"]: -0.99}}
    s = ex.run_exit_tick(today=TODAY, orders=[_order(**one)], quotes=_quotes([_market()]),
                         venue_positions=lambda: venue, now=NOW)
    assert sent == [] and s["live_exits"] == {"sliver_rest_under_one": 1}
