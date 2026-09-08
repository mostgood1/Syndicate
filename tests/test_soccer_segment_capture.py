"""Soccer first-half / second-half capture: reachability first, then correctness.

`model_engine_standard` §4.3 -- a REACHABILITY test (`off != on`) before any
correctness test, for anything behind a flag. The defect this path replaces is
itself an inert feature that looked alive: `_segment_market_map()` in the soccer
fetcher has carried `h2h_h1`/`totals_h2`/... since `#343`, and not one of those
keys was ever REQUESTED -- the bulk endpoint 422s on them, so they lived as a
tagging map for markets that never arrived.

Every HTTP call here is mocked. The tests that matter most are the ones that
count outbound calls: with `SYNDICATE_SOCCER_SEGMENT_MARKETS` unset the script
must make exactly the ONE bulk call it always made, and nothing else, because
"no extra credit until someone sets the key" is the whole deployment contract.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from scripts import fetch_soccer_oddsapi_odds_local as soccer
from syndicate.features.shared import segment_odds_fetch as sof

NOW = datetime(2026, 9, 12, 13, 0, 0, tzinfo=timezone.utc)  # a Saturday, 14:00 UK
H1_KEYS = {"h2h_h1", "spreads_h1", "totals_h1"}


def _event(event_id: str, minutes_from_now: float, *, now: datetime = NOW) -> dict:
    return {
        "id": event_id,
        "commence_time": (now + timedelta(minutes=minutes_from_now)).isoformat().replace("+00:00", "Z"),
        "home_team": "Home FC",
        "away_team": "Away FC",
        "bookmakers": [],
    }


class _Response:
    def __init__(self, payload, status_code=200, url="https://api.the-odds-api.com/v4/x"):
        self._payload = payload
        self.status_code = status_code
        self.headers: dict = {}
        self.url = url
        self.text = "" if status_code < 400 else '{"error_code":"INVALID_MARKET"}'

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


class _Session:
    """Records every outbound call. The only way to prove `off` made none."""

    def __init__(self, payload_for=None, status_for=None):
        self.calls: list[dict] = []
        self._payload_for = payload_for
        self._status_for = status_for or (lambda _eid: 200)

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        event_id = url.rstrip("/").split("/")[-2]
        payload = (self._payload_for or (lambda _eid: {"id": _eid, "bookmakers": []}))(event_id)
        return _Response(payload, status_code=self._status_for(event_id), url=url)


# --------------------------------------------------------------------------
# 1. REACHABILITY. off != on, on the thing that actually costs money: the call.
# --------------------------------------------------------------------------


def test_capture_is_off_when_the_key_is_absent_and_makes_no_call():
    """ABSENT MEANS OFF. Asserted, not described -- `CLAUDE.md`: the same edit
    is a no-op in one direction and a behaviour change in the other depending
    on the code's default."""
    session = _Session()
    payloads, stats = soccer.fetch_event_segments(
        "k",
        [_event("e1", 60), _event("e2", -20)],
        sport_key="soccer_epl",
        session=session,
        now=NOW,
        env={},
    )
    assert payloads == []
    assert stats["enabled"] is False
    assert stats["estimated_credits"] == 0
    assert session.calls == [], "capture is OFF but a credit-spending call went out"


def test_on_differs_from_off_and_requests_exactly_the_h1_keys_per_in_window_event():
    session = _Session()
    events = [
        _event("pre_1", 60),        # 1h out         -> pregame tier
        _event("pre_2", 300),       # 5h out         -> pregame tier (6h window)
        _event("too_far", 8 * 60),  # 8h out         -> out of window
        _event("finished", -180),   # 3h ago         -> out of window
    ]
    payloads, stats = soccer.fetch_event_segments(
        "k", events, sport_key="soccer_spain_la_liga", session=session, now=NOW,
        env={"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1"},
    )
    assert stats["enabled"] is True
    assert len(session.calls) == 2, "capture is ON but the in-window events were not each called once"
    assert len(payloads) == 2 and stats["ok_events"] == 2
    called = {call["url"].rstrip("/").split("/")[-2] for call in session.calls}
    assert called == {"pre_1", "pre_2"}
    for call in session.calls:
        assert set(call["params"]["markets"].split(",")) == H1_KEYS
        assert "h2h" not in call["params"]["markets"].split(","), "a full-game key on the per-event call is a credit spent twice"
        assert call["params"]["regions"] == "us"
    assert stats["estimated_credits"] == 2 * 3 * 1


