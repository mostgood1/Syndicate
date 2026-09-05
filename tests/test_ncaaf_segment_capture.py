"""NCAAF half/quarter capture: reachability first, then correctness.

`model_engine_standard` §4.3 -- a REACHABILITY test (`off != on`) before any
correctness test, for anything behind a flag. Four inert features in one session
were caught by that rule and by nothing else, and the defect this module fixes
is itself an inert feature that looked alive for weeks: NFL's segment map is
built, passed around, and never reaches a `markets=` parameter.

The billing test (`test_segment_regions_are_not_widened_by_the_shared_knob`) is
the highest-value one here. The shared `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS`
knob widens to `eu,us_ex`, and `odds_regions.py` exists to keep that widening on
the CHEAP side of the billing split. Applying it to a PER-EVENT call would
triple the bill of the most expensive call on the platform with no line of code
saying so, and nothing else in the suite would notice.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import segment_odds_fetch as sof

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 5, 18, 0, 0, tzinfo=timezone.utc)


def _ncaaf_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_ncaaf_oddsapi_game_lines", ROOT / "scripts" / "fetch_ncaaf_oddsapi_game_lines.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(event_id: str, minutes_from_now: float) -> dict:
    return {
        "id": event_id,
        "commence_time": (NOW + timedelta(minutes=minutes_from_now)).isoformat().replace("+00:00", "Z"),
        "home_team": "Home U",
        "away_team": "Away U",
    }


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}
        self.url = "https://api.the-odds-api.com/v4/x"
        self.text = ""

    def json(self):
        return self._payload


class _Session:
    """Records every outbound call. The only way to prove `off` made none."""

    def __init__(self, payload_for=None):
        self.calls: list[dict] = []
        self._payload_for = payload_for

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        event_id = url.rstrip("/").split("/")[-2]
        payload = (self._payload_for or (lambda _eid: {"id": _eid, "bookmakers": []}))(event_id)
        return _Response(payload)


# --------------------------------------------------------------------------
# 1. REACHABILITY. off != on, on the thing that actually costs money: the call.
# --------------------------------------------------------------------------


def test_capture_is_off_when_the_key_is_absent_and_makes_no_call():
    """ABSENT MEANS OFF, and `CLAUDE.md` requires this to be stated and tested.

    The same edit is a no-op in one direction and a behaviour change in the
    other depending on the code's default, so the default is asserted rather
    than described.
    """
    session = _Session()
    payloads, stats = sof.fetch_event_segments(
        api_key="k",
        sport="ncaaf",
        sport_key="americanfootball_ncaaf",
        base_url="https://api.the-odds-api.com/v4",
        events=[_event("e1", 60), _event("e2", -30)],
        session=session,
        now=NOW,
        env={},
    )
    assert payloads == []
    assert stats["enabled"] is False
    assert stats["estimated_credits"] == 0
    assert session.calls == [], "capture is OFF but a credit-spending call went out"


def test_capture_is_on_when_configured_and_off_differs_from_on():
    session = _Session()
    payloads, stats = sof.fetch_event_segments(
        api_key="k",
        sport="ncaaf",
        sport_key="americanfootball_ncaaf",
        base_url="https://api.the-odds-api.com/v4",
        events=[_event("e1", 60), _event("e2", -30)],
        session=session,
        now=NOW,
        env={"SYNDICATE_NCAAF_SEGMENT_MARKETS": "h1"},
    )
    assert stats["enabled"] is True
    assert len(session.calls) == 2, "capture is ON but no per-event call went out"
    assert len(payloads) == 2
    assert stats["ok_events"] == 2


# --------------------------------------------------------------------------
# 2. BILLING. The regions split, the market count, the credit arithmetic.
# --------------------------------------------------------------------------


def test_segment_regions_are_not_widened_by_the_shared_knob():
    """`eu,us_ex` must NOT reach a per-event call.

    MLB obeys this by handing `_fetch_live_event_odds` the raw `regions` while
    widening only the bulk slate call. A regression here is invisible in every
    behavioural test -- the rows look identical -- and shows up only as a 3x
    quota burn days later.
    """
    session = _Session()
    sof.fetch_event_segments(
        api_key="k",
        sport="ncaaf",
        sport_key="americanfootball_ncaaf",
        base_url="https://api.the-odds-api.com/v4",
        events=[_event("e1", 60)],
        session=session,
        now=NOW,
        env={
            "SYNDICATE_NCAAF_SEGMENT_MARKETS": "h1",
            # The shared knob, set exactly as production sets it.
            "SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS": "eu,us_ex",
        },
    )
    assert session.calls[0]["params"]["regions"] == "us"


def test_default_bases_exclude_alternates():
    """Alternates were ~60% of the NFL preseason segment rows, triple the bill,
    and `period_lines.py` filters them straight back out."""
    market_map = sof.segment_markets_for("ncaaf", env={"SYNDICATE_NCAAF_SEGMENT_MARKETS": "h1"})
    assert set(market_map) == {"h2h_h1", "spreads_h1", "totals_h1"}
    assert not any(key.startswith("alternate_") for key in market_map)


def test_estimated_credits_is_markets_times_regions_times_events():
    assert sof.estimated_credits(12, 3, "us") == 36
    assert sof.estimated_credits(12, 3, "us,eu,us_ex") == 108


def test_configured_segments_drops_unknown_tokens_rather_than_guessing():
    env = {"SYNDICATE_NCAAF_SEGMENT_MARKETS": "h1,first5,p1"}
    # first5 is MLB's, p1 is NHL's. Neither is declared for ncaaf.
    assert sof.configured_segments("ncaaf", env=env) == ("h1",)
    # And a value of nothing-but-unknowns stays OFF rather than falling back.
    assert sof.configured_segments("ncaaf", env={"SYNDICATE_NCAAF_SEGMENT_MARKETS": "first5"}) == ()


def test_all_expands_to_the_sports_declared_segments():
    segments = set(sof.configured_segments("ncaaf", env={"SYNDICATE_NCAAF_SEGMENT_MARKETS": "all"}))
    assert segments == {"q1", "q2", "q3", "q4", "h1", "h2"}


# --------------------------------------------------------------------------
# 3. SCOPING. This is what makes the live tier affordable.
# --------------------------------------------------------------------------


def test_window_admits_pregame_and_live_and_excludes_the_rest():
    events = [
        _event("pregame_in", 60),        # kicks off in 1h  -> pregame tier
        _event("pregame_edge", 359),     # 5h59m out        -> in (6h window)
        _event("pregame_out", 400),      # 6h40m out        -> out
        _event("live_in", -30),          # 30m in           -> live tier
        _event("live_edge", -104),       # 1h44m in         -> in (1h45 window)
        _event("halftime_passed", -140), # 2h20m in         -> out, h1 is settled
    ]
    scoped, stats = sof.events_in_window(events, sport="ncaaf", now=NOW, env={})
    assert [e["id"] for e in scoped] == sorted(
        ["pregame_in", "pregame_edge", "live_in", "live_edge"],
        key=lambda i: {"live_in": 30, "pregame_in": 60, "live_edge": 104, "pregame_edge": 359}[i],
    )
    assert stats["pregame"] == 2
    assert stats["live"] == 2
    assert stats["out_of_window"] == 2


def test_event_without_a_commence_time_is_excluded_and_counted():
    """An unknown must not default to the permissive branch. Including it would
    mean paying for a call whose tier nobody can name."""
    scoped, stats = sof.events_in_window(
        [{"id": "no_time"}, _event("ok", 60)], sport="ncaaf", now=NOW, env={}
    )
    assert [e["id"] for e in scoped] == ["ok"]
    assert stats["no_commence_time"] == 1


def test_cap_trips_and_keeps_the_events_nearest_kickoff():
    events = [_event(f"e{i}", i * 10) for i in range(1, 11)]
    scoped, stats = sof.events_in_window(
        events, sport="ncaaf", now=NOW, env={"SYNDICATE_NCAAF_SEGMENT_MAX_EVENTS": "3"}
    )
    assert [e["id"] for e in scoped] == ["e1", "e2", "e3"]
    assert stats["capped"] == 7


def test_live_window_is_the_h1_markets_life_not_the_games():
    """A first-half line is delisted at halftime. The default therefore has to
    be shorter than a game, or every post-halftime sweep buys nothing."""
    _, stats = sof.events_in_window([], sport="ncaaf", now=NOW, env={})
    assert stats["live_window_seconds"] == 105 * 60
    assert stats["live_window_seconds"] < 210 * 60


# --------------------------------------------------------------------------
# 4. TAGGING. A segment price must never be stored as a full-game line.
# --------------------------------------------------------------------------


def test_union_map_tags_segment_rows_and_leaves_full_game_rows_alone():
    from syndicate.features.shared.odds_book_quotes import quote_rows_from_oddsapi_events

    module = _ncaaf_module()
    market_map = sof.merged_market_map(
        module._market_map(), "ncaaf", env={"SYNDICATE_NCAAF_SEGMENT_MARKETS": "h1"}
    )
    payload = [
        {
            "id": "e1",
            "commence_time": "2026-09-05T23:00:00Z",
            "home_team": "Home U",
            "away_team": "Away U",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {"key": "totals", "outcomes": [{"name": "Over", "point": 55.5, "price": -110}]},
                        {"key": "totals_h1", "outcomes": [{"name": "Over", "point": 28.5, "price": -105}]},
                        # Not requested; must be dropped, not mis-tagged.
                        {"key": "totals_q1", "outcomes": [{"name": "Over", "point": 14.5, "price": -115}]},
                    ],
                }
            ],
        }
    ]
    rows = quote_rows_from_oddsapi_events(payload, market_map=market_map)
    by_segment = {(r["segment"], r["market"], r["line"]) for r in rows}
    assert ("full", "totals", 55.5) in by_segment
    assert ("h1", "totals", 28.5) in by_segment
    assert not any(seg == "q1" for seg, _, _ in by_segment)
    # And the h1 row is NOT stored as a full-game line, which is the whole point.
    assert ("full", "totals", 28.5) not in by_segment


def test_bulk_market_map_still_carries_no_segment_key():
    """The bulk endpoint 422s INVALID_MARKET on a segment key, and that does not
    merely waste a credit -- it kills the full-game capture on the same call.
    Nine days of soccer capture were lost to exactly this."""
    module = _ncaaf_module()
    assert set(module._market_map()) == {"h2h", "spreads", "totals"}


def test_append_quotes_with_no_segment_payloads_is_the_previous_behaviour():
    """With capture off, the union map IS the full-game map."""
    module = _ncaaf_module()
    assert sof.merged_market_map(module._market_map(), "ncaaf", env={}) == module._market_map()


# --------------------------------------------------------------------------
# 5. COST ATTRIBUTION. The bucket the cadence decisions are read from.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market,expected",
    [
        ("totals_h1", "segment"),
        ("spreads_q1", "segment"),
        ("h2h_h2", "segment"),
        ("totals_p1", "segment"),
        ("totals_1st_5_innings", "segment"),
        ("alternate_totals_h1", "alternate"),
        ("totals", "full_game"),
        ("player_pass_tds", "props"),
    ],
)
def test_market_family_recognises_football_and_hockey_segments(market, expected):
    """`_market_family` knew only MLB's `_1st_*` spelling, so every `_q1`/`_h1`
    key billed into `other` -- the one bucket that is not read as a segment
    cost. The `segment` family is 35% of all platform burn."""
    from syndicate.features.shared.oddsapi_quota import _market_family

    assert _market_family(market) == expected
