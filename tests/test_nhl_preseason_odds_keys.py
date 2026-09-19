"""NHL preseason odds live under TheOddsAPI's own `icehockey_nhl_preseason` key.

2026-09-19: all 7 preseason games generated `anchor_state=no_market`, with every
odds column blank, because only `icehockey_nhl` was ever requested.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from syndicate import local_nhl_odds as lno

DATE = "2026-09-19"


def _event(event_id: str, sport_key: str) -> dict:
    return {
        "id": event_id,
        "sport_key": sport_key,
        "commence_time": "2026-09-19T23:00:00Z",
        "home_team": "St. Louis Blues",
        "away_team": "Dallas Stars",
    }


def _odds(event: dict) -> dict:
    return {
        **event,
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-09-19T15:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2026-09-19T15:00:00Z",
                        "outcomes": [
                            {"name": "St. Louis Blues", "price": -120},
                            {"name": "Dallas Stars", "price": 100},
                        ],
                    }
                ],
            }
        ],
    }


class FakeClient:
    def __init__(self, events_by_key: dict[str, list[dict]], *, reject_segment_markets_for: set[str] = frozenset(), fail_list_for: set[str] = frozenset()):
        self.events_by_key = events_by_key
        self.reject_segment_markets_for = set(reject_segment_markets_for)
        self.fail_list_for = set(fail_list_for)
        self.list_calls: list[str] = []
        self.odds_calls: list[tuple[str, str, str]] = []

    def list_events(self, sport, *, commence_from_iso=None, commence_to_iso=None):
        self.list_calls.append(sport)
        if sport in self.fail_list_for:
            raise RuntimeError(f"TheOddsAPI request failed (404) for /sports/{sport}/events")
        return list(self.events_by_key.get(sport, [])), {}

    def event_odds(self, sport, event_id, *, markets, regions="us", bookmakers=None):
        self.odds_calls.append((sport, event_id, markets))
        if sport in self.reject_segment_markets_for and set(markets.split(",")) - set(lno.NHL_CORE_TEAM_MARKETS):
            raise RuntimeError("TheOddsAPI request failed (422)")
        for event in self.events_by_key.get(sport, []):
            if event["id"] == event_id:
                return _odds(event), {}
        # Asking the WRONG key for an event returns nothing, as the real API does.
        return {}, {}


def test_both_keys_are_listed_and_each_event_keeps_its_own_key() -> None:
    client = FakeClient({
        lno.NHL_REGULAR_SPORT_KEY: [_event("reg1", lno.NHL_REGULAR_SPORT_KEY)],
        lno.NHL_PRESEASON_SPORT_KEY: [_event("pre1", lno.NHL_PRESEASON_SPORT_KEY)],
    })
    events = lno.list_nhl_events(client, commence_from_iso="a", commence_to_iso="b")
    assert client.list_calls == [lno.NHL_REGULAR_SPORT_KEY, lno.NHL_PRESEASON_SPORT_KEY]
    assert {e["id"]: e["sport_key"] for e in events} == {"reg1": lno.NHL_REGULAR_SPORT_KEY, "pre1": lno.NHL_PRESEASON_SPORT_KEY}


def test_preseason_list_failure_does_not_cost_the_regular_board() -> None:
    client = FakeClient({lno.NHL_REGULAR_SPORT_KEY: [_event("reg1", lno.NHL_REGULAR_SPORT_KEY)]}, fail_list_for={lno.NHL_PRESEASON_SPORT_KEY})
    events = lno.list_nhl_events(client, commence_from_iso="a", commence_to_iso="b")
    assert [e["id"] for e in events] == ["reg1"]


def test_regular_list_failure_still_raises() -> None:
    client = FakeClient({}, fail_list_for={lno.NHL_REGULAR_SPORT_KEY})
    with pytest.raises(RuntimeError):
        lno.list_nhl_events(client, commence_from_iso="a", commence_to_iso="b")


def test_team_odds_price_a_preseason_game() -> None:
    client = FakeClient({lno.NHL_PRESEASON_SPORT_KEY: [_event("pre1", lno.NHL_PRESEASON_SPORT_KEY)]})
    with patch.object(lno, "OddsApiClient", return_value=client):
        frame = lno.collect_oddsapi_team_odds(DATE, markets=["h2h", "spreads", "totals"])
    assert not frame.empty
    assert {call[0] for call in client.odds_calls} == {lno.NHL_PRESEASON_SPORT_KEY}


def test_preseason_event_retries_core_markets_when_period_markets_are_rejected() -> None:
    client = FakeClient(
        {lno.NHL_PRESEASON_SPORT_KEY: [_event("pre1", lno.NHL_PRESEASON_SPORT_KEY)]},
        reject_segment_markets_for={lno.NHL_PRESEASON_SPORT_KEY},
    )
    with patch.object(lno, "OddsApiClient", return_value=client):
        frame = lno.collect_oddsapi_team_odds(DATE)
    assert not frame.empty
    assert client.odds_calls[-1][2] == "h2h,spreads,totals"
    assert len(client.odds_calls) == 2


def test_props_request_the_preseason_key_for_a_preseason_event() -> None:
    client = FakeClient({lno.NHL_PRESEASON_SPORT_KEY: [_event("pre1", lno.NHL_PRESEASON_SPORT_KEY)]})
    client.historical_list_events = lambda *a, **k: ({"data": []}, {})
    with patch.object(lno, "OddsApiClient", return_value=client):
        lno.collect_oddsapi_props(DATE)
    assert client.odds_calls, "no props request was made for the preseason event"
    assert all(call[0] == lno.NHL_PRESEASON_SPORT_KEY for call in client.odds_calls)
