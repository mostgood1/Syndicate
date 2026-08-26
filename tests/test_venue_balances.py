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


def test_kalshi_cents_become_dollars_and_the_assumption_is_stamped(monkeypatch):
    """The unit is an ASSUMPTION. Both it and the raw value are recorded, so a
    live run can correct the constant without reverse-engineering a rendered
    number -- the discipline that caught the 100x price error."""
    _kalshi(monkeypatch, payload={"balance": 4231})
    row = vb.fetch_kalshi_balance()
    assert row["status"] == "ok"
    assert row["dollars"] == 42.31
    assert row["raw_value"] == 4231
    assert row["unit_assumption"] == "cents"
    assert row["path"] == "/portfolio/balance"


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


def test_polymarket_discovers_the_path_that_answers(monkeypatch):
    from syndicate.features.shared.polymarket_us_auth import PolymarketUSAuthError

    seen: list[str] = []

    def responder(url):
        seen.append(url)
        if url.endswith("/account/balance"):
            return {"available_balance": 40.5}
        raise PolymarketUSAuthError(f"http_404: {url}")

    _polymarket(monkeypatch, responder)
    row = vb.fetch_polymarket_balance()
    assert row["status"] == "ok"
    assert row["path"] == "/account/balance"
    assert row["dollars"] == 40.5
    # It tried the first candidate and stopped at the one that worked.
    assert len(seen) == 2


def test_polymarket_does_not_divide_by_a_unit_it_has_never_read(monkeypatch):
    """Kalshi documents cents; this venue documents nothing we have read.
    Dividing here would be inventing a fact, so the raw value is carried and
    the assumption is labelled unverified."""
    _polymarket(monkeypatch, lambda url: {"balance": 40.5})
    row = vb.fetch_polymarket_balance()
    assert row["dollars"] == 40.5
    assert row["raw_value"] == 40.5
    assert row["unit_assumption"] == "dollars_unverified"


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
        return {"balance": 12.0}

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
    _polymarket(monkeypatch, lambda url: seen.append(url) or {"balance": 1.0})
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
        lambda date, show_all=False: {
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
        lambda date, show_all=False: {
            "date": date, "orders": [], "health": {}, "limits": {}, "kill_switch": {}, "balances": None,
        },
    )
    body = client.get("/portfolio").get_data(as_text=True)
    assert "worker has not reported" in body
