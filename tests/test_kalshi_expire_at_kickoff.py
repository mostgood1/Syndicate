"""SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF: a pregame Kalshi order carries `expiration_time` = game start.

User decision 2026-10-20 ("Build option C"). Absent = off = today's body, byte-identical.
CreateOrderV2: `expiration_time` is unix SECONDS and valid only with good_till_canceled.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from syndicate.features.shared import kalshi_orders as mod

NOW = dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.timezone.utc)
KICKOFF = "2026-10-21T00:30:00Z"  # 7:30 PM CT
KICKOFF_TS = int(dt.datetime(2026, 10, 21, 0, 30, tzinfo=dt.timezone.utc).timestamp())


def _request(**overrides):
    fields = dict(
        position_key="pk", selected_date="2026-10-20", venue="kalshi", sport="nba", event_id="e1",
        market="moneyline", side="home", requested_price=0.55, requested_stake_dollars=5.5,
        line=None, venue_ticker="KXNBAGAME-26OCT20OKCSAS-SAS", commence_time=KICKOFF,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.fixture(autouse=True)
def _stable(monkeypatch):
    monkeypatch.delenv("KALSHI_ORDER_SUBACCOUNT", raising=False)
    monkeypatch.delenv("KALSHI_ORDER_EXCHANGE_INDEX", raising=False)
    monkeypatch.delenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", raising=False)
    monkeypatch.setattr(mod, "_side_to_kalshi", lambda *_a: "yes")
    monkeypatch.setattr("syndicate.features.shared.execution_ledger.idempotency_key", lambda _r: "key-1")


def _body(**overrides):
    return mod.order_body_v2(_request(**overrides), price_dollars=0.55, now=NOW)


def test_off_and_on_produce_different_bodies(monkeypatch):
    """REACHABILITY FIRST: the flag must change what is sent."""
    off = _body()
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    on = _body()
    assert off != on
    assert "expiration_time" not in off
    assert on["expiration_time"] == KICKOFF_TS
    assert {k: v for k, v in on.items() if k != "expiration_time"} == off


@pytest.mark.parametrize("raw", ["", "off", "0", "false", "shadow", "bogus"])
def test_absent_or_anything_but_on_is_off(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", raw)
    assert "expiration_time" not in _body()


def test_expiry_rides_only_on_good_till_canceled(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    body = _body()
    assert body["time_in_force"] == "good_till_canceled"
    assert isinstance(body["expiration_time"], int)  # unix SECONDS, not ms, not a string


def test_offset_kickoff_is_converted_to_the_same_instant(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    assert _body(commence_time="2026-10-20T19:30:00-05:00")["expiration_time"] == KICKOFF_TS


@pytest.mark.parametrize(
    "commence, reason",
    [
        ("2026-10-20T22:00:00Z", "game_started"),   # in-play entry: an expiry in the past is a rejection
        ("2026-10-20T23:00:00Z", "game_started"),   # exactly at kickoff
        (None, "no_commence_time"),
        ("tonight", "unreadable_commence_time"),
    ],
)
def test_no_expiry_is_named_and_leaves_the_body_as_today(monkeypatch, commence, reason):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    request = _request(commence_time=commence)
    assert mod.kickoff_expiration(request, now=NOW) == (None, reason)
    assert "expiration_time" not in mod.order_body_v2(request, price_dollars=0.55, now=NOW)


def test_naive_commence_is_read_as_utc(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    assert _body(commence_time="2026-10-21T00:30:00")["expiration_time"] == KICKOFF_TS


def test_the_submit_line_names_the_expiry(monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    monkeypatch.setenv("KALSHI_API_BASE", "https://example.test/trade-api/v2")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).replace(microsecond=0)
    sent = {}

    def fake(method, url, *, body=None, **_kw):
        sent["body"] = body
        return {"order": {"order_id": "o1", "status": "resting", "fill_count_fp": "0.00"}}

    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request", fake)
    try:
        mod.submit_order(_request(commence_time=future.isoformat()), price_dollars=0.55)
    except Exception:
        pass  # the response shape is not under test; the request and its log line are
    assert sent["body"]["expiration_time"] == int(future.timestamp())
    line = [ln for ln in capsys.readouterr().out.splitlines() if "[kalshi_orders] SUBMIT " in ln][0]
    assert f"expiry={int(future.timestamp())}" in line


def test_the_submit_line_says_disabled_when_off(monkeypatch, capsys):
    monkeypatch.setenv("KALSHI_API_BASE", "https://example.test/trade-api/v2")
    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request",
                        lambda *_a, **_k: {"order": {"order_id": "o1", "status": "resting"}})
    try:
        mod.submit_order(_request(), price_dollars=0.55)
    except Exception:
        pass
    assert "expiry=disabled" in capsys.readouterr().out
