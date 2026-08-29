"""Venue balances: the number, and every way there might not be one.

THE ONLY DANGEROUS BUG HERE IS A ZERO. "The account is empty" and "we could
not read the account" are opposite facts -- one says stop trading, the other
says something is broken -- and the naive implementation renders both as
`$0.00`. Most of this file is about keeping them apart.

The second theme is that Kalshi's path is VERIFIED and Polymarket's is not, and
the code must not pretend otherwise. A guessed endpoint that 404s forever, or a
unit assumption applied silently, is how the 100x price error nearly shipped.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import venue_balances as vb


@pytest.fixture(autouse=True)
def _no_store(monkeypatch):
    """Never touch the real store or the real venues from a test."""
    monkeypatch.setattr(vb, "read_json_file", lambda path: None)
    monkeypatch.setattr(vb, "write_json_file", lambda path, payload: None)


# ---------------------------------------------------------------------------
# Extraction: find the number, or say you could not
# ---------------------------------------------------------------------------


def test_a_balance_is_found_by_field_name():
    assert vb._extract_balance({"balance": 4231}) == (4231.0, "balance")
    assert vb._extract_balance({"availableBalance": 12.5}) == (12.5, "availableBalance")


def test_a_nested_balance_is_found_and_the_path_is_reported():
    """A `/portfolio` style endpoint wraps the number, and refusing those would
    report `shape_unrecognised` over a payload that plainly has the answer."""
    raw, field = vb._extract_balance({"account": {"cash_balance": 900}})
    assert raw == 900.0
    assert field == "account.cash_balance"


def test_a_boolean_is_not_a_balance():
    """`isinstance(True, int)` is True in Python, so a flag named `available`
    would otherwise be read as a $1.00 account."""
    assert vb._extract_balance({"available": True}) == (None, None)


def test_an_unrecognised_shape_yields_no_number_at_all():
    assert vb._extract_balance({"status": "ok", "ticker": "KX"}) == (None, None)


# ---------------------------------------------------------------------------
# Kalshi -- the verified path
# ---------------------------------------------------------------------------


def _kalshi(monkeypatch, *, creds="ok", payload=None, raises=None):
    import syndicate.features.shared.kalshi_auth as auth

    monkeypatch.setattr(auth, "load_credentials", lambda: {"status": creds, "reason": "no_key"})
    monkeypatch.setattr(auth, "_base_url", lambda: "https://api.example/trade-api/v2")

    def fake(method, url, **kwargs):
        if raises is not None:
            raise raises
        return payload

    monkeypatch.setattr(auth, "signed_request", fake)


def test_kalshi_cents_become_dollars(monkeypatch):
    """`balance` is documented as int64 CENTS (docs.kalshi.com, read
    2026-08-26). Production read 1384 -> $13.84 at 20:46Z, which is the same
    arithmetic this pins."""
    _kalshi(monkeypatch, payload={"balance": 4231})
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "ok"
    assert row["dollars"] == 42.31
    assert row["raw_field"] == "balance(cents)"
    assert row["unit_assumption"] == "documented"
    assert row["path"] == "/portfolio/balance"


def test_kalshi_prefers_the_documented_dollar_string(monkeypatch):
    """`balance_dollars` is documented as fixed-point dollars, so reading it
    REMOVES this module's last unit assumption rather than restating it."""
    _kalshi(monkeypatch, payload={"balance": 56, "balance_dollars": "0.5600"})
    row = vb.fetch_kalshi_balance()
    assert row["dollars"] == 0.56
    assert row["raw_field"] == "balance_dollars"
    assert row["unit_disagreement"] is None


def test_kalshi_reports_when_the_venue_disagrees_with_itself(monkeypatch):
    """Two representations of one number that stop matching means the venue
    changed something under us. A silently-picked winner would hide it."""
    _kalshi(monkeypatch, payload={"balance": 4231, "balance_dollars": "99.00"})
    row = vb.fetch_kalshi_balance()
    assert row["unit_disagreement"] == {"balance_dollars": 99.0, "balance_cents": 4231.0}


def test_kalshi_portfolio_value_is_kept_apart_from_spendable_cash(monkeypatch):
    """Cash and cash-plus-positions are different questions. Conflating them
    overstates what can be deployed by exactly what is already at risk."""
    _kalshi(monkeypatch, payload={"balance": 1384, "portfolio_value": 9900})
    row = vb.fetch_kalshi_balance()
    assert row["dollars"] == 13.84
    assert row["portfolio_value_dollars"] == 99.0


def test_kalshi_without_a_credential_says_so_and_shows_no_number(monkeypatch):
    _kalshi(monkeypatch, creds="missing")
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "credentials_absent"
    assert "dollars" not in row


