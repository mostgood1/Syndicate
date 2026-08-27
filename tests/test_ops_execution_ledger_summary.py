"""`/api/ops/execution/ledger-summary` -- counts per day per venue, never rows.

WHY IT EXISTS. "Why so little Polymarket activity today" is a day-over-day
question and was unanswerable: `execution_ledger` writes through
`write_json_file`, which routes everything outside `migration_runs/` to the
KEYVALUE store and returns before touching disk, while
`/api/ops/artifacts/export` is a DISK read. Allowlisting the ledger would have
turned `403 not allowed` into an empty result -- the guard passes and the data
still never arrives. This reads through the same keyvalue-aware `read_json_file`
the writer used.

MOST OF THIS FILE POLICES THE SHAPE, NOT THE ARITHMETIC. This is the record of
MONEY, and "aggregates only" is a property that decays silently: the natural way
to answer the next question is to add one more field. `test_no_order_level_field
_ever_appears` walks the whole response and fails on any ticker, price, client id
or idempotency key, so the decay is caught by a test rather than by review.
"""

from __future__ import annotations

import json

import pytest

from syndicate.app import app
from syndicate.blueprints.ops import _LEDGER_SUMMARY_FIELDS


ADMIN = {"X-Admin-Token": "test-token"}

FORBIDDEN_SUBSTRINGS = (
    "ticker", "idempotency", "client_order", "venue_order_id",
    "fill_price", "requested_price", "position_key", "event_id", "player",
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _order(**kw):
    base = {
        "selected_date": "2026-08-27", "mode": "live", "venue": "kalshi",
        "status": "filled", "fill_stake_dollars": 2.5,
        # Deliberately present, and deliberately never emitted:
        "venue_ticker": "KXMLB-SECRET", "idempotency_key": "abc123",
        "fill_price": 0.44, "position_key": "p1", "event_id": "e1",
    }
    base.update(kw)
    return base


def _install(monkeypatch, orders):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda *a, **k: {"orders": orders},
        raising=False,
    )


def test_it_requires_the_admin_token(client):
    assert client.get("/api/ops/execution/ledger-summary").status_code in (401, 403)


def test_an_absent_ledger_is_named_not_reported_as_no_activity(client, monkeypatch):
    """"Unreadable" and "nothing was placed" must never share an answer.

    `execution_ledger._load` refuses rather than degrades for the same reason:
    an empty-looking ledger invites a duplicate of the entire slate.
    """
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda *a, **k: None, raising=False,
    )
    body = json.loads(client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data)
    assert body["ok"] is True
    assert body["summary"] == {}
    assert body["reason"] == "no_execution_ledger_recorded"


def test_it_counts_per_day_per_venue_and_mode(client, monkeypatch):
    _install(monkeypatch, [
        _order(venue="kalshi"), _order(venue="kalshi", status="rejected"),
        _order(venue="polymarket", fill_stake_dollars=3.0),
        _order(venue="kalshi", mode="paper"),
        _order(selected_date="2026-08-26", venue="kalshi"),
    ])
    body = json.loads(client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data)
    day = body["summary"]["2026-08-27"]
    assert day["live:kalshi"]["orders"] == 2
    assert day["live:kalshi"]["filled"] == 1
    assert day["live:kalshi"]["staked_dollars"] == 2.5
    assert day["live:kalshi"]["by_status"] == {"filled": 1, "rejected": 1}
    assert day["live:polymarket"]["staked_dollars"] == 3.0
    # PAPER IS SPLIT OUT, NOT SUMMED: adding a paper order to a live one is how
    # a paper P&L gets quoted as real.
    assert "paper:kalshi" in day
    assert body["summary"]["2026-08-26"]["live:kalshi"]["orders"] == 1


def test_no_order_level_field_ever_appears(client, monkeypatch):
    """The safety property, checked over the WHOLE response.

    The fixture orders carry a ticker, an idempotency key, a fill price and a
    position key. None may survive into the response at any depth.
    """
    _install(monkeypatch, [_order(), _order(venue="polymarket")])
    raw = client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data.decode("utf-8")
    lowered = raw.lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in lowered, f"order-level field leaked: {needle}"
    assert "kxmlb-secret" not in lowered
    assert "abc123" not in lowered


def test_the_bucket_carries_only_the_declared_fields(client, monkeypatch):
    """A new field must be a deliberate edit to `_LEDGER_SUMMARY_FIELDS`."""
    _install(monkeypatch, [_order()])
    body = json.loads(client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data)
    bucket = body["summary"]["2026-08-27"]["live:kalshi"]
    assert set(bucket) == set(_LEDGER_SUMMARY_FIELDS)


def test_the_mode_filter_narrows(client, monkeypatch):
    _install(monkeypatch, [_order(mode="live"), _order(mode="paper")])
    body = json.loads(
        client.get("/api/ops/execution/ledger-summary?mode=paper", headers=ADMIN).data)
    day = body["summary"]["2026-08-27"]
    assert list(day) == ["paper:kalshi"]


def test_an_unreadable_stake_counts_the_ORDER_but_not_the_dollars(client, monkeypatch):
    """Coercing a bad stake to 0.0 is the same number with a worse meaning."""
    _install(monkeypatch, [_order(fill_stake_dollars="not-a-number")])
    body = json.loads(client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data)
    bucket = body["summary"]["2026-08-27"]["live:kalshi"]
    assert bucket["orders"] == 1 and bucket["filled"] == 1
    assert bucket["staked_dollars"] == 0.0


def test_orders_without_a_date_are_counted_not_silently_dropped(client, monkeypatch):
    """Invisible to every per-day cut, so it has to be reported somewhere."""
    _install(monkeypatch, [_order(selected_date=None), _order()])
    body = json.loads(client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data)
    assert body["orders_without_date"] == 1


def test_a_read_error_reports_rather_than_500s(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", boom, raising=False)
    body = json.loads(client.get("/api/ops/execution/ledger-summary", headers=ADMIN).data)
    assert body["ok"] is False and "RuntimeError" in body["error"]


def test_the_days_window_is_bounded(client, monkeypatch):
    _install(monkeypatch, [_order()])
    for raw, expected in (("0", 1), ("999", 60), ("junk", 7)):
        body = json.loads(
            client.get(f"/api/ops/execution/ledger-summary?days={raw}", headers=ADMIN).data)
        assert body["days"] == expected