def test_league_sport_key_is_the_bulk_calls_key_not_a_second_mapping():
    """The per-event URL must carry the same OddsAPI key the bulk call resolved
    from `LEAGUE_SPORT_KEYS`; a second mapping is a second thing to drift."""
    for league, sport_key in soccer.LEAGUE_SPORT_KEYS.items():
        session = _Session()
        soccer.fetch_event_segments(
            "k", [_event("e1", 30)], sport_key=sport_key, session=session, now=NOW,
            env={"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1"},
        )
        assert session.calls[0]["url"].endswith(f"/sports/{sport_key}/events/e1/odds"), league


def test_segment_regions_are_not_widened_by_the_shared_knob():
    """`eu,us_ex` must NOT reach a per-event call -- the 3x bill nothing
    behavioural would notice."""
    session = _Session()
    soccer.fetch_event_segments(
        "k", [_event("e1", 30)], sport_key="soccer_epl", session=session, now=NOW,
        env={"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1", "SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS": "eu,us_ex"},
    )
    assert session.calls[0]["params"]["regions"] == "us"


# --------------------------------------------------------------------------
# 2. FAILURE ISOLATION and the CIRCUIT BREAKER.
# --------------------------------------------------------------------------


def test_a_422_on_one_event_does_not_abort_the_others():
    session = _Session(status_for=lambda eid: 422 if eid == "bad" else 200)
    payloads, stats = soccer.fetch_event_segments(
        "k", [_event("ok_1", 30), _event("bad", 45), _event("ok_2", 60)],
        sport_key="soccer_epl", session=session, now=NOW,
        env={"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1"},
    )
    assert len(session.calls) == 3, "the 422 stopped the sweep"
    assert {p["id"] for p in payloads} == {"ok_1", "ok_2"}
    assert stats["ok_events"] == 2 and stats["failed_events"] == 1
    assert "422" in stats["last_error"]


def test_circuit_breaker_trips_above_40_events_and_keeps_those_nearest_kickoff():
    """The tier's cost is linear in events and the slate comes from a vendor.
    A league-day is <=12 fixtures, so 45 in one window is a bad response, and
    the cap must bound the spend loudly rather than pay for it."""
    session = _Session()
    events = [_event(f"e{i:02d}", 5 + i * 7) for i in range(45)]  # 5m .. 5h13m out
    payloads, stats = soccer.fetch_event_segments(
        "k", events, sport_key="soccer_efl_champ", session=session, now=NOW,
        env={"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1"},
    )
    assert stats["max_events"] == sof.DEFAULT_MAX_EVENTS == 40
    assert len(session.calls) == 40
    assert stats["capped"] == 5
    assert len(payloads) == 40
    called = {call["url"].rstrip("/").split("/")[-2] for call in session.calls}
    assert called == {f"e{i:02d}" for i in range(40)}, "the cap dropped the wrong end of the slate"


# --------------------------------------------------------------------------
# 3. SOCCER'S LIVE WINDOW. An h1 market dies at half-time, ~48 min in.
# --------------------------------------------------------------------------


def test_live_window_is_a_soccer_half_when_only_h1_is_configured():
    env = soccer._soccer_segment_env({"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1"})
    assert env["SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS"] == str(55 * 60)
    # 40 min in: h1 still trading -> in. 70 min in: half-time has passed -> out.
    scoped, stats = sof.events_in_window(
        [_event("first_half", -40), _event("second_half", -70)], sport="soccer", now=NOW, env=env,
    )
    assert [e["id"] for e in scoped] == ["first_half"]
    assert stats["live_window_seconds"] == 55 * 60


