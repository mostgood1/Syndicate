"""`/api/ops/polymarket/slate` -- making the slate readable from web.

WHY THIS ENDPOINT AND NOT AN ALLOWLIST ENTRY. The obvious fix for "the slate is
invisible from ops" is to add it to `HOT_ARTIFACT_PATTERNS`. That would have
been an INERT no-op, and the test below pins the reason so nobody re-derives it:
both services run `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, so
`persist_game_slate` writes to the KEYVALUE STORE and never to disk, while the
export endpoint scans disk. The artifact was reachable from web all along --
what was missing was a reader.
"""

from __future__ import annotations

import json

import pytest

from syndicate.app import app


ADMIN = {"X-Admin-Token": "test-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _slate(markets):
    return {"fetched_at": 1.0, "markets": markets, "count": len(markets),
            "fetched_count": len(markets), "truncated": False, "dropped_for_size": 0}


def _install(monkeypatch, payload):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda *a, **k: payload,
        raising=False,
    )


def test_an_absent_slate_is_named_not_reported_as_empty(client, monkeypatch):
    """"No tick has written" must not read as "the venue lists nothing"."""
    _install(monkeypatch, None)
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["ok"] is True
    assert body["slate"] is None
    assert body["reason"] == "no_slate_artifact_recorded"


def test_it_requires_the_admin_token(client):
    assert client.get("/api/ops/polymarket/slate").status_code in (401, 403)


def test_it_counts_by_venue_market_type(client, monkeypatch):
    _install(monkeypatch, _slate([
        {"slug": "mlbgame-mlb-bos-mia-2026-08-26", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"},
        {"slug": "mlbgame-mlb-col-wsh-2026-08-26", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"},
        {"slug": "astatc-lol-bam-gng-2026-08-20-game1", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP"},
    ]))
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["ok"] is True
    assert body["by_venue_market_type"]["SPORTS_MARKET_TYPE_MONEYLINE"] == 2
    # PROP is counted as a market the venue sent, but must NOT appear in the
    # join cut -- it is deliberately out of scope for game lines, and merging
    # the two numbers is what makes "we dropped it" look like "they didn't
    # list it".
    assert body["by_venue_market_type"]["SPORTS_MARKET_TYPE_PROP"] == 1
    assert not any(k.endswith("|prop") for k in body["by_league_and_board_market"])


def test_an_unparseable_slug_is_counted_not_silently_dropped(client, monkeypatch):
    _install(monkeypatch, _slate([
        {"slug": "this-is-not-a-slug", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE"},
    ]))
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["slug_unparseable"] == 1


def test_a_read_error_is_reported_not_raised(client, monkeypatch):
    """An ops read must not 500 -- it is the tool used when things are broken."""

    def boom(*a, **k):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", boom, raising=False
    )
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["ok"] is False
    assert "RuntimeError" in body["error"]


def test_the_two_truncation_facts_stay_separate(client, monkeypatch):
    """`truncated` and `dropped_for_size` answer different questions.

    "The venue had more than we asked for" is a bug; "we chose not to store the
    far end" is a budget decision. One number for both hides the first.
    """
    payload = _slate([])
    payload["truncated"] = True
    payload["dropped_for_size"] = 12
    _install(monkeypatch, payload)
    body = json.loads(client.get("/api/ops/polymarket/slate", headers=ADMIN).data)
    assert body["truncated"] is True
    assert body["dropped_for_size"] == 12
