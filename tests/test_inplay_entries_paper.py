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
                             tickers_fn=lambda d, s="nhl": [TICKER, "KXNHLSPREAD-26OCT21TORCBJ-CBJ2"],
                             load=lambda: {"entries": {}}, persist=persisted.append)

    def advance(i):
        calls["i"] = i
        clock["t"] = clock_ts[i]
        loop.books_t = {}  # force a fresh poll each simulated pass
        loop.espn_t = {}
        loop.last_pass_t = None
        loop.sleep = lambda s: None
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
    loop = ip.PaperEntryLoop(today_fn=lambda: "2026-10-21", get=lambda u: {}, tickers_fn=lambda d, s="nhl": [],
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


# -- all-sports extension (user 2026-10-23) ------------------------------------------------------


def test_classify_every_full_game_shape():
    assert ip.classify({"ticker": "KXNHLSPREAD-26OCT21TORCBJ-TOR2", "yes_sub_title": "Toronto wins by over 1.5 goals",
                        "floor_strike": 1.5}) == ("spreads", "Toronto", 1.5)
    assert ip.classify({"ticker": "KXNBATOTAL-26OCT22CHIMIL-215", "yes_sub_title": "Over 214.5 points",
                        "floor_strike": 214.5}) == ("totals", "Over", 214.5)
    assert ip.classify({"ticker": "KXNBAGAME-26OCT22CHIMIL-MIL", "yes_sub_title": "Milwaukee",
                        "floor_strike": None}) == ("h2h", "Milwaukee", None)
    assert ip.classify({"ticker": "KXEPLGAME-26OCT25ARSCHE-TIE", "yes_sub_title": "Tie"}) is None
    assert ip.classify({"ticker": "KXNBAPTS-26OCT22CHIMIL-X", "yes_sub_title": "Giannis: 30+"}) is None


def _two_way(key, outs, upd):
    return {"key": key, "last_update": upd, "outcomes": outs}


def test_book_fair_totals_and_h2h_and_skips_three_way():
    upd = ip._iso(T0 - 10)
    ev = {"bookmakers": [{"key": f"b{i}", "markets": [
        _two_way("totals", [{"name": "Over", "price": 1 / 0.55, "point": 214.5},
                            {"name": "Under", "price": 1 / 0.45, "point": 214.5}], upd),
        _two_way("h2h", [{"name": "Milwaukee Bucks", "price": 1 / 0.62}, {"name": "Chicago Bulls", "price": 1 / 0.38}], upd),
    ]} for i in range(3)] + [{"key": "eu3way", "markets": [{"key": "h2h", "last_update": upd, "outcomes": [
        {"name": "Milwaukee Bucks", "price": 2.0}, {"name": "Chicago Bulls", "price": 3.0}, {"name": "Draw", "price": 9.0}]}]}]}
    fair, n = ip.book_fair(ev, "Over", 214.5, T0, kind="totals")
    assert n == 3 and abs(fair - 0.55) < 1e-9
    fair, n = ip.book_fair(ev, "Milwaukee", None, T0, kind="h2h")
    assert n == 3 and abs(fair - 0.62) < 1e-9  # the 3-way market is not counted


def test_nba_moneyline_books_through_the_multi_sport_loop():
    """Reachability for a non-NHL sport: its own ESPN + OddsAPI URLs, h2h, score gate 0 for basketball."""
    tick = "KXNBAGAME-26OCT22CHIMIL-MIL"
    upd = ip._iso(T0 - 10)
    book = {"id": "nba1", "home_team": "Milwaukee Bucks", "away_team": "Chicago Bulls",
            "commence_time": ip._iso(T0 - 3600),
            "bookmakers": [{"key": f"b{i}", "markets": [_two_way("h2h", [
                {"name": "Milwaukee Bucks", "price": 1 / 0.62}, {"name": "Chicago Bulls", "price": 1 / 0.38}], upd)]}
                for i in range(4)]}
    seen_urls: list = []

    def get(url):
        seen_urls.append(url)
        if url.startswith(ip.espn_url("nba")):
            return {"events": [{"competitions": [{"status": {"type": {"state": "in"}}, "competitors": [
                {"team": {"abbreviation": "MIL"}, "score": "50"}, {"team": {"abbreviation": "CHI"}, "score": "48"}]}]}]}
        if url.startswith(ip.espn_url("nhl")):
            return {"events": []}
        if url.startswith(ip.oddsapi_url("nba")):
            return [book]
        return {"markets": [{"ticker": tick, "event_ticker": "KXNBAGAME-26OCT22CHIMIL", "status": "active",
                             "yes_sub_title": "Milwaukee", "yes_ask_dollars": "0.5500", "yes_bid_dollars": "0.5400",
                             "no_ask_dollars": "0.4600", "result": ""}]}

    clock = {"t": T0}
    hooked: list = []
    loop = ip.PaperEntryLoop(today_fn=lambda: "2026-10-22", clock=lambda: clock["t"], get=get,
                             tickers_fn=lambda d, s: [tick] if s == "nba" else [],
                             load=lambda: {"entries": {}}, persist=lambda d: None, sports=("nhl", "nba"),
                             on_book=lambda e: hooked.append(e) or {"placed": False, "reason": "test"})
    loop.step()
    clock["t"] = T0 + 20
    loop.books_t, loop.espn_t, loop.last_pass_t = {}, {}, None
    out = loop.step()
    assert out["booked"] == 1, out
    (e,) = loop.doc["entries"].values()
    assert e["sport"] == "nba" and e["kind"] == "h2h" and e["leg"] == "yes"  # fair 0.62 vs ask 0.55
    assert (e["event_id"], e["home_team"], e["away_team"]) == ("nba1", "Milwaukee Bucks", "Chicago Bulls")
    assert (e["order_side"], e["order_line"]) == ("home", None)  # YES on Milwaukee = the home moneyline
    assert hooked and hooked[0]["sport"] == "nba" and hooked[0]["kind"] == "h2h"
    assert any(u.startswith(ip.oddsapi_url("nba")) and "h2h" in u for u in seen_urls)


def test_event_match_refuses_an_ambiguous_single_name():
    loop = ip.PaperEntryLoop(today_fn=lambda: "d", get=lambda u: {}, tickers_fn=lambda d, s="nhl": [],
                             load=lambda: {"entries": {}}, persist=lambda d: None)
    loop.books["nhl"] = {"a": {"id": "a", "home_team": "New York Rangers", "away_team": "Boston Bruins"},
                         "b": {"id": "b", "home_team": "New York Islanders", "away_team": "Detroit Red Wings"}}
    assert loop._event_for("nhl", {"New York"}) is None  # two games: refuse
    assert loop._event_for("nhl", {"New York", "Boston"})["id"] == "a"
    assert loop._event_for("nhl", {"Detroit"})["id"] == "b"
    assert loop._event_for("nhl", set()) is None


def test_default_oddsapi_calls_are_metered_by_quota_telemetry(monkeypatch):
    """The paper loop's OddsAPI spend must reach oddsapi_quota (coordinator ask 2026-10-23)."""
    from syndicate.features.shared import oddsapi_quota

    recorded: list = []
    monkeypatch.setattr(oddsapi_quota, "record_oddsapi_quota",
                        lambda headers, sport=None, endpoint=None: recorded.append((headers, sport, endpoint)))

    class _Resp:
        headers = {"x-requests-used": "3079320", "x-requests-remaining": "1920680", "x-requests-last": "9"}

        def read(self):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ip.urllib.request, "urlopen", lambda req, timeout=10.0: _Resp())
    loop = ip.PaperEntryLoop(today_fn=lambda: "d", tickers_fn=lambda d, s="nhl": [],
                             load=lambda: {"entries": {}}, persist=lambda d: None)  # real default get
    assert loop.get_odds is ip._get_odds
    loop._refresh_books("nba", T0)
    (h, sport, endpoint), = recorded
    assert sport == "nba" and h["x-requests-last"] == "9" and endpoint.startswith(ip.oddsapi_url("nba"))