def test_live_window_keeps_the_shared_default_when_h2_is_configured_and_explicit_value_wins():
    # h2 trades into the second half, so the shared 1h45 stays.
    env = soccer._soccer_segment_env({"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1,h2"})
    assert "SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS" not in env
    _, stats = sof.events_in_window([], sport="soccer", now=NOW, env=env)
    assert stats["live_window_seconds"] == sof.DEFAULT_LIVE_WINDOW_SECONDS
    # An operator's explicit value is never overwritten.
    env = soccer._soccer_segment_env({
        "SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1",
        "SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS": "1200",
    })
    assert env["SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS"] == "1200"


def test_soccer_segment_env_never_writes_os_environ():
    before = dict(os.environ)
    with mock.patch.dict(os.environ, {"SYNDICATE_SOCCER_SEGMENT_MARKETS": "h1"}, clear=False):
        os.environ.pop("SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS", None)
        env = soccer._soccer_segment_env()
        assert "SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS" in env
        assert "SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS" not in os.environ
    assert dict(os.environ) == before


# --------------------------------------------------------------------------
# 4. END TO END through `main()`: one bulk call when off; tagged tape when on.
# --------------------------------------------------------------------------


def _bulk_payload(now: datetime) -> list[dict]:
    return [
        {
            **_event("evt_a", 90, now=now),
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {"key": "totals", "last_update": now.isoformat(),
                         "outcomes": [{"name": "Over", "point": 2.5, "price": -110}, {"name": "Under", "point": 2.5, "price": -110}]},
                        {"key": "h2h", "last_update": now.isoformat(),
                         "outcomes": [{"name": "Home FC", "price": 120}, {"name": "Away FC", "price": 210}, {"name": "Draw", "price": 230}]},
                    ],
                }
            ],
        },
        _event("evt_b", 30 * 60, now=now),  # 30h out: never in a segment window
    ]


def _segment_payload(event_id: str, now: datetime) -> dict:
    return {
        **_event(event_id, 90, now=now),
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {"key": "totals_h1", "last_update": now.isoformat(),
                     "outcomes": [{"name": "Over", "point": 1.0, "price": -105}, {"name": "Under", "point": 1.0, "price": -115}]},
                    {"key": "h2h_h1", "last_update": now.isoformat(),
                     "outcomes": [{"name": "Home FC", "price": 150}, {"name": "Away FC", "price": 260}]},
                ],
            }
        ],
    }


class _Http:
    """Stands in for `requests.get` for BOTH the bulk call and the per-event
    calls -- the shared fetcher's `session or requests` resolves to the same
    patched module -- so one recorder sees every credit the script would spend."""

    def __init__(self, now: datetime):
        self.now = now
        self.calls: list[dict] = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if url.endswith("/odds") and "/events/" not in url:
            return _Response(_bulk_payload(self.now), url=url)
        event_id = url.rstrip("/").split("/")[-2]
        return _Response(_segment_payload(event_id, self.now), url=url)


