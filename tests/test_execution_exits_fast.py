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


def _loop(orders, quotes, *, exits_state=None, persisted=None):
    clock = _Clock()
    loop = fx.FastExitLoop(
        today_fn=lambda: TODAY,
        orders_fn=lambda: orders,
        quotes_fn=lambda tickers: quotes,
        exits_state_fn=lambda: exits_state or {"watch": {}, "exits": {}},
        persist=(persisted.append if persisted is not None else (lambda s: None)),
        clock=clock,
    )
    return loop, clock


def test_off_unless_exactly_paper(monkeypatch):
    assert fx.fast_loop_mode() == "off"
    for raw in ("live", "on", "1", "Paper "):
        monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", raw)
        assert fx.fast_loop_mode() == ("paper" if raw.strip().lower() == "paper" else "off")


def test_reachability_off_books_nothing_on_books_the_trigger(monkeypatch):
    """off != on: the same orders and quotes, a trigger only with the flag."""
    persisted: list = []
    loop, _ = _loop([_order()], _quotes(), persisted=persisted)
    assert loop.step(now=IN_PLAY) == {"status": "off"}
    assert persisted == []

    monkeypatch.setenv("SYNDICATE_EXIT_FAST_LOOP", "paper")
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
