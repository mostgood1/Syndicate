"""Stage 1 in-game fast exit loop: paper only, in-play only, the slow tick's own rule."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import execution_exits_fast as fx

TODAY = "2026-10-20"
PREGAME = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
IN_PLAY = datetime(2026, 10, 20, 23, 45, tzinfo=timezone.utc)
TICKER = "KXNBAPTS-26OCT20PHINYK-PHIVEDGECOMBE77-10"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    for name in (
        "SYNDICATE_EXIT_FAST_LOOP",
        "SYNDICATE_EXIT_FAST_LOOP_SECONDS",
        "SYNDICATE_EXIT_FAST_POSITIONS_SECONDS",
        "SYNDICATE_EXIT_MODE",
        "SYNDICATE_EXIT_TAKE_PROFIT_MARGIN",
        "SYNDICATE_EXIT_FAIR_MARGIN",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _order(**overrides):
    base = {
        "idempotency_key": "b" * 24,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": TICKER,
        "status": "filled",
        "outcome": None,
        "selected_date": TODAY,
        "commence_time": "2026-10-20T23:30:00Z",
        "sport": "nba",
        "market": "player_points",
        "side": "over",
        "line": 9.5,
        "player_name": "VJ Edgecombe",
        "requested_price": 0.50,
        "requested_stake_dollars": 5.0,
        "fill_price": 0.50,
        "fill_stake_dollars": 5.0,
        "fees_dollars": 0.18,
        "model_edge_pct": None,
        "ev_pct": None,
    }
    base.update(overrides)
    return base


def _quotes(yes_bid="0.6500", yes_ask="0.6700"):
    return {
        "markets": {
            TICKER: {
                "ticker": TICKER,
                "status": "active",
                "yes_bid_dollars": yes_bid,
                "yes_ask_dollars": yes_ask,
                "no_bid_dollars": f"{1 - float(yes_ask):.4f}",
                "no_ask_dollars": f"{1 - float(yes_bid):.4f}",
                "yes_bid_size_fp": "30.00",
                "yes_ask_size_fp": "60.00",
            }
        },
        "errors": [],
    }


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _loop(orders, quotes, *, exits_state=None, persisted=None, dispatched=None):
    clock = _Clock()

    def _dispatch(**kw):
        if dispatched is None:
            raise AssertionError("dispatch called in a test that forbids it")
        dispatched.append(kw)
        return {"status": "ok", "mode": "live", "live_exits": {"placed": 1}, "reasons": {"triggered": 1}}

    loop = fx.FastExitLoop(
        today_fn=lambda: TODAY,
        orders_fn=lambda: orders,
        quotes_fn=lambda tickers: quotes,
        exits_state_fn=lambda: exits_state or {"watch": {}, "exits": {}},
        persist=(persisted.append if persisted is not None else (lambda s: None)),
        clock=clock,
        dispatch_fn=_dispatch,
    )
    return loop, clock


def test_mode_follows_the_slow_ticks_exit_mode_unless_pinned(monkeypatch):
    assert fx.fast_loop_mode() == "paper"  # SYNDICATE_EXIT_MODE absent = paper, so the follower is paper
    monkeypatch.setenv("SYNDICATE_EXIT_MODE", "live")
    assert fx.fast_loop_mode() == "live"  # absent fast flag FOLLOWS the live exit mode
    for raw, want in (("live", "live"), ("paper", "paper"), ("off", "off"), ("0", "off"), (" disabled ", "off"),
                      ("on", "paper"), ("typo", "paper")):
        monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", raw)
        assert fx.fast_loop_mode() == want, raw
    monkeypatch.setenv("SYNDICATE_EXIT_MODE", "paper")
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "live")
    assert fx.fast_loop_mode() == "paper"  # "live" cannot outrank a paper slow tick


def test_reachability_off_books_nothing_on_books_the_trigger(monkeypatch):
    """off != on: the same orders and quotes, a trigger only with the flag."""
    persisted: list = []
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "off")
    loop, _ = _loop([_order()], _quotes(), persisted=persisted)
    assert loop.step(now=IN_PLAY) == {"status": "off"}
    assert persisted == []

    monkeypatch.delenv("SYNDICATE_EXIT_FAST_LOOP")
    loop, _ = _loop([_order()], _quotes(), persisted=persisted)
    out = loop.step(now=IN_PLAY)
    assert out["status"] == "ok" and out["new_exits"] == 1
    (row,) = loop.state["exits"].values()
    # 10 contracts @0.50 + $0.18 fee; bid 0.65 less the exit fee clears the 0.08 margin.
    assert row["rule"].startswith("take_profit") and row["bid"] == 0.65
    assert persisted, "a new exit is persisted on the pass that booked it"


def test_pregame_positions_are_left_to_the_slow_tick(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
    loop, _ = _loop([_order()], _quotes())
    assert loop.step(now=PREGAME) == {"status": "idle", "positions": 0}


def test_first_trigger_only_and_slow_watch_context(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
    slow = {"watch": {"b" * 24: {"last_seen": "2026-10-20T23:31:00Z", "last_reason": "below_threshold", "hwm_edge": 0.01}},
            "exits": {}}
    loop, clock = _loop([_order()], _quotes(), exits_state=slow)
    loop.step(now=IN_PLAY)
    clock.t += 15
    out = loop.step(now=IN_PLAY)
    assert out["new_exits"] == 0
    (row,) = loop.state["exits"].values()
    assert row["slow_last_reason"] == "below_threshold" and row["slow_last_seen"] == "2026-10-20T23:31:00Z"
    assert loop.state["marks"]["b" * 24]["samples"] == 2


def test_below_margin_marks_but_does_not_exit(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
    loop, _ = _loop([_order()], _quotes(yes_bid="0.5200", yes_ask="0.5400"))
    out = loop.step(now=IN_PLAY)
    assert out["new_exits"] == 0 and out["marked"] == 1
    assert loop.state["marks"]["b" * 24]["last_reason"] == "below_threshold"


def test_a_position_sold_live_is_not_marked(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
    key = ex.exit_idempotency_key("b" * 24)
    sold = {"watch": {}, "exits": {key: {"mode": "live", "status": "filled", "filled_contracts": 10}}}
    loop, _ = _loop([_order()], _quotes(), exits_state=sold)
    assert loop.step(now=IN_PLAY)["status"] == "idle"


def test_never_writes_the_slow_ticks_document(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
    loop, _ = _loop([_order()], _quotes(), persisted=None)
    loop.persist = fx.persist_fast_state
    loop.step(now=IN_PLAY)
    assert fx.fast_path().exists()
    assert not ex.exits_path().exists()
    assert fx.load_fast_state()["exits"]


def test_the_module_has_no_order_path():
    """Stage 1 cannot sell: no order, cancel or credential name is imported or called."""
    source = Path(fx.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    forbidden = {"place_exit", "send_exit_order", "exit_order_body", "cancel_order", "kalshi_orders",
                 "kalshi_auth", "polymarket_us_orders", "reconcile_exit_orders", "_persist"}
    assert not (names & forbidden), names & forbidden


def test_worker_starts_the_thread_only_when_paper(monkeypatch):
    """Reachability of the worker wiring: off -> no thread; paper -> the loop's step runs."""
    import importlib
    import threading

    worker = importlib.import_module("scripts.run_live_odds_refresh_worker")
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "off")
    assert worker.start_fast_exit_loop() is False

    stepped = threading.Event()

    class _Stub:
        def __init__(self, **_kw):
            self.state = None

        def step(self):
            stepped.set()
            worker._FAST_EXIT_STOP.set()  # one pass, then the thread ends
            return {"status": "ok"}

    monkeypatch.setattr(fx, "FastExitLoop", _Stub)
    monkeypatch.delenv("SYNDICATE_EXIT_FAST_LOOP")  # absent = paper
    monkeypatch.setattr(worker, "_FAST_EXIT_THREAD", None)
    try:
        assert worker.start_fast_exit_loop() is True
        assert stepped.wait(5), "the started thread never ran a pass"
        worker._FAST_EXIT_THREAD.join(5)
        assert not worker._FAST_EXIT_THREAD.is_alive()
    finally:
        worker._FAST_EXIT_STOP.set()


