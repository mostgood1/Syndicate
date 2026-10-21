"""In-game entry rule, PAPER ONLY: the rule, the grading, and that it cannot trade."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from syndicate.features.shared import inplay_entries_paper as ip

T0 = 1_761_000_000.0
TICKER = "KXNHLSPREAD-26OCT21TORCBJ-TOR2"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("SYNDICATE_INPLAY_ENTRIES_PAPER", raising=False)
    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")


def _market(ya="0.3000", yb="0.2900", na="0.7100", status="active", result=""):
    return {"ticker": TICKER, "event_ticker": "KXNHLSPREAD-26OCT21TORCBJ", "status": status,
            "yes_sub_title": "Toronto wins by over 1.5 goals", "floor_strike": 1.5,
            "yes_ask_dollars": ya, "yes_bid_dollars": yb, "no_ask_dollars": na, "result": result}


def _other():
    m = _market()
    m.update({"ticker": "KXNHLSPREAD-26OCT21TORCBJ-CBJ2", "yes_sub_title": "Columbus wins by over 1.5 goals"})
    return m


def _event(p_tor=0.40, books=4, age=30.0, poll_t=T0):
    upd = ip._iso(poll_t - age)
    dec_tor, dec_cbj = 1 / p_tor, 1 / (1 - p_tor)
    return {"id": "ev1", "home_team": "Columbus Blue Jackets", "away_team": "Toronto Maple Leafs",
            "commence_time": ip._iso(T0 - 3600),
            "bookmakers": [{"key": f"b{i}", "markets": [{"key": "spreads", "last_update": upd, "outcomes": [
                {"name": "Toronto Maple Leafs", "price": dec_tor, "point": -1.5},
                {"name": "Columbus Blue Jackets", "price": dec_cbj, "point": 1.5}]}]} for i in range(books)]}


def test_rule_fires_only_inside_every_gate():
    ok = dict(market=_market(), event=_event(), poll_t=T0, since_score_s=400, mid_move_60s=0.01, now_t=T0 + 10)
    d = ip.decide(**ok)
    assert d and d["leg"] == "yes" and d["edge"] >= ip.MIN_EDGE  # fair 0.40 vs ask 0.30
    assert ip.decide(**{**ok, "since_score_s": 120}) is None  # near a score change
    assert ip.decide(**{**ok, "since_score_s": None}) is None  # unknown is not quiet
    assert ip.decide(**{**ok, "mid_move_60s": 0.05}) is None  # Kalshi still moving
    assert ip.decide(**{**ok, "mid_move_60s": None}) is None
    assert ip.decide(**{**ok, "event": _event(books=2)}) is None  # too few books
    assert ip.decide(**{**ok, "event": _event(age=300)}) is None  # stale book quotes
    assert ip.decide(**{**ok, "now_t": T0 + 200}) is None  # stale poll
    assert ip.decide(**{**ok, "event": _event(p_tor=0.32)}) is None  # edge under 3% after fee
    assert ip.decide(**{**ok, "market": _market(status="closed")}) is None


def _loop(markets_by_pass, espn_states, clock_ts, persisted):
    calls = {"i": 0}

    def get(url):
        if url.startswith(ip.ESPN):
            st, sc = espn_states[min(calls["i"], len(espn_states) - 1)]
            return {"events": [{"competitions": [{"status": {"type": {"state": st}}, "competitors": [
                {"team": {"abbreviation": "TOR"}, "score": sc[0]}, {"team": {"abbreviation": "CBJ"}, "score": sc[1]}]}]}]}
        if url.startswith(ip.ODDSAPI):
            return [_event(poll_t=clock_ts[min(calls["i"], len(clock_ts) - 1)])]
        return {"markets": markets_by_pass[min(calls["i"], len(markets_by_pass) - 1)]}

    clock = {"t": clock_ts[0]}
    loop = ip.PaperEntryLoop(today_fn=lambda: "2026-10-21", clock=lambda: clock["t"], get=get,
                             tickers_fn=lambda d: [TICKER, "KXNHLSPREAD-26OCT21TORCBJ-CBJ2"],
                             load=lambda: {"entries": {}}, persist=persisted.append)

    def advance(i):
        calls["i"] = i
        clock["t"] = clock_ts[i]
        loop.books_t = None  # force a fresh poll each simulated pass
        loop.espn_t = None
        return loop.step()

    return loop, advance


def test_records_grades_and_settles_a_would_be_entry():
    persisted: list = []
    ts = [T0, T0 + 200, T0 + 220, T0 + 290, T0 + 530, T0 + 600]
    m = [_market(), _other()]
    moved = [_market(ya="0.3600", yb="0.3500", na="0.6500"), _other()]
    final = [_market(status="finalized", result="yes"), _other()]
    loop, advance = _loop([m, m, m, moved, moved, final], [("in", ("1", "0"))], ts, persisted)
    assert advance(0)["booked"] == 0  # first sight of an in-play game = just changed: wait
    assert advance(1)["booked"] == 0  # 200 s quiet, but only ONE mid sample inside the 60 s window: no stability read
    out = advance(2)
    assert out["booked"] == 1
    (e,) = loop.doc["entries"].values()
    assert e["leg"] == "yes" and e["ask"] == 0.30
    advance(3)  # +70 s: markout_60 graded from the moved mid
    assert e["markout_60"] == round(0.355 - 0.30 - e["fee"], 4)
    advance(4)  # +310 s
    assert e["markout_300"] is not None
    advance(5)
    assert e["settled"] == "yes" and e["pnl_1c"] == round(1.0 - 0.30 - e["fee"], 4)
    assert persisted


def test_once_per_ticker_leg_per_day_and_budget():
    persisted: list = []
    ts = [T0, T0 + 200, T0 + 220, T0 + 240]
    m = [_market(), _other()]
    loop, advance = _loop([m] * 4, [("in", ("1", "0"))], ts, persisted)
    for i in range(4):
        advance(i)
    assert len(loop.doc["entries"]) == 1


def test_off_switch(monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRIES_PAPER", "off")
    loop = ip.PaperEntryLoop(today_fn=lambda: "2026-10-21", get=lambda u: {}, tickers_fn=lambda d: [],
                             load=lambda: {"entries": {}}, persist=lambda d: None)
    assert loop.step() == {"status": "off"}


def test_the_module_cannot_trade():
    tree = ast.parse(Path(ip.__file__).read_text(encoding="utf-8"))
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
    forbidden = {"place_order", "check_order", "guarded_submit", "kalshi_orders", "kalshi_submitter", "submit_order",
                 "kalshi_auth", "signed_request", "execution_ledger", "execution_guard", "polymarket_us_orders",
                 "place_exit", "cancel_order", "execute_portfolio", "OrderRequest"}
    hits = {n for n in names if any(f in (n or "") for f in forbidden)}
    assert not hits, hits
