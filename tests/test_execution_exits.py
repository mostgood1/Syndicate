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
        {"venue": "prophetx"},
        {"venue_ticker": None},
    ],
)
def test_graded_unfilled_and_unwatched_venue_rows_are_not_positions(overrides):
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
    assert grid["kalshi/live@0.04"]["triggered"] == 2 - 1  # B never cleared 0.04
    assert grid["kalshi/live@0.10"]["triggered"] == 0
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


# -- Polymarket (paper only) --------------------------------------------------


def _pm_order(**overrides):
    base = _order(
        idempotency_key="d" * 24,
        mode="paper",
        venue="paper:polymarket",
        venue_ticker="tsc-nfl-dal-hou-2026-10-19-total-47pt5",
        market="totals",
        side="over",
        line=47.5,
        player_name=None,
        fill_price=0.50,
        requested_price=0.50,
        fill_stake_dollars=5.0,
        fees_dollars=None,
        sport="nfl",
    )
    base.update(overrides)
    return base


def _pm_book(bid="0.6400", offer="0.6500", state="MARKET_STATE_OPEN"):
    return {
        "marketSlug": "tsc-nfl-dal-hou-2026-10-19-total-47pt5",
        "state": state,
        "bids": [{"px": {"value": bid, "currency": "USD"}, "qty": "120.00"}] if bid else [],
        "offers": [{"px": {"value": offer, "currency": "USD"}, "qty": "90.00"}] if offer else [],
    }


def test_polymarket_named_legs_map_and_team_legs_are_never_guessed():
    over, _ = ex.open_positions([_pm_order()], today=TODAY)
    under, _ = ex.open_positions([_pm_order(side="under")], today=TODAY)
    venue_said, _ = ex.open_positions([_pm_order(side="home", held_side="POSITION_RESOLUTION_SIDE_SHORT")], today=TODAY)
    team, skipped = ex.open_positions([_pm_order(side="home", market="h2h")], today=TODAY)
    assert over[0].family == "polymarket" and over[0].leg == "yes"
    assert under[0].leg == "no"
    assert venue_said[0].leg == "no"
    assert team == [] and skipped == {"polymarket_team_leg_unresolved": 1}


def test_polymarket_fee_is_flat_on_notional():
    p, _ = ex.open_positions([_pm_order()], today=TODAY)
    assert p[0].contracts == pytest.approx(10.0)
    assert p[0].entry_fee_dollars == pytest.approx(0.15)  # 150 bps x 10 contracts


def test_polymarket_book_reads_the_held_leg():
    yes = ex.normalize_polymarket_book("s", _pm_book())
    assert yes["status"] == "active" and yes["yes_bid_dollars"] == 0.64
    assert yes["no_bid_dollars"] == pytest.approx(0.35)  # NO sells at 1 - best YES offer
    expired = ex.normalize_polymarket_book("s", _pm_book(bid=None, offer=None, state="MARKET_STATE_EXPIRED"))
    assert expired["status"] == "expired" and expired["yes_bid_dollars"] is None