def test_live_dispatch_reachability_and_its_refusals(monkeypatch):
    """off != on for SELLING: only a LIVE position, an ARMED rule, a live slow tick, once per entry."""
    order = _order()
    # paper slow tick -> the follower is paper -> no dispatch
    loop, _ = _loop([order], _quotes(), dispatched=None)
    assert loop.step(now=IN_PLAY)["live_dispatched"] == 0

    monkeypatch.setenv("SYNDICATE_EXIT_MODE", "live")
    sent: list = []
    loop, clock = _loop([order], _quotes(), dispatched=sent)
    out = loop.step(now=IN_PLAY)
    assert out["live_dispatched"] == 1 and len(sent) == 1
    assert sent[0]["orders"] == [order] and sent[0]["today"] == TODAY
    assert loop.state["live_dispatch"]["b" * 24]["live_exits"] == {"placed": 1}
    clock.t += 15
    assert loop.step(now=IN_PLAY)["live_dispatched"] == 0 and len(sent) == 1  # never twice

    # pinned paper -> marks, never dispatches
    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
    loop, _ = _loop([order], _quotes(), dispatched=None)
    assert loop.step(now=IN_PLAY)["live_dispatched"] == 0
    monkeypatch.delenv("SYNDICATE_EXIT_FAST_LOOP")

    # a PAPER-book position is never handed to the live path
    loop, _ = _loop([_order(mode="paper:kalshi", idempotency_key="c" * 24)], _quotes(), dispatched=None)
    assert loop.step(now=IN_PLAY)["live_dispatched"] == 0

    # a rule that is not armed live (model_fair only) is not dispatched
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.50")  # take_profit cannot fire
    loop, _ = _loop([_order(model_edge_pct=1.0, ev_pct=1.0)], _quotes(yes_bid="0.9900", yes_ask="0.9950"),
                    dispatched=None)
    out = loop.step(now=IN_PLAY)
    assert out["live_dispatched"] == 0


def test_a_settled_market_is_not_requoted(monkeypatch):
    seen: list = []
    clock = _Clock()
    q = _quotes()
    q["markets"][TICKER]["status"] = "finalized"
    loop = fx.FastExitLoop(today_fn=lambda: TODAY, orders_fn=lambda: [_order()],
                           quotes_fn=lambda tickers: (seen.append(list(tickers)) or q),
                           exits_state_fn=lambda: {"watch": {}, "exits": {}}, persist=lambda s: None, clock=clock)
    assert loop.step(now=IN_PLAY)["settled"] == ["b" * 24]
    clock.t += 120  # past the positions refresh
    assert loop.step(now=IN_PLAY)["status"] == "idle"
    assert len(seen) == 1


def test_exit_tick_is_serialised_by_one_lock():
    import threading

    assert isinstance(ex.EXIT_STATE_LOCK, type(threading.RLock()))
    with ex.EXIT_STATE_LOCK:  # re-entrant: the fast loop may dispatch while holding nothing else
        assert ex.run_exit_tick.__name__ == "run_exit_tick"