def test_kalshi_auth_failure_is_never_a_zero_balance(monkeypatch):
    """The bug this whole module is shaped around."""
    from syndicate.features.shared.kalshi_auth import KalshiAuthError

    _kalshi(monkeypatch, raises=KalshiAuthError("http_401: check clock skew"))
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "auth_error"
    assert "dollars" not in row
    assert "http_401" in row["detail"]


def test_kalshi_answering_with_an_unknown_shape_reports_the_keys(monkeypatch):
    _kalshi(monkeypatch, payload={"portfolio_value": 100, "ticker": "X"})
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "shape_unrecognised"
    assert "dollars" not in row
    assert row["payload_keys"] == ["portfolio_value", "ticker"]


# ---------------------------------------------------------------------------
# Polymarket -- the UNVERIFIED path, discovered rather than guessed
# ---------------------------------------------------------------------------


def _polymarket(monkeypatch, responder, *, present=True):
    import syndicate.features.shared.polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: present)
    monkeypatch.setattr(auth, "signed_request", lambda method, url, **kw: responder(url))


def _pm_payload(**over):
    row = {"currentBalance": 40.5, "currency": "USD", "buyingPower": 31.25,
           "openOrders": 9.25, "unsettledFunds": 0}
    row.update(over)
    return {"balances": [row]}


def test_polymarket_reads_the_documented_path_first(monkeypatch):
    """`/account/balances` is PLURAL, and that one character is why the first
    production discovery round returned `path_unknown`. Measured
    2026-08-26T20:46Z: all four guesses -- including the singular
    `/account/balance` -- 404'd with a gRPC `code: 5` envelope."""
    seen: list[str] = []
    _polymarket(monkeypatch, lambda url: seen.append(url) or _pm_payload())
    row = vb.fetch_polymarket_balance()
    assert row["status"] == "ok"
    assert row["path"] == "/account/balances"
    assert seen == ["https://api.polymarket.us/v1/account/balances"]


def test_polymarket_uses_buying_power_not_the_cash_balance(monkeypatch):
    """The docs define buyingPower as unencumbered capital available for
    trading, factoring in security valuations and open orders -- what can
    actually be deployed. A day cap checked against `currentBalance` would look
    reachable while every dollar sat in resting orders."""
    _polymarket(monkeypatch, lambda url: _pm_payload())
    row = vb.fetch_polymarket_balance()
    assert row["dollars"] == 31.25
    assert row["buying_power_dollars"] == 31.25
    assert row["cash_dollars"] == 40.5
    assert row["open_orders_dollars"] == 9.25


def test_polymarket_never_reports_a_pending_withdrawal_as_the_balance(monkeypatch):
    """Each row carries `pendingWithdrawals[].balance`. A generic scan for a
    balance-shaped field would report money LEAVING the account as the money in
    it. The documented shape is parsed by name for exactly this reason."""
    payload = {"balances": [{"currency": "USD",
                             "pendingWithdrawals": [{"id": "w1", "balance": 500.0}]}]}
    _polymarket(monkeypatch, lambda url: payload)
    row = vb.fetch_polymarket_balance()
    assert row["status"] == "path_unknown"
    assert "dollars" not in row


def test_polymarket_picks_the_usd_row_out_of_several(monkeypatch):
    payload = {"balances": [
        {"currency": "POINTS", "buyingPower": 9999.0},
        {"currency": "USD", "buyingPower": 12.0},
    ]}
    _polymarket(monkeypatch, lambda url: payload)
    assert vb.fetch_polymarket_balance()["dollars"] == 12.0


def test_polymarket_refuses_to_guess_when_no_row_says_usd(monkeypatch):
    """Which pile of money is spendable is not something to guess at."""
    payload = {"balances": [
        {"currency": "POINTS", "buyingPower": 9999.0},
        {"currency": "CREDITS", "buyingPower": 1.0},
    ]}
    _polymarket(monkeypatch, lambda url: payload)
    assert vb.fetch_polymarket_balance()["status"] == "path_unknown"


def test_polymarket_figures_are_dollars_and_are_not_divided(monkeypatch):
    """Every field is `number<decimal>` per the reference -- DOLLARS, not
    cents. This was an open assumption labelled `dollars_unverified` until the
    docs settled it."""
    _polymarket(monkeypatch, lambda url: _pm_payload(buyingPower=40.5))
    row = vb.fetch_polymarket_balance()
    assert row["dollars"] == 40.5
    assert row["unit_assumption"] == "documented"