def _run_main(tmp_path, monkeypatch, *, env_markets: str | None):
    now = datetime.now(tz=timezone.utc)
    http = _Http(now)
    appended: list[dict] = []

    def _capture_append(**kwargs):
        appended.append(kwargs)
        return {"appended": len(list(kwargs.get("rows") or []))}

    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.setenv("ODDS_API_BASE", "https://api.the-odds-api.com/v4")
    monkeypatch.delenv("ODDS_API_SOCCER_GAME_MARKETS", raising=False)
    monkeypatch.delenv("SYNDICATE_SOCCER_SEGMENT_LIVE_WINDOW_SECONDS", raising=False)
    if env_markets is None:
        monkeypatch.delenv("SYNDICATE_SOCCER_SEGMENT_MARKETS", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_SOCCER_SEGMENT_MARKETS", env_markets)
    out = tmp_path / "game_odds_current.csv"
    with mock.patch.object(soccer, "_load_env", lambda: None), \
            mock.patch("requests.get", http), \
            mock.patch("syndicate.features.shared.odds_book_quotes.append_book_quotes", _capture_append), \
            mock.patch.object(sys, "argv", ["fetch_soccer_oddsapi_odds_local.py", "--league", "epl", "--out", str(out)]):
        rc = soccer.main()
    assert rc == 0
    assert out.exists()
    return http, appended


def test_main_with_the_key_absent_makes_only_the_one_bulk_call(tmp_path, monkeypatch):
    """The deployment contract: absent env = the single call this script has
    always made, zero per-event calls, zero extra credit."""
    http, appended = _run_main(tmp_path, monkeypatch, env_markets=None)
    assert len(http.calls) == 1
    assert http.calls[0]["url"].endswith("/sports/soccer_epl/odds")
    assert set(http.calls[0]["params"]["markets"].split(",")) == set(soccer.DEFAULT_GAME_MARKETS)
    rows = [row for call in appended for row in call["rows"]]
    assert rows, "the full-game rows themselves must still reach the tape"
    assert {row["segment"] for row in rows} == {"full"}


def test_main_with_h1_calls_each_in_window_event_and_lands_h1_rows_on_the_tape(tmp_path, monkeypatch):
    http, appended = _run_main(tmp_path, monkeypatch, env_markets="h1")
    bulk = [c for c in http.calls if "/events/" not in c["url"]]
    per_event = [c for c in http.calls if "/events/" in c["url"]]
    assert len(bulk) == 1
    # evt_a is 90 min out -> pregame tier; evt_b is 30h out -> no call.
    assert [c["url"].rstrip("/").split("/")[-2] for c in per_event] == ["evt_a"]
    assert per_event[0]["url"].endswith("/sports/soccer_epl/events/evt_a/odds")
    assert set(per_event[0]["params"]["markets"].split(",")) == H1_KEYS
    # The bulk request list is untouched: no segment key may reach it (#343).
    assert set(bulk[0]["params"]["markets"].split(",")) == set(soccer.DEFAULT_GAME_MARKETS)

    rows = [row for call in appended for row in call["rows"]]
    assert all(call["sport"] == "soccer" for call in appended)
    assert all(call["extra"] == {"league": "epl"} for call in appended)
    h1_rows = [r for r in rows if r["segment"] == "h1"]
    full_rows = [r for r in rows if r["segment"] == "full"]
    assert h1_rows and full_rows
    # Canonical market names, not the raw OddsAPI keys.
    assert {r["market"] for r in h1_rows} == {"totals", "h2h"}
    assert not any(r["market"].endswith("_h1") for r in rows)
    assert {r["event_id"] for r in h1_rows} == {"evt_a"}
    # The half total (1.0) must never be stored as a full-game total, and the
    # full-game total (2.5) is still there beside it.
    assert ("full", "totals", 1.0) not in {(r["segment"], r["market"], r["line"]) for r in rows}
    assert ("h1", "totals", 1.0) in {(r["segment"], r["market"], r["line"]) for r in rows}
    assert ("full", "totals", 2.5) in {(r["segment"], r["market"], r["line"]) for r in rows}
    # Nothing outside the shared vocabulary ever reaches the tape.
    assert {r["segment"] for r in rows} <= {"full", "h1"}


def test_the_csv_is_unchanged_by_segment_payloads(tmp_path, monkeypatch):
    """The CSV is the board's full-game input and is built from the bulk
    response alone; the segment tier writes to the quote tape only."""
    import pandas as pd

    _run_main(tmp_path, monkeypatch, env_markets="h1")
    df = pd.read_csv(tmp_path / "game_odds_current.csv")
    assert set(df["market"].astype(str)) <= set(soccer.DEFAULT_GAME_MARKETS)
    assert not df["market"].astype(str).str.endswith("_h1").any()


# --------------------------------------------------------------------------
# 5. The wiring test's pin: the bulk request list never gains a segment key.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("segments", ["h1", "h1,h2", "all"])
def test_bulk_request_list_ignores_the_segment_env(segments):
    with mock.patch.dict(os.environ, {"SYNDICATE_SOCCER_SEGMENT_MARKETS": segments}, clear=False):
        os.environ.pop("ODDS_API_SOCCER_GAME_MARKETS", None)
        assert soccer._game_markets() == list(soccer.DEFAULT_GAME_MARKETS)
