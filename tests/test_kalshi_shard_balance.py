"""`#573`: refuse a Kalshi order by READING its shard's balance.

MEASURED 2026-09-11 on production. Kalshi's `balance_dollars` ($101.61) is the
SUM across exchange shards -- the docs say so: "includes all exchange indexes
when `exchange_index` is omitted" -- while the venue checks an order only
against its OWN shard's cash. Since 15:45Z every Kalshi `insufficient_balance`
400 landed on a shard short of cash:

    KXMLBSPREAD-26SEP111907BALTOR-BAL2  $20.85   shard 3
    KXMLBTOTAL-26SEP111910LADMIA-8      $18.91   shard 3
    KXNFLTOTAL-26SEP13NYJTEN-39         $4.07    shard 0, 8 s after three
                                                 shard-0 orders reserved $11.90

`balance_breakdown` carries each shard's cash on the same response, and it was
thrown away. This records it and refuses by name.

THE PERMISSIVE HALF IS THE HOUSE RULE, and most of the gate tests are about it:
exactly like the account-level gate (`test_execution_guard_balance.py`), every
unknown -- no breakdown, a stale reading, a shard we cannot resolve -- ALLOWS,
because failing closed on a broken read would stop all live trading and look
like a quiet slate. The venue's own 400 stays the backstop.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import execution_guard as G
from syndicate.features.shared import venue_balances as vb
from syndicate.features.shared.execution_ledger import OrderRequest

MLB = "KXMLBSPREAD-26SEP111907BALTOR-BAL2"
NFL = "KXNFLTOTAL-26SEP13NYJTEN-39"
NFL_OTHER = "KXNCAAFSPREAD-26SEP11RUTGBC-BC4"
SHARD_OF = {MLB: 3, NFL: 0, NFL_OTHER: 0}


# ---------------------------------------------------------------------------
# Recording: `balance_breakdown` -> per-shard dollars
# ---------------------------------------------------------------------------


@pytest.fixture
def no_store(monkeypatch):
    monkeypatch.setattr(vb, "read_json_file", lambda path: None)
    monkeypatch.setattr(vb, "write_json_file", lambda path, payload: None)


def _kalshi(monkeypatch, payload):
    import syndicate.features.shared.kalshi_auth as auth

    monkeypatch.setattr(auth, "load_credentials", lambda: {"status": "ok"})
    monkeypatch.setattr(auth, "_base_url", lambda: "https://api.example/trade-api/v2")
    monkeypatch.setattr(auth, "signed_request", lambda method, url, **kw: payload)


def _payload(breakdown, *, balance_dollars="101.6100"):
    body = {"balance": 10161, "balance_dollars": balance_dollars, "portfolio_value": 5129}
    if breakdown is not None:
        body["balance_breakdown"] = breakdown
    return body


def test_the_breakdown_becomes_per_shard_dollars(no_store, monkeypatch):
    """`IndexedBalance.balance` is FixedPointDollars (docs.kalshi.com, read
    2026-09-11) -- a dollar STRING, not cents, so it is not divided."""
    _kalshi(monkeypatch, _payload([
        {"exchange_index": 0, "balance": "96.6100"},
        {"exchange_index": 3, "balance": "5.0000"},
    ]))
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "ok"
    assert row["dollars"] == 101.61
    assert row["shards"] == {"0": 96.61, "3": 5.0}
    assert row["shards_status"] == "ok"
    assert row["shards_sum_dollars"] == 101.61


def test_no_breakdown_is_ABSENT_never_a_zero_shard(no_store, monkeypatch):
    """A subaccount-restricted key omits the breakdown (docs). That is "we do
    not know", which must never read as "shard 3 is empty"."""
    _kalshi(monkeypatch, _payload(None))
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "ok"
    assert row["shards"] is None
    assert row["shards_status"] == "absent"


@pytest.mark.parametrize("bad_row", [
    {"exchange_index": "x", "balance": "1.00"},
    {"exchange_index": 0},
    {"exchange_index": True, "balance": "1.00"},
    "not-a-row",
])
def test_an_unreadable_breakdown_row_poisons_the_whole_breakdown(no_store, monkeypatch, bad_row):
    """Half a breakdown is worse than none: the missing shard would read as
    unfunded. So one bad row makes the whole thing `unreadable`."""
    _kalshi(monkeypatch, _payload([{"exchange_index": 3, "balance": "5.00"}, bad_row]))
    row = vb.fetch_kalshi_balance()
    assert row["shards"] is None
    assert row["shards_status"] == "unreadable"
    assert row["dollars"] == 101.61, "the account-level number is unaffected"


def test_a_breakdown_that_does_not_sum_to_the_balance_is_not_trusted(no_store, monkeypatch):
    """The unit check, and the one this change could otherwise fail on. If the
    shards were ever cents, or omitted a shard, the sum would miss the total by
    far more than a rounding cent -- and the gate must then stand down."""
    _kalshi(monkeypatch, _payload([
        {"exchange_index": 0, "balance": "40.00"},
        {"exchange_index": 3, "balance": "5.00"},
    ]))
    row = vb.fetch_kalshi_balance()
    assert row["shards_status"] == "sum_disagrees"
    assert row["shards_sum_dollars"] == 45.0
    assert row["shards"] == {"0": 40.0, "3": 5.0}, "kept for display, not for the gate"