def test_metering_failure_never_breaks_the_fetch(monkeypatch):
    from syndicate.features.shared import oddsapi_quota

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(oddsapi_quota, "record_oddsapi_quota", boom)

    class _Resp:
        headers = {}

        def read(self):
            return b'[{"id": "e1"}]'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ip.urllib.request, "urlopen", lambda req, timeout=10.0: _Resp())
    assert ip._get_odds("https://api.the-odds-api.com/v4/sports/x/odds?apiKey=k", "nhl") == [{"id": "e1"}]


def test_pass_spacing_batch_gap_and_429_cooldown():
    """The Kalshi public limit is shared with the live path (429s from external-api.kalshi.com, 2026-10-24)."""
    import urllib.error

    clock = {"t": T0}
    gaps: list = []
    calls = {"n": 0, "fail": False}

    def get(url):
        if url.startswith(ip.ESPN):
            return {"events": [{"competitions": [{"status": {"type": {"state": "in"}}, "competitors": [
                {"team": {"abbreviation": "TOR"}, "score": "1"}, {"team": {"abbreviation": "CBJ"}, "score": "0"}]}]}]}
        if url.startswith(ip.ODDSAPI):
            return []
        calls["n"] += 1
        if calls["fail"]:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"markets": []}

    tickers = [f"KXNHLSPREAD-26OCT21TORCBJ-T{i}" for i in range(120)]  # 3 batches of 50
    loop = ip.PaperEntryLoop(today_fn=lambda: "d", clock=lambda: clock["t"], get=get,
                             tickers_fn=lambda d, s="nhl": tickers, load=lambda: {"entries": {}}, persist=lambda d: None)
    loop.sleep = gaps.append
    assert loop.step()["status"] == "ok" and calls["n"] == 3 and gaps == [ip.BATCH_GAP_S] * 2
    clock["t"] += 15
    assert loop.step() == {"status": "waiting"} and calls["n"] == 3  # one pass per PASS_EVERY_S
    clock["t"] += 20
    calls["fail"] = True
    import pytest as _pt
    with _pt.raises(urllib.error.HTTPError):
        loop.step()
    clock["t"] += 31
    assert loop.step()["status"] == "cooldown"  # backs off instead of hammering the shared limit
    clock["t"] += 31
    calls["fail"] = False
    assert loop.step()["status"] == "ok"
