"""The exit path: paper sell-to-close, its own key space, and the live seam's discipline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared.execution_ledger import _is_our_key

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)
TODAY = "2026-10-19"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    for name in (
        "SYNDICATE_EXIT_MODE",
        "SYNDICATE_EXIT_LIVE_ARMED",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_KILL_SWITCH",
        "SYNDICATE_EXIT_TAKE_PROFIT_MARGIN",
        "SYNDICATE_EXIT_FAIR_MARGIN",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _order(**overrides):
    base = {
        "idempotency_key": "a" * 24,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": "KXWNBAPTS-26OCT19ATLGS-GSKTHORNTON5-10",
        "status": "filled",
        "outcome": None,
        "selected_date": TODAY,
        "commence_time": "2026-10-19T23:30:00Z",
        "sport": "wnba",
        "market": "player_points",
        "side": "under",
        "line": 9.5,
        "player_name": "Kayla Thornton",
        "requested_price": 0.90,
        "requested_stake_dollars": 4.5,
        "fill_price": 0.90,
        "fill_stake_dollars": 4.5,
        "fees_dollars": 0.0315,
        "model_edge_pct": None,
        "ev_pct": None,
    }
    base.update(overrides)
    return base


def _market(**overrides):
    base = {
        "ticker": "KXWNBAPTS-26OCT19ATLGS-GSKTHORNTON5-10",
        "status": "active",
        "yes_bid_dollars": "0.0200",
        "yes_ask_dollars": "0.0300",
        "no_bid_dollars": "0.9700",
        "no_ask_dollars": "0.9800",
        "yes_bid_size_fp": "100.00",
        "yes_ask_size_fp": "80.00",
    }
    base.update(overrides)
    return base


def _position(**overrides):
    positions, _ = ex.open_positions([_order(**overrides)], today=TODAY)
    assert len(positions) == 1
    return positions[0]


# -- identity -----------------------------------------------------------------


def test_exit_key_is_its_own_key_space():
    """The entry orphan scan claims 24-hex ids; an exit key must never be one."""
    key = ex.exit_idempotency_key("a" * 24)
    assert len(key) == 24 and key[0] == "x"
    assert not _is_our_key(key)
    assert ex.is_exit_key(key)
    assert ex.exit_idempotency_key("a" * 24) == key
    assert ex.exit_idempotency_key("b" * 24) != key


# -- (1) open-position ledger -------------------------------------------------


def test_a_filled_live_under_is_a_held_no_position():
    p = _position()
    assert p.leg == "no"
    assert p.contracts == 5.0
    assert p.entry_price == 0.90
    assert p.entry_fee_dollars == 0.0315 and not p.entry_fee_estimated


def test_paper_book_rows_are_watched_with_american_prices():
    p = _position(mode="paper", venue="paper:kalshi", fill_price=-150.0, requested_price=-150.0,
                  fill_stake_dollars=6.0, fees_dollars=None, side="over")
    assert p.mode == "paper" and p.leg == "yes"
    assert p.entry_price == pytest.approx(0.6)
    assert p.contracts == pytest.approx(10.0)
    assert p.entry_fee_estimated and p.entry_fee_dollars > 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"outcome": "won"},
        {"status": "submitted"},
        {"venue": "polymarket"},
        {"venue_ticker": None},
    ],
)
def test_graded_unfilled_and_non_kalshi_rows_are_not_positions(overrides):
    positions, _ = ex.open_positions([_order(**overrides)], today=TODAY)
    assert positions == []


def test_lookback_and_unmappable_rows_are_counted_not_dropped():
    positions, skipped = ex.open_positions(
        [_order(selected_date="2026-10-01"), _order(idempotency_key="b" * 24, side="sideways")],
        today=TODAY,
    )
    assert positions == []
    assert skipped == {"outside_lookback": 1, "unmappable_leg": 1}


def test_model_probability_matches_the_sizing_derivation():
    # fair = (ev/100 + 1)/(profit + 1); model = fair + edge/100
    p = _position(model_edge_pct=5.0, ev_pct=2.0, fill_price=0.5, requested_price=0.5, fill_stake_dollars=5.0)
    assert p.model_probability == pytest.approx((1.02 / 2.0) + 0.05, abs=1e-4)


def test_reconcile_caps_sellable_at_what_the_venue_holds():
    p = _position()
    ok = ex.reconcile_positions([p], {"status": "ok", "positions": {p.ticker: -5.0}})
    assert ok["status"] == "ok" and ok["sellable"][p.entry_key] == 5.0
    short = ex.reconcile_positions([p], {"status": "ok", "positions": {p.ticker: -3.0}})
    assert short["status"] == "mismatch" and short["sellable"][p.entry_key] == 3.0
    wrong_leg = ex.reconcile_positions([p], {"status": "ok", "positions": {p.ticker: 5.0}})
    assert wrong_leg["sellable"][p.entry_key] == 0.0
    unread = ex.reconcile_positions([p], {"status": "error", "reason": "http_500"})
    assert unread["status"] == "venue_unread" and unread["sellable"] == {}


# -- (3) the rule -------------------------------------------------------------


def test_take_profit_fires_net_of_both_fees():
    p = _position()  # NO at 0.90 + fee
    d = ex.evaluate_exit(p, _market(), margin=0.05, fair_buffer=0.0, now=NOW)
    assert d["rule"] == ex.RULE_TAKE_PROFIT
    assert d["bid"] == 0.97
    assert d["edge_per_contract"] == pytest.approx(
        0.97 - d["exit_fee_dollars"] / 5 - (0.90 + 0.0315 / 5), abs=1e-4
    )
    assert d["in_play"] is False


def test_below_margin_does_not_fire():
    d = ex.evaluate_exit(_position(), _market(no_bid_dollars="0.9200"), margin=0.05, fair_buffer=0.0, now=NOW)
    assert d["rule"] is None and d["reason"] == "below_threshold"


def test_model_fair_rule_fires_when_the_net_bid_reaches_the_model():
    p = _position(model_edge_pct=3.0, ev_pct=1.0, fill_price=0.5, requested_price=0.5,
                  fill_stake_dollars=5.0, side="over")
    d = ex.evaluate_exit(p, _market(yes_bid_dollars="0.5800"), margin=0.5, fair_buffer=0.0, now=NOW)
    assert d["rule"] == ex.RULE_MODEL_FAIR


@pytest.mark.parametrize(
    "market, reason",
    [(None, "unquoted"), (_market(status="closed"), "market_closed"), (_market(no_bid_dollars="0.0000"), "no_bid")],
)
def test_no_decision_without_a_live_bid(market, reason):
    d = ex.evaluate_exit(_position(), market, margin=0.0, fair_buffer=0.0, now=NOW)
    assert d["rule"] is None and d["reason"] == reason


# -- (2) the sell order -------------------------------------------------------


def test_sell_body_reverses_the_entry_leg_and_is_reduce_only():
    no = ex.exit_order_body(_position(), bid=0.97, count=5)
    assert no["side"] == "bid" and no["price"] == "0.0300"  # sell NO == buy YES at 1-bid
    assert no["reduce_only"] is True and no["count"] == "5.00"
    assert no["client_order_id"] == ex.exit_idempotency_key("a" * 24)
    yes = ex.exit_order_body(_position(side="over"), bid=0.40, count=2)
    assert yes["side"] == "ask" and yes["price"] == "0.4000"
    with pytest.raises(ex.ExitBuildError):
        ex.exit_order_body(_position(), bid=0.97, count=0)


def _decision():
    return ex.evaluate_exit(_position(), _market(), margin=0.05, fair_buffer=0.0, now=NOW)


def _arm_live(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXIT_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setattr(
        "syndicate.features.shared.execution_guard.kill_switch_engaged",
        lambda: {"engaged": False, "source": "clear"},
    )


def _never_send(_body):
    raise AssertionError("an order was sent")


@pytest.mark.parametrize(
    "env, token",
    [
        ({}, "exit_mode_not_live"),
        ({"SYNDICATE_EXIT_MODE": "live"}, "exit_not_armed"),
        ({"SYNDICATE_EXIT_MODE": "live", "SYNDICATE_EXIT_LIVE_ARMED": "1"}, "exit_not_armed"),
    ],
)
def test_live_exit_refuses_without_every_switch(monkeypatch, env, token):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    state = ex._empty_state()
    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=_never_send, persist=_never_send)
    assert out["refused"] == token
    assert state["exits"] == {}


def test_kill_switch_stops_a_live_exit(monkeypatch):
    _arm_live(monkeypatch)
    monkeypatch.setenv("SYNDICATE_EXECUTION_KILL_SWITCH", "1")
    monkeypatch.setattr(
        "syndicate.features.shared.execution_guard.kill_switch_engaged",
        lambda: {"engaged": True, "source": "env"},
    )
    state = ex._empty_state()
    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=_never_send, persist=_never_send)
    assert out["refused"] == "kill_switch:env" and state["exits"] == {}


def test_a_paper_position_is_never_sold_live(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    out = ex.place_exit(state, _position(mode="paper", venue="paper:kalshi"), _decision(),
                        sellable=5.0, send=_never_send, persist=_never_send)
    assert out["refused"] == "paper_position"


def test_nothing_held_at_the_venue_means_nothing_sent(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    out = ex.place_exit(state, _position(), _decision(), sellable=0.0, send=_never_send, persist=_never_send)
    assert out["refused"] == "exit_below_one_contract" and state["exits"] == {}


def test_live_exit_is_written_ahead_then_completed(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    seen_at_send = []
    persisted = []

    def persist(s):
        persisted.append({k: dict(v) for k, v in s["exits"].items()})

    def send(body):
        # The row must already be ON DISK when the order leaves.
        seen_at_send.append([r["status"] for r in persisted[-1].values()])
        return {"state": "filled", "filled_count": 5, "fill_cost_dollars": 0.15,
                "fees_dollars": 0.01, "order_id": "ord-1", "venue_status": "executed"}

    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=send, persist=persist)
    assert out["placed"] is True
    assert seen_at_send == [[ex.EXIT_SUBMITTED]]
    row = out["row"]
    assert row["status"] == ex.EXIT_FILLED and row["filled_contracts"] == 5
    assert row["fill_price"] == pytest.approx(0.97)  # 0.03 YES cost -> 0.97 on our NO leg
    # Idempotent: the same entry cannot be sold twice.
    again = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=_never_send, persist=persist)
    assert again["refused"] == "duplicate"


def test_a_send_that_raised_stays_failed_and_blocks_new_exits(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()

    def boom(_body):
        raise TimeoutError("response lost")

    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=boom, persist=lambda s: None)
    assert out["row"]["status"] == ex.EXIT_FAILED
    other = _position(idempotency_key="c" * 24)
    blocked = ex.place_exit(state, other, _decision(), sellable=5.0, send=_never_send, persist=lambda s: None)
    assert blocked["refused"] == "unreconciled_exits"


def test_reconcile_finds_a_lost_response_by_client_order_id(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    ex.place_exit(state, _position(), _decision(), sellable=5.0,
                  send=lambda b: (_ for _ in ()).throw(TimeoutError("lost")), persist=lambda s: None)
    key = ex.exit_idempotency_key("a" * 24)
    book = {"orders": [{"client_order_id": key, "order_id": "ord-9", "status": "executed",
                        "fill_count_fp": "5.00", "taker_fill_cost_dollars": "0.15",
                        "taker_fees_dollars": "0.01"}]}
    result = ex.reconcile_exit_orders(state, fetch_book=lambda: book)
    assert result == {"checked": 1, "changed": 1}
    assert state["exits"][key]["status"] == ex.EXIT_FILLED
    assert ex.unreconciled_exits(state) == []


# -- the tick -----------------------------------------------------------------


def _quotes(markets):
    return lambda tickers: {"markets": {m["ticker"]: m for m in markets if m["ticker"] in tickers}, "errors": []}


def test_off_is_off_and_paper_is_on(monkeypatch):
    """Reachability: the mode flag must change what happens."""
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    orders = [_order(mode="paper", venue="paper:kalshi")]
    kwargs = dict(today=TODAY, orders=orders, quotes=_quotes([_market()]),
                  venue_positions=lambda: {"status": "ok", "positions": {}}, now=NOW)
    monkeypatch.setenv("SYNDICATE_EXIT_MODE", "off")
    assert ex.run_exit_tick(**kwargs) == {"status": "off"}
    assert ex.load_state()["exits"] == {}
    monkeypatch.delenv("SYNDICATE_EXIT_MODE")
    summary = ex.run_exit_tick(**kwargs)
    assert summary["mode"] == "paper" and summary["new_paper_exits"] == 1
    assert len(ex.load_state()["exits"]) == 1


def test_paper_tick_books_one_exit_per_entry_and_tracks_the_high_water_mark(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    orders = [_order()]  # a REAL live position, watched in paper mode
    venue = lambda: {"status": "ok", "positions": {orders[0]["venue_ticker"]: -5.0}}  # noqa: E731
    first = ex.run_exit_tick(today=TODAY, orders=orders, quotes=_quotes([_market(no_bid_dollars="0.9300")]),
                             venue_positions=venue, now=NOW)
    assert first["new_paper_exits"] == 0 and first["venue_reconcile"]["status"] == "ok"
    second = ex.run_exit_tick(today=TODAY, orders=orders, quotes=_quotes([_market()]), venue_positions=venue, now=NOW)
    third = ex.run_exit_tick(today=TODAY, orders=orders, quotes=_quotes([_market(no_bid_dollars="0.9900")]),
                             venue_positions=venue, now=NOW)
    assert second["new_paper_exits"] == 1 and third["new_paper_exits"] == 0
    state = ex.load_state()
    (row,) = state["exits"].values()
    assert row["mode"] == "paper" and row["entry_mode"] == "live" and row["bid"] == 0.97
    watch = state["watch"]["a" * 24]
    assert watch["samples"] == 3 and watch["hwm_bid"] == 0.99


def test_paper_mode_never_reaches_the_sell_path(monkeypatch):
    monkeypatch.setattr(ex, "send_exit_order", _never_send)
    monkeypatch.setattr(ex, "place_exit", lambda *a, **k: _never_send(None))
    ex.run_exit_tick(today=TODAY, orders=[_order()], quotes=_quotes([_market()]),
                     venue_positions=lambda: {"status": "ok", "positions": {}}, now=NOW)


def test_an_unreadable_document_is_not_overwritten(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file_result", lambda path: (None, False)
    )
    with pytest.raises(RuntimeError):
        ex.run_exit_tick(today=TODAY, orders=[], quotes=_quotes([]), now=NOW)


# -- the readout --------------------------------------------------------------


def test_counterfactual_grades_exit_against_hold(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    orders = [_order(), _order(idempotency_key="b" * 24, venue_ticker="KX-B")]
    ex.run_exit_tick(today=TODAY, orders=orders,
                     quotes=_quotes([_market(), _market(ticker="KX-B", no_bid_dollars="0.9100")]),
                     venue_positions=lambda: {"status": "ok", "positions": {}}, now=NOW)
    state = ex.load_state()
    orders[0]["outcome"] = "lost"  # the under we sold at 0.97 then lost
    orders[1]["outcome"] = "won"
    report = ex.exit_counterfactual(state, orders)
    assert report["graded"] == 1 and report["pending"] == 0
    bucket = report["by_mode"]["live/paper"]
    hold = 5 * (0.0 - 0.90) - 0.0315
    assert bucket["hold_pnl"] == pytest.approx(hold, abs=0.01)
    assert bucket["delta"] > 0 and bucket["exit_better"] == 1
    grid = report["by_margin"]
    # Position A reached ~+0.06 net: credited at 0.04, held at 0.10.
    assert grid["live@0.04"]["triggered"] == 2 - 1  # B never cleared 0.04
    assert grid["live@0.10"]["triggered"] == 0
    assert report["watched_graded"] == 2


# -- worker wiring: the tick must actually reach the exit path --------------


@pytest.fixture
def worker(monkeypatch):
    import importlib

    mod = importlib.import_module("scripts.run_live_odds_refresh_worker")
    mod._LAST_EXECUTION_AT = None
    monkeypatch.delenv("SYNDICATE_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("SYNDICATE_EXECUTION_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr("pipeline.execute_portfolio.run_execution", lambda date, **kw: {"status": "ok"})
    monkeypatch.setattr("pipeline.execute_portfolio.verify_order_paths", lambda *a, **k: {"venues": {}})
    monkeypatch.setattr(
        "syndicate.features.shared.venue_settlement.settle_from_venue", lambda *a, **k: {"status": "ok"}
    )
    monkeypatch.setattr(
        "syndicate.features.shared.venue_balances.record_venue_balances", lambda **k: {"venues": {}}
    )
    return mod


def test_the_execution_tick_reaches_the_exit_tick(worker, monkeypatch):
    calls = []
    monkeypatch.setattr(ex, "run_exit_tick", lambda **kw: calls.append(kw) or {"status": "ok"})
    worker._run_execution_tick()
    assert calls == [], "the exit tick ran with execution disabled"
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    worker._run_execution_tick()
    assert len(calls) == 1 and calls[0]["today"]


def test_a_raising_exit_tick_does_not_stop_placement(worker, monkeypatch):
    placed = []
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(ex, "run_exit_tick", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("pipeline.execute_portfolio.run_execution", lambda date, **kw: placed.append(date) or {})
    worker._run_execution_tick()
    assert len(placed) == 1
