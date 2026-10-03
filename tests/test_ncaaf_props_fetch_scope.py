"""NCAAF props: one request per event, scoped to the board's horizon.

Lane `layer2-freshness-1h`, user 2026-10-02 ("do both 1 and 2 for NCAAF props").
Measured on the fleet that day: the sweep made ~500 calls and ~250 credits a run,
about every 22 minutes (~20k credits/day, ~12% of the monthly cap), for a board
that served 2 NCAAF prop rows -- it fetched the whole week while the board shows
today and tomorrow.

Reachability first: every test below drives the real `main()` or the real
planner, and the end-to-end test counts the requests that were actually made.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import fetch_ncaaf_oddsapi_props_local as fetch_module

# Thursday 2026-10-02, 11:00 CT.
NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)


def _event(event_id: str, commence: str, *, with_props: bool = True) -> dict:
    event = {"id": event_id, "home_team": f"Home {event_id}", "away_team": f"Away {event_id}", "commence_time": commence}
    event["bookmakers"] = (
        [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "outcomes": [
                            {"name": "Over", "description": f"QB {event_id}", "point": 245.5, "price": -110},
                            {"name": "Under", "description": f"QB {event_id}", "point": 245.5, "price": -110},
                        ],
                    }
                ],
            }
        ]
        if with_props
        else []
    )
    return event


THU_NIGHT = "2026-10-03T00:30:00Z"   # 7:30pm CT Thursday 10-02 -> near (UTC date is 10-03)
FRI_NIGHT = "2026-10-04T00:00:00Z"   # 7:00pm CT Friday 10-03 -> near (tomorrow)
SAT_NOON = "2026-10-04T16:00:00Z"    # 11:00am CT Saturday 10-04 -> far


def test_near_events_are_always_fetched_and_far_ones_carried_while_fresh():
    scoped = [_event("thu", THU_NIGHT), _event("fri", FRI_NIGHT), _event("sat", SAT_NOON)]
    one_hour_ago = (NOW - timedelta(hours=1)).isoformat()
    to_fetch, carried = fetch_module.plan_event_fetch(
        scoped, {"thu": one_hour_ago, "fri": one_hour_ago, "sat": one_hour_ago}, now=NOW
    )
    assert [e["id"] for e in to_fetch] == ["thu", "fri"]
    assert carried == ["sat"]


def test_a_far_event_is_refetched_once_its_heartbeat_is_due():
    scoped = [_event("sat", SAT_NOON)]
    seven_hours_ago = (NOW - timedelta(hours=7)).isoformat()
    to_fetch, carried = fetch_module.plan_event_fetch(scoped, {"sat": seven_hours_ago}, now=NOW)
    assert [e["id"] for e in to_fetch] == ["sat"] and carried == []


def test_a_far_event_never_fetched_is_fetched():
    to_fetch, carried = fetch_module.plan_event_fetch([_event("sat", SAT_NOON)], {}, now=NOW)
    assert [e["id"] for e in to_fetch] == ["sat"] and carried == []


def test_the_near_window_is_the_central_calendar_not_utc():
    # 7:30pm CT Thursday is 10-03 in UTC; it is TONIGHT and must be near. A
    # 25-minute-old fetch separates the two readings: due for a near pregame
    # event (20 min), carried for a far one (6h heartbeat).
    recent = (NOW - timedelta(minutes=25)).isoformat()
    to_fetch, carried = fetch_module.plan_event_fetch([_event("thu", THU_NIGHT)], {"thu": recent}, now=NOW)
    assert [e["id"] for e in to_fetch] == ["thu"] and carried == []


# Lane `ncaaf-props-credit-cut` (2026-10-03): near events refresh by their OWN age.
# Measured: NCAAF spent 5,332 credits in the half hour after 16:00Z, re-fetching
# ~51 events x 9 markets on every ~2.5-minute live sweep.
FRI_IN_PLAY = "2026-10-02T15:30:00Z"   # kicked off 30 min before NOW -> near, in progress


def test_reachability_a_near_pregame_event_fetched_recently_is_carried():
    five = (NOW - timedelta(minutes=5)).isoformat()
    to_fetch, carried = fetch_module.plan_event_fetch([_event("fri", FRI_NIGHT)], {"fri": five}, now=NOW)
    assert to_fetch == [] and carried == ["fri"], "a live sweep must not re-buy a game that has not started"
    stale = (NOW - timedelta(minutes=21)).isoformat()
    to_fetch, carried = fetch_module.plan_event_fetch([_event("fri", FRI_NIGHT)], {"fri": stale}, now=NOW)
    assert [e["id"] for e in to_fetch] == ["fri"]


def test_an_in_progress_event_refreshes_at_most_every_15_minutes():
    ten = (NOW - timedelta(minutes=10)).isoformat()
    sixteen = (NOW - timedelta(minutes=16)).isoformat()
    assert fetch_module.plan_event_fetch([_event("live", FRI_IN_PLAY)], {"live": ten}, now=NOW) == ([], ["live"])
    to_fetch, _ = fetch_module.plan_event_fetch([_event("live", FRI_IN_PLAY)], {"live": sixteen}, now=NOW)
    assert [e["id"] for e in to_fetch] == ["live"]


def test_never_fetched_or_zero_window_always_fetches(monkeypatch):
    assert [e["id"] for e in fetch_module.plan_event_fetch([_event("fri", FRI_NIGHT)], {}, now=NOW)[0]] == ["fri"]
    one = (NOW - timedelta(minutes=1)).isoformat()
    monkeypatch.setenv("NCAAF_PROPS_PREGAME_REFRESH_SECONDS", "0")
    monkeypatch.setenv("NCAAF_PROPS_INPLAY_REFRESH_SECONDS", "0")
    events = [_event("fri", FRI_NIGHT), _event("live", FRI_IN_PLAY)]
    to_fetch, carried = fetch_module.plan_event_fetch(events, {"fri": one, "live": one}, now=NOW)
    assert [e["id"] for e in to_fetch] == ["fri", "live"] and carried == []


@pytest.fixture
def stub_oddsapi(monkeypatch):
    """The real fetch code, with requests stubbed: counts every HTTP call."""
    calls: list[str] = []
    listed = [_event("thu", THU_NIGHT), _event("sat", SAT_NOON), _event("fcs", SAT_NOON, with_props=False)]

    class _Resp:
        def __init__(self, payload, url):
            self._payload, self.url, self.status_code, self.headers, self.text = payload, url, 200, {}, ""

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, params=None, timeout=None):
        calls.append(f"{url}|{(params or {}).get('markets', '')}")
        if url.endswith("/events"):
            return _Resp([{k: v for k, v in e.items() if k != "bookmakers"} for e in listed], url)
        event_id = url.split("/events/")[1].split("/")[0]
        return _Resp(next(e for e in listed if e["id"] == event_id), url)

    quoted: list[list[str]] = []
    monkeypatch.setattr(fetch_module.requests, "get", fake_get)
    monkeypatch.setattr(fetch_module, "record_oddsapi_quota", lambda *a, **k: None)
    monkeypatch.setattr(fetch_module, "events_in_scope", lambda events, **k: events)
    monkeypatch.setattr(
        fetch_module, "_append_ncaaf_book_quotes", lambda events, **k: quoted.append([e["id"] for e in events])
    )
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    monkeypatch.delenv("ODDSAPI_PROPS_MODE", raising=False)
    return calls, quoted


def _run(tmp_path: Path) -> int:
    out = tmp_path / "oddsapi_player_props_2026_wk5.csv"
    return fetch_module.main(["--season", "2026", "--week", "5", "--out", str(out)])


def test_end_to_end_one_request_per_event_and_carried_events_are_never_quoted(tmp_path, stub_oddsapi, monkeypatch):
    calls, quoted = stub_oddsapi
    monkeypatch.setattr(fetch_module, "datetime", _FrozenDatetime)

    # Run 1, nothing captured yet: every in-scope event is fetched, ONE request each.
    assert _run(tmp_path) == 0
    event_calls = [c for c in calls if "/events/" in c]
    assert len(event_calls) == 3, calls
    assert all("player_pass_yds" in c and "," in c.split("|")[1] for c in event_calls), "combined: all markets per request"
    assert quoted[-1] == ["thu", "sat"]

    # Run 2, 21 minutes later (the next pregame sweep): the near game is due again
    # and re-fetched; Saturday's is carried, the prop-less FCS game is neither.
    monkeypatch.setattr(fetch_module, "datetime", _clock(NOW + timedelta(minutes=21)))
    calls.clear()
    assert _run(tmp_path) == 0
    assert [c.split("/events/")[1].split("/")[0] for c in calls if "/events/" in c] == ["thu"]
    assert quoted[-1] == ["thu"], "a carried payload must never reach the quote log"

    raw = json.loads((tmp_path / "oddsapi_player_props_2026_wk5_raw.json").read_text(encoding="utf-8"))
    assert raw["events_fetched"] == 1 and raw["events_carried"] == 1
    assert {e["id"] for e in raw["events"]} == {"thu", "sat"}
    csv_text = (tmp_path / "oddsapi_player_props_2026_wk5.csv").read_text(encoding="utf-8")
    assert "QB sat" in csv_text, "Saturday's props stay in the CSV for the NCAAF page"

    # Run 3, five minutes after run 2 (a live sweep): nothing is due, nothing is bought.
    monkeypatch.setattr(fetch_module, "datetime", _clock(NOW + timedelta(minutes=26)))
    calls.clear()
    assert _run(tmp_path) == 0
    assert [c for c in calls if "/events/" in c] == [], "lane ncaaf-props-credit-cut: no re-buy within the window"
    csv_text = (tmp_path / "oddsapi_player_props_2026_wk5.csv").read_text(encoding="utf-8")
    assert "QB thu" in csv_text and "QB sat" in csv_text, "carried events keep their rows"


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


def _clock(instant):
    class _At(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    return _At