def test_polymarket_paper_exit_books_from_its_own_book(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    pm = lambda slugs: {"markets": {s: ex.normalize_polymarket_book(s, _pm_book()) for s in slugs}, "errors": []}  # noqa: E731
    summary = ex.run_exit_tick(
        today=TODAY, orders=[_pm_order(), _order(mode="paper", venue="paper:kalshi")],
        quotes=_quotes([_market(no_bid_dollars="0.9100")]), polymarket_quotes=pm, now=NOW,
    )
    assert summary["by_venue"] == {"kalshi": 1, "polymarket": 1}
    assert summary["polymarket_quoted"] == 1 and summary["new_paper_exits"] == 1
    (row,) = ex.load_state()["exits"].values()
    assert row["family"] == "polymarket" and row["bid"] == 0.64
    assert row["realized_pnl_dollars"] == pytest.approx(10 * (0.64 - 0.50) - 0.15 - 0.15, abs=0.01)


def test_a_kalshi_ticker_never_prices_a_polymarket_position(monkeypatch):
    """Quotes are keyed by venue: the same id on the other venue is not a quote."""
    slug = "tsc-nfl-dal-hou-2026-10-19-total-47pt5"
    kalshi_with_same_id = lambda t: {"markets": {slug: _market(ticker=slug, yes_bid_dollars="0.9900")}, "errors": []}  # noqa: E731
    summary = ex.run_exit_tick(today=TODAY, orders=[_pm_order()], quotes=kalshi_with_same_id,
                               polymarket_quotes=lambda s: {"markets": {}, "errors": []}, now=NOW)
    assert summary["reasons"] == {"unquoted": 1}


def test_a_live_polymarket_position_is_never_sold(monkeypatch):
    _arm_live(monkeypatch)
    positions, _ = ex.open_positions([_pm_order(mode="live", venue="polymarket")], today=TODAY)
    out = ex.place_exit(ex._empty_state(), positions[0], {"bid": 0.64}, sellable=10.0,
                        send=_never_send, persist=_never_send)
    assert out["refused"] == "venue_live_exit_unbuilt"


def test_counterfactual_splits_by_venue(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.05")
    orders = [_pm_order()]
    pm = lambda slugs: {"markets": {s: ex.normalize_polymarket_book(s, _pm_book()) for s in slugs}, "errors": []}  # noqa: E731
    ex.run_exit_tick(today=TODAY, orders=orders, quotes=_quotes([]), polymarket_quotes=pm, now=NOW)
    orders[0]["outcome"] = "lost"
    report = ex.exit_counterfactual(ex.load_state(), orders)
    assert report["by_venue"]["polymarket"]["n"] == 1
    assert "polymarket/paper@0.10" in report["by_margin"]


# -- partial (one-contract) live sales ------------------------------------------


def _filled_one(monkeypatch, *, limit_price=None, purpose="sell_body_verification"):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    sent = []

    def send(body):
        sent.append(body)
        return {"state": "filled", "filled_count": 1, "fill_cost_dollars": 0.12,
                "fees_dollars": 0.01, "order_id": "ord-1", "venue_status": "executed"}

    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=send, persist=lambda s: None,
                        max_contracts=1, limit_price=limit_price, purpose=purpose)
    return state, out, sent


def test_max_contracts_sells_exactly_that_many(monkeypatch):
    state, out, sent = _filled_one(monkeypatch, limit_price=0.96)
    assert sent[0]["count"] == "1.00"
    assert sent[0]["price"] == "0.0400"  # NO limit 0.96 -> YES bid at 0.04
    row = out["row"]
    assert row["requested_contracts"] == 1 and row["limit_price"] == 0.96
    assert row["purpose"] == "sell_body_verification" and row["filled_contracts"] == 1
    assert row["fill_price"] == pytest.approx(0.88)


def test_a_partial_live_sale_reduces_what_is_held(monkeypatch):
    state, _, _ = _filled_one(monkeypatch)
    held, fully_sold = ex.net_of_live_sales([_position()], state)
    assert fully_sold == 0 and held[0].contracts == 4.0
    assert held[0].entry_fee_dollars == pytest.approx(0.0315 * 4 / 5, abs=1e-4)
    rec = ex.reconcile_positions(held, {"status": "ok", "positions": {held[0].ticker: -4.0}})
    assert rec["status"] == "ok" and rec["mismatches"] == []


def test_a_paper_exit_row_never_reduces_a_holding():
    state = ex._empty_state()
    state["exits"][ex.exit_idempotency_key("a" * 24)] = {"mode": "paper", "status": ex.EXIT_PAPER_FILLED,
                                                          "filled_contracts": 5, "entry_key": "a" * 24}
    held, _ = ex.net_of_live_sales([_position()], state)
    assert held[0].contracts == 5.0


def test_counterfactual_grades_a_partial_sale_on_the_contracts_sold(monkeypatch):
    state, _, _ = _filled_one(monkeypatch, purpose=None)  # a RULE's sale, not an operator's
    order = _order(outcome="won")  # NO paid out: holding that 1 contract would have made 1 - 0.90
    report = ex.exit_counterfactual(state, [order])
    bucket = report["by_mode"]["live/live"]
    fee_share = 0.0315 / 5
    assert bucket["n"] == 1
    assert bucket["exit_pnl"] == pytest.approx(1 * (0.88 - 0.90) - 0.01 - fee_share, abs=0.01)
    assert bucket["hold_pnl"] == pytest.approx(1 * (1.0 - 0.90) - fee_share, abs=0.01)


# -- the create response does not price the fill (measured 2026-10-19) --------


def test_an_unpriced_create_response_is_read_back(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    reads = []

    def send(_body):  # what Kalshi's POST answered: a count, nothing else
        return {"state": "filled", "filled_count": 1, "fill_cost_dollars": None, "fees_dollars": None,
                "order_id": "ord-7", "venue_status": None}

    def read_back(order_id):
        reads.append(order_id)
        return {"status": "ok", "order": {"status": "executed", "fill_count_fp": "1.00",
                                          "taker_fill_cost_dollars": "0.130000", "taker_fees_dollars": "0.008000",
                                          "order_id": "ord-7"}}

    out = ex.place_exit(state, _position(), _decision(), sellable=5.0, send=send, persist=lambda s: None,
                        read_back=read_back, max_contracts=1)
    assert reads == ["ord-7"]
    row = out["row"]
    assert row["fill_price"] == pytest.approx(0.87) and row["exit_fee_dollars"] == pytest.approx(0.008)
    assert ex.unreconciled_exits(state) == []


def test_an_unpriced_fill_is_unreconciled_until_priced(monkeypatch):
    _arm_live(monkeypatch)
    state = ex._empty_state()
    out = ex.place_exit(
        state, _position(), _decision(), sellable=5.0, persist=lambda s: None, max_contracts=1,
        send=lambda b: {"state": "filled", "filled_count": 1, "order_id": "ord-8"},
        read_back=lambda oid: {"status": "error", "reason": "timeout"},
    )
    assert out["row"]["fill_price"] is None
    assert len(ex.unreconciled_exits(state)) == 1
    blocked = ex.place_exit(state, _position(idempotency_key="c" * 24), _decision(), sellable=5.0,
                            send=_never_send, persist=lambda s: None)
    assert blocked["refused"] == "unreconciled_exits"


def test_operator_sales_are_kept_out_of_the_rule_counterfactual(monkeypatch):
    state, _, _ = _filled_one(monkeypatch)  # purpose=sell_body_verification
    report = ex.exit_counterfactual(state, [_order(outcome="won")])
    assert report["manual_excluded"] == 1 and report["graded"] == 0


def test_no_live_blockers_remain_after_the_measured_sale():
    assert ex.LIVE_BLOCKERS == ()
