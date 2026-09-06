"""NFL regular-season segment capture: does the request actually GO OUT?

THE DEFECT THIS PINS. `_nfl_segment_market_map()` built all 36 segment keys and
its docstring said they were used *"both to REQUEST the keys and to TAG the
returned quotes so the two cannot drift"*. Only the tagging half was ever true:
`main()` called `fetch_odds(api_key=..., region=...)` with no `markets=`, so the
literal default `"h2h,spreads,totals"` went out and the segment keys reached
`quote_rows_from_oddsapi_events` alone -- where a key that never arrived cannot
be tagged.

Everything looked healthy. The map was built and passed;
`test_all_sports_segment_wiring.py` asserted the token
`segment_market_keys("nfl")` appeared in the file and passed; production NFL
shards carried zero segment rows. **A token is not a request.**

So these tests assert the OUTBOUND CALL, never a token. The distinction is the
whole point: a source-level check is exactly what was already green.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _nfl_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_nfl_team_odds_local", ROOT / "scripts" / "fetch_nfl_team_odds_local.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers = {}
        self.url = "https://api.the-odds-api.com/v4/x"
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.fixture()
def calls(monkeypatch):
    """Every outbound GET, from whichever module makes it."""
    recorded: list[dict] = []

    def _get(url, params=None, timeout=None, **_kw):
        recorded.append({"url": url, "params": dict(params or {})})
        if "/events/" in url:
            event_id = url.rstrip("/").split("/")[-2]
            return _Response({"id": event_id, "bookmakers": []})
        return _Response([])

    import requests

    monkeypatch.setattr(requests, "get", _get)
    return recorded


EVENTS = [
    {
        "id": "evt1",
        "commence_time": "2099-01-01T00:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
    }
]


def test_segment_request_reaches_the_per_event_endpoint_when_configured(monkeypatch, calls):
    """THE REACHABILITY TEST. Fails against unmodified code, where no per-event
    call exists at all for regular-season NFL."""
    monkeypatch.setenv("SYNDICATE_NFL_SEGMENT_MARKETS", "h1")
    # The window has to admit a fixture kickoff in 2099.
    monkeypatch.setenv("SYNDICATE_NFL_SEGMENT_PREGAME_WINDOW_SECONDS", str(10**12))

    module = _nfl_module()
    payloads = module._fetch_nfl_segments("key", EVENTS)

    per_event = [c for c in calls if "/events/" in c["url"]]
    assert per_event, "configured for h1 capture and NOT ONE per-event call went out"
    assert per_event[0]["url"].endswith("/sports/americanfootball_nfl/events/evt1/odds")
    markets = per_event[0]["params"]["markets"].split(",")
    assert set(markets) == {"h2h_h1", "spreads_h1", "totals_h1"}
    assert len(payloads) == 1


def test_no_per_event_call_when_unconfigured(monkeypatch, calls):
    """off != on. Absent means OFF -- no call, no credit, no behaviour change."""
    monkeypatch.delenv("SYNDICATE_NFL_SEGMENT_MARKETS", raising=False)
    module = _nfl_module()
    payloads = module._fetch_nfl_segments("key", EVENTS)
    assert payloads == []
    assert [c for c in calls if "/events/" in c["url"]] == []


def test_bulk_call_still_sends_only_full_game_markets(monkeypatch, calls):
    """The bulk route 422s INVALID_MARKET on a segment key and takes the
    full-game markets on the same call down with it. Nine days of soccer
    capture were lost to exactly that, so this stays asserted."""
    module = _nfl_module()
    module.fetch_odds(api_key="key", region="us")
    bulk = [c for c in calls if c["url"].endswith("/sports/americanfootball_nfl/odds")]
    assert len(bulk) == 1
    sent = set(bulk[0]["params"]["markets"].split(","))
    assert sent == {"h2h", "spreads", "totals"}
    assert not any("_h1" in m or "_q1" in m for m in sent)


def test_segment_regions_are_not_widened_on_the_per_event_call(monkeypatch, calls):
    """`SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` (`eu,us_ex` in production) must
    not reach a per-event call: OddsAPI bills markets x regions, so it would
    triple the bill of the most expensive call on the platform silently."""
    monkeypatch.setenv("SYNDICATE_NFL_SEGMENT_MARKETS", "h1")
    monkeypatch.setenv("SYNDICATE_NFL_SEGMENT_PREGAME_WINDOW_SECONDS", str(10**12))
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "eu,us_ex")

    module = _nfl_module()
    module._fetch_nfl_segments("key", EVENTS)
    per_event = [c for c in calls if "/events/" in c["url"]]
    assert per_event[0]["params"]["regions"] == "us"


def test_quote_rows_tag_a_returned_h1_market_as_h1_not_full():
    """The other half of the original claim -- tagging -- must still hold, and
    must not silently store a half line as a full-game line."""
    from syndicate.features.shared.odds_book_quotes import quote_rows_from_oddsapi_events

    module = _nfl_module()
    payload = [
        {
            "id": "evt1",
            "commence_time": "2026-09-07T17:00:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {"key": "totals_h1", "outcomes": [{"name": "Over", "point": 21.5, "price": -110}]},
                    ],
                }
            ],
        }
    ]
    rows = quote_rows_from_oddsapi_events(payload, market_map=module._nfl_segment_market_map())
    assert len(rows) == 1
    assert rows[0]["segment"] == "h1"
    assert rows[0]["market"] == "totals"
    assert rows[0]["line"] == 21.5