def test_polymarket_reports_path_unknown_rather_than_a_zero(monkeypatch):
    from syndicate.features.shared.polymarket_us_auth import PolymarketUSAuthError

    def responder(url):
        raise PolymarketUSAuthError(f"http_404: {url}")

    _polymarket(monkeypatch, responder)
    row = vb.fetch_polymarket_balance()
    assert row["status"] == "path_unknown"
    assert "dollars" not in row
    assert len(row["attempts"]) == len(vb.POLYMARKET_BALANCE_PATH_CANDIDATES)


def test_a_401_stops_discovery_instead_of_trying_every_path(monkeypatch):
    """A bad credential cannot be fixed by another path, and hammering four
    endpoints with a refused key spends the venue's patience for nothing."""
    from syndicate.features.shared.polymarket_us_auth import PolymarketUSAuthError

    seen: list[str] = []

    def responder(url):
        seen.append(url)
        raise PolymarketUSAuthError(f"http_401: {url}")

    _polymarket(monkeypatch, responder)
    row = vb.fetch_polymarket_balance()
    assert row["status"] == "auth_error"
    assert len(seen) == 1


def test_a_pinned_path_skips_discovery_entirely(monkeypatch):
    seen: list[str] = []

    def responder(url):
        seen.append(url)
        return _pm_payload(buyingPower=12.0)

    monkeypatch.setenv("POLYMARKET_US_BALANCE_PATH", "/v2/cash")
    _polymarket(monkeypatch, responder)
    row = vb.fetch_polymarket_balance()
    assert row["path"] == "/v2/cash"
    assert seen == ["https://api.polymarket.us/v1/v2/cash"]


def test_a_previously_discovered_path_is_reused(monkeypatch):
    """Discovery runs once, not on every tick."""
    monkeypatch.setattr(
        vb,
        "read_json_file",
        lambda path: {
            "recorded_at": "2026-08-26T20:00:00Z",
            "venues": {"polymarket": {"status": "ok", "path": "/account/balance"}},
        },
    )
    seen: list[str] = []
    _polymarket(monkeypatch, lambda url: seen.append(url) or _pm_payload())
    vb.fetch_polymarket_balance()
    assert seen == ["https://api.polymarket.us/v1/account/balance"]


# ---------------------------------------------------------------------------
# The stamp -- and that it can never take down the tick that places orders
# ---------------------------------------------------------------------------


