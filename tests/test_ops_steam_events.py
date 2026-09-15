"""`/api/ops/steam/events` -- the raw steam record, read the way the board reads it.

WHY IT EXISTS. The odds tracker writes steam events through `write_json_file`,
which on the keyvalue backend never touches disk. So `/api/ops/artifacts/export`
returned count 0 for `reports/steam/*` on 2026-09-15 while the board carried
steam cards, and the writer's `refresh_odds_sources.py` children never reach
Render's logs. Lane `legacy-steam-crossing-delta` needs each event's previous and
current price to count the steam flags that come only from a ±100 crossing.

THE PATH TEST MATTERS MOST. A reader that resolves a different key than the
writer reads "no events" on a day full of steam, which looks like a quiet market.

THE GATE TESTS MATTER TOO. The route lives on its own blueprint, not on
`ops_bp`, so the admin check that `ops_bp.before_request` gives every other ops
route has to be attached explicitly. These tests are what catch it going missing.
"""

from __future__ import annotations

import pytest

import syndicate.features.shared.refresh_state_store as store
from syndicate.app import app
from syndicate.features.shared.odds_refresh_tracking import steam_events_path_for_sport


ADMIN = {"X-Admin-Token": "test-token"}
URL = "/api/ops/steam/events"
TODAY = {"sport": "soccer", "date": "2026-09-15"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _event(previous_odds, odds_delta, *, line_delta=None):
    return {
        "sport": "soccer",
        "market_type": "totals",
        "price": previous_odds + odds_delta,
        "steam": {
            "previous_odds": previous_odds,
            "odds_delta": odds_delta,
            "previous_line": 1.5,
            "line_delta": line_delta,
            "capture_phase": "live",
            "window_seconds": 300.0,
        },
    }


def test_refuses_a_request_without_the_admin_token(client, monkeypatch):
    called = []
    monkeypatch.setattr(store, "read_json_file", lambda path: called.append(path))
    assert client.get(URL, query_string=TODAY).status_code == 401
    assert called == []  # refused BEFORE the store is touched


def test_refuses_a_wrong_admin_token(client):
    assert client.get(URL, query_string=TODAY, headers={"X-Admin-Token": "nope"}).status_code == 401


@pytest.mark.parametrize("params", [
    {"sport": "../soccer", "date": "2026-09-15"},
    {"sport": "soccer", "date": "2026-9-15"},
    {"sport": "", "date": "2026-09-15"},
    {"sport": "soccer"},
])
def test_rejects_anything_but_a_slug_and_an_iso_date(client, params):
    assert client.get(URL, query_string=params, headers=ADMIN).status_code == 400


def test_returns_the_record_the_WRITER_would_have_written(client, monkeypatch):
    seen = []
    events = [_event(-110.0, 215.0), _event(-130.0, 240.0, line_delta=-0.25)]

    def fake_read(path):
        seen.append(path)
        return {"date": "2026-09-15", "sport": "soccer", "events": events}

    monkeypatch.setattr(store, "read_json_file", fake_read)
    body = client.get(URL, query_string={"sport": "Soccer", "date": "2026-09-15"}, headers=ADMIN).get_json()
    assert seen == [steam_events_path_for_sport("soccer", "2026-09-15")]
    assert body["ok"] is True and body["count"] == 2 and body["truncated"] is False
    assert [e["steam"]["previous_odds"] for e in body["events"]] == [-110.0, -130.0]


def test_an_absent_record_reads_as_zero_not_an_error(client, monkeypatch):
    monkeypatch.setattr(store, "read_json_file", lambda path: None)
    body = client.get(URL, query_string=TODAY, headers=ADMIN).get_json()
    assert body == {"ok": True, "sport": "soccer", "date": "2026-09-15", "count": 0, "truncated": False, "events": []}


def test_an_oversized_record_keeps_the_newest_events_and_says_so(client, monkeypatch):
    import syndicate.blueprints.ops_steam as route

    events = [dict(_event(-110.0, 10.0), seq=i) for i in range(50)]
    monkeypatch.setattr(store, "read_json_file", lambda path: {"events": events})
    monkeypatch.setattr(route, "_RESPONSE_MAX_BYTES", 1200)
    body = client.get(URL, query_string=TODAY, headers=ADMIN).get_json()
    assert body["truncated"] is True and 0 < body["count"] < 50
    assert body["events"][-1]["seq"] == 49