def test_the_history_row_carries_the_shards():
    entry = vb._history_entry({
        "recorded_at": "2026-09-11T17:00:39Z",
        "venues": {"kalshi": {"status": "ok", "dollars": 101.61, "shards": {"0": 96.61, "3": 5.0}}},
    })
    assert entry["kalshi"]["shards"] == {"0": 96.61, "3": 5.0}


def test_recording_prints_the_shard_line(no_store, monkeypatch, capsys):
    monkeypatch.setattr(vb, "fetch_kalshi_balance", lambda: {
        "venue": "kalshi", "status": "ok", "dollars": 101.61,
        "shards": {"0": 96.61, "3": 5.0}, "shards_status": "ok", "shards_sum_dollars": 101.61,
    })
    monkeypatch.setattr(vb, "fetch_polymarket_balance", lambda: {"venue": "polymarket", "status": "ok", "dollars": 5.0})
    vb.record_venue_balances(recorded_by="test")
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if "KALSHI_SHARD_BALANCES" in l)
    assert "status=ok" in line
    assert "'3': 5.0" in line
    assert "balance=101.61" in line


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def _stamp(age: float = 30.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat().replace("+00:00", "Z")


def _balances(shards, *, dollars=101.61, status="ok", shards_status="ok", age=30.0):
    return {
        "recorded_at": _stamp(age),
        "recorded_by": "test",
        "venues": {"kalshi": {
            "venue": "kalshi", "status": status, "dollars": dollars,
            "shards": shards, "shards_status": shards_status,
        }},
    }


def _order(ticker=MLB, *, stake=3.39, venue="kalshi"):
    return OrderRequest(
        position_key="p1",
        selected_date="2026-09-11",
        venue=venue,
        sport="mlb",
        event_id="e1",
        market="spreads",
        side="away",
        requested_price=194.0,
        requested_stake_dollars=stake,
        venue_ticker=ticker,
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("SYNDICATE_EXECUTION_KILL_SWITCH", "SYNDICATE_EXECUTION_MODE", "SYNDICATE_KALSHI_SHARD_BALANCE_GATE"):
        monkeypatch.delenv(name, raising=False)
    G._SHARD_CACHE.clear()
    yield
    G._SHARD_CACHE.clear()


@pytest.fixture
def world(monkeypatch):
    """A balance stamp, the orders placed since it, and each ticker's shard."""

    def install(payload, *, orders=(), shard_of=None):
        table = dict(SHARD_OF if shard_of is None else shard_of)
        monkeypatch.setattr(
            "syndicate.features.shared.venue_balances.read_venue_balances",
            lambda: payload, raising=False,
        )
        monkeypatch.setattr(G, "_live_stake_since", lambda *a, **k: sum(amount for _, amount in orders))
        monkeypatch.setattr(G, "_live_orders_since", lambda *a, **k: list(orders))
        monkeypatch.setattr(
            G, "_kalshi_shard_of",
            lambda ticker: (table[ticker], None) if ticker in table else (None, "unresolved"),
        )

    return install


def _check(order):
    return G.check_order(order, mode="live", already={"dollars": 0, "orders": 0})


def test_reachability_the_gate_OFF_is_not_the_gate_ON(world, monkeypatch):
    """off != on, on the production shape: plenty of cash in TOTAL, too little
    on the shard the MLB order routes to."""
    world(_balances({"0": 96.61, "3": 2.00}))
    on = _check(_order(MLB, stake=3.39))
    assert on["allowed"] is False
    assert on["reason"] == "insufficient_shard_balance"
    assert on["shard_balance"]["shard"] == 3
    assert on["shard_balance"]["available"] == pytest.approx(2.00)

    monkeypatch.setenv("SYNDICATE_KALSHI_SHARD_BALANCE_GATE", "off")
    off = _check(_order(MLB, stake=3.39))
    assert off["allowed"] is True, "the kill switch must restore today's behaviour exactly"


def test_an_order_its_own_shard_can_cover_is_allowed(world):
    world(_balances({"0": 96.61, "3": 2.00}))
    assert _check(_order(NFL, stake=3.39))["allowed"] is True


def test_orders_placed_since_the_reading_on_the_SAME_shard_are_subtracted(world):
    """The measured 15:50Z shape: three shard-0 orders reserved the cash, and
    the fourth on the same shard found too little left."""
    world(_balances({"0": 10.00, "3": 50.00}), orders=[(NFL_OTHER, 8.50)])
    result = _check(_order(NFL, stake=3.39))
    assert result["allowed"] is False
    assert result["reason"] == "insufficient_shard_balance"
    assert result["shard_balance"]["committed_since_reading"] == pytest.approx(8.50)
    assert result["shard_balance"]["available"] == pytest.approx(1.50)


def test_orders_on_another_shard_are_not_charged(world):
    world(_balances({"0": 10.00, "3": 50.00}), orders=[(MLB, 8.50)])
    assert _check(_order(NFL, stake=3.39))["allowed"] is True


def test_an_order_whose_shard_cannot_be_read_is_charged_to_EVERY_shard(world):
    """Over-counting costs one cycle of a smaller book; under-counting is the
    overspend this gate exists to stop."""
    world(_balances({"0": 10.00, "3": 50.00}), orders=[("KX-UNREADABLE-1", 9.00)])
    result = _check(_order(NFL, stake=3.39))
    assert result["allowed"] is False
    assert result["shard_balance"]["committed_since_reading"] == pytest.approx(9.00)


def test_the_account_level_refusal_still_comes_first(world):
    world(_balances({"0": 1.00, "3": 1.00}, dollars=2.00))
    assert _check(_order(MLB, stake=3.39))["reason"] == "insufficient_venue_balance"


@pytest.mark.parametrize("payload, reason_prefix", [
    (None, "never_recorded"),
    (_balances(None, shards_status="absent"), "shards_absent"),
    (_balances({"0": 40.0, "3": 5.0}, shards_status="sum_disagrees"), "shards_sum_disagrees"),
    (_balances(None, shards_status="unreadable"), "shards_unreadable"),
    (_balances({"0": 96.61, "3": 2.0}, status="auth_error"), "balance_auth_error"),
])
def test_every_unknown_reading_ALLOWS(world, payload, reason_prefix):
    world(payload)
    assert _check(_order(MLB, stake=3.39))["allowed"] is True
    assert G._shard_available_dollars(_order(MLB))["reason"].startswith(reason_prefix)


def test_a_stale_reading_ALLOWS(world):
    world(_balances({"0": 96.61, "3": 2.00}, age=G._BALANCE_MAX_AGE_SECONDS + 60))
    assert _check(_order(MLB, stake=3.39))["allowed"] is True
    assert G._shard_available_dollars(_order(MLB))["reason"] == "stale_reading"


def test_a_shard_we_cannot_resolve_ALLOWS_and_says_so(world, capsys):
    world(_balances({"0": 96.61, "3": 2.00}), shard_of={})
    assert _check(_order(MLB, stake=3.39))["allowed"] is True
    out = capsys.readouterr().out
    assert "SHARD_BALANCE_UNKNOWN" in out and "shard_unresolved" in out


def test_a_shard_missing_from_the_breakdown_ALLOWS(world):
    world(_balances({"0": 96.61}))
    assert _check(_order(MLB, stake=3.39))["allowed"] is True
    assert G._shard_available_dollars(_order(MLB))["reason"] == "shard_absent_from_breakdown"


def test_a_read_that_raises_ALLOWS_rather_than_crashing_the_tick(world, monkeypatch):
    world(_balances({"0": 96.61, "3": 2.00}))

    def boom():
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr("syndicate.features.shared.venue_balances.read_venue_balances", boom, raising=False)
    assert G._shard_available_dollars(_order(MLB))["reason"].startswith("read_error:")


def test_no_ticker_and_other_venues_and_paper_are_untouched(world):
    world(_balances({"0": 96.61, "3": 0.01}))
    assert _check(_order(None, stake=3.39))["allowed"] is True
    assert G._shard_available_dollars(_order(MLB, venue="polymarket"))["reason"] == "venue_has_no_shards"
    paper = G.check_order(_order(MLB, stake=3.39), mode="paper", already={"dollars": 0, "orders": 0})
    assert paper["allowed"] is True


# ---------------------------------------------------------------------------
# Resolving a ticker's shard -- the public market read, cached
# ---------------------------------------------------------------------------


def test_the_shard_comes_from_the_markets_own_exchange_index_and_is_cached(monkeypatch):
    calls = []

    def fake(ticker):
        calls.append(ticker)
        return {"status": "ok", "market": {"ticker": ticker, "exchange_index": 3}}

    monkeypatch.setattr("syndicate.features.shared.kalshi_client.fetch_market", fake)
    assert G._kalshi_shard_of(MLB) == (3, None)
    assert G._kalshi_shard_of(MLB) == (3, None)
    assert calls == [MLB], "a market's shard does not move; read it once"


@pytest.mark.parametrize("answer, reason", [
    ({"status": "error", "reason": "no_base_responded"}, "fetch_failed"),
    ({"status": "ok", "market": {"ticker": MLB}}, "no_exchange_index"),
    ({"status": "ok", "market": {"ticker": MLB, "exchange_index": True}}, "no_exchange_index"),
    ({"status": "ok", "market": {"ticker": MLB, "exchange_index": -1}}, "no_exchange_index"),
])
def test_an_unreadable_shard_is_None_with_a_reason_and_is_not_cached(monkeypatch, answer, reason):
    monkeypatch.setattr("syndicate.features.shared.kalshi_client.fetch_market", lambda ticker: answer)
    shard, why = G._kalshi_shard_of(MLB)
    assert shard is None
    assert why.startswith(reason)
    assert MLB not in G._SHARD_CACHE