def test_recording_never_raises_even_if_a_venue_blows_up(monkeypatch):
    """A balance is a nicety. `record_venue_balances` runs inside the execution
    tick, so an exception here would stop orders being placed."""
    monkeypatch.setattr(vb, "fetch_kalshi_balance", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(vb, "fetch_polymarket_balance", lambda: {"venue": "polymarket", "status": "ok", "dollars": 5.0})
    stamp = vb.record_venue_balances(recorded_by="test")
    assert stamp["status"] == "ok"
    assert stamp["venues"]["kalshi"]["status"] == "auth_error"
    assert stamp["venues"]["polymarket"]["dollars"] == 5.0


def test_a_stamp_without_a_timestamp_reads_as_never_reported(monkeypatch):
    """`None` means "the worker has not reported", which the page must render
    as unknown rather than as no money -- the same distinction
    `read_execution_state` draws for the switches."""
    monkeypatch.setattr(vb, "read_json_file", lambda path: {"venues": {}})
    assert vb.read_venue_balances() is None
    monkeypatch.setattr(vb, "read_json_file", lambda path: (_ for _ in ()).throw(RuntimeError("store down")))
    assert vb.read_venue_balances() is None


def test_the_balances_path_carries_no_date_token():
    """A dated path takes the keyvalue store's 10-day TTL, and a balance that
    silently expires leaves the page blank over a funded account."""
    assert "venue_balances.json" == vb.balances_path().name
    assert "2026" not in str(vb.balances_path())


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from syndicate.app import app

    return app.test_client()


def test_the_page_never_prints_a_total_over_a_partial_read(client, monkeypatch):
    """If either venue is unreadable the sum is not the account, and printing
    it as one is a lie with a dollar sign on it."""
    from syndicate.blueprints import intelligence as bp

    monkeypatch.setattr(
        bp,
        "_live_portfolio_payload",
        # `**kwargs` rather than naming each one: this stub exists to return a
        # payload, and re-listing the route's signature here just means it goes
        # red again the next time a filter is added (it did -- `?venue=`,
        # 2026-08-28, and these two tests were red on `origin/main`).
        lambda date, **kwargs: {
            "date": date,
            "orders": [],
            "health": {},
            "limits": {},
            "kill_switch": {},
            "balances": {
                "recorded_at": "2026-08-26T20:00:00Z",
                "age_seconds": 120,
                "venues": {
                    "kalshi": {"status": "ok", "dollars": 41.0},
                    "polymarket": {"status": "path_unknown"},
                },
            },
        },
    )
    body = client.get("/portfolio").get_data(as_text=True)
    assert "$41.00" in body
    assert "path unknown" in body
    # No summed figure anywhere, and no invented zero for the unread venue.
    assert "$0.00" not in body.split('class="live-tile__label">Venue balances')[-1][:900]


def test_no_stamp_reads_as_not_reported_rather_than_no_money(client, monkeypatch):
    from syndicate.blueprints import intelligence as bp

    monkeypatch.setattr(
        bp,
        "_live_portfolio_payload",
        # `**kwargs` rather than naming each one: this stub exists to return a
        # payload, and re-listing the route's signature here just means it goes
        # red again the next time a filter is added (it did -- `?venue=`,
        # 2026-08-28, and these two tests were red on `origin/main`).
        lambda date, **kwargs: {
            "date": date, "orders": [], "health": {}, "limits": {}, "kill_switch": {}, "balances": None,
        },
    )
    body = client.get("/portfolio").get_data(as_text=True)
    assert "worker has not reported" in body


# ---------------------------------------------------------------------------
# THE TRAIL. A single overwritten stamp answers "what is in the account now"
# and cannot answer "did anything leave it when that submit failed" -- the only
# question that settles an order the venue never answered.
#
# 2026-08-29: $1.84 was settled by five readings that existed only because the
# worker prints them and Render retains logs.
# ---------------------------------------------------------------------------


def _stamp(at, dollars, status="ok"):
    return {
        "recorded_by": "live-odds-worker",
        "recorded_at": at,
        "venues": {"polymarket": {"status": status, "dollars": dollars, "cash_dollars": 118.15}},
    }


class _Store:
    """A stand-in for the keyvalue store that actually remembers."""

    def __init__(self):
        self.data = {}

    def read(self, path):
        return self.data.get(str(path))

    def write(self, path, payload):
        self.data[str(path)] = payload


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(vb, "read_json_file", s.read)
    monkeypatch.setattr(vb, "write_json_file", s.write)
    return s


def test_readings_accumulate_oldest_first(store):
    vb.append_balance_history(_stamp("2026-08-29T21:05:56Z", 96.04765))
    vb.append_balance_history(_stamp("2026-08-29T21:12:47Z", 96.04765))
    vb.append_balance_history(_stamp("2026-08-29T21:32:08Z", 94.14995))

    trail = vb.read_balance_history()
    assert [r["recorded_at"] for r in trail] == [
        "2026-08-29T21:05:56Z", "2026-08-29T21:12:47Z", "2026-08-29T21:32:08Z",
    ]
    assert trail[0]["polymarket"]["dollars"] == 96.04765
    assert trail[-1]["polymarket"]["dollars"] == 94.14995


def test_the_trail_is_bounded(store):
    for i in range(vb._BALANCE_HISTORY_LIMIT + 25):
        vb.append_balance_history(_stamp(f"2026-08-29T{i:04d}Z", 1.0))
    assert len(vb.read_balance_history()) == vb._BALANCE_HISTORY_LIMIT


def test_a_failed_reading_is_kept_with_its_status(store):
    """Dropping it would leave a gap that reads as "no reading taken", and a
    gap and a refusal are different facts about the same minute."""
    vb.append_balance_history(_stamp("2026-08-29T21:05:56Z", None, status="auth_error"))
    assert vb.read_balance_history()[0]["polymarket"]["status"] == "auth_error"


def test_no_trail_reads_as_empty_not_as_an_error(store):
    assert vb.read_balance_history() == []


def test_a_history_write_failure_never_raises(monkeypatch, capsys):
    """A nicety, like the stamp itself. It must not take down the tick that
    places orders."""
    monkeypatch.setattr(vb, "read_json_file", lambda path: None)

    def _boom(path, payload):
        raise OSError("disk gone")

    monkeypatch.setattr(vb, "write_json_file", _boom)
    vb.append_balance_history(_stamp("2026-08-29T21:05:56Z", 96.0))
    assert "HISTORY_WRITE_FAILED" in capsys.readouterr().out


def test_recording_balances_also_appends_to_the_trail(store, monkeypatch):
    """The wiring. Without this the history is a function nothing calls."""
    monkeypatch.setattr(vb, "fetch_kalshi_balance", lambda: {"venue": "kalshi", "status": "ok", "dollars": 50.19})
    monkeypatch.setattr(
        vb, "fetch_polymarket_balance", lambda: {"venue": "polymarket", "status": "ok", "dollars": 96.05}
    )
    vb.record_venue_balances(recorded_by="live-odds-worker")
    trail = vb.read_balance_history()
    assert len(trail) == 1
    assert trail[0]["polymarket"]["dollars"] == 96.05
    assert trail[0]["kalshi"]["dollars"] == 50.19
