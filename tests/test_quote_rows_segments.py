"""`#343` — the shared row builder derives segment per MARKET, not per call.

Every sport except MLB requested only h2h/spreads/totals and passed the default
`segment="full"`, so interval capture existed for exactly one sport. The OddsAPI
key already names the interval (`totals_q1`), so the segment is derivable per
market once the caller passes the shared map.
"""

from __future__ import annotations

from syndicate.features.shared.market_segments import full_game_market_keys, segment_market_keys
from syndicate.features.shared.odds_book_quotes import quote_rows_from_oddsapi_events


def _event(*market_keys):
    return {
        "id": "evt1",
        "home_team": "Las Vegas Aces",
        "away_team": "New York Liberty",
        "commence_time": "2026-08-10T23:00:00Z",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [
                {"key": k, "outcomes": [
                    {"name": "Over", "point": 42.5, "price": -110},
                    {"name": "Under", "point": 42.5, "price": -110},
                ]} for k in market_keys
            ],
        }],
    }


def test_quarter_and_half_markets_are_tagged_with_their_own_segment():
    keys = {**full_game_market_keys(), **segment_market_keys("wnba")}
    rows = quote_rows_from_oddsapi_events([_event("totals", "totals_q1", "totals_h2")], market_map=keys)
    got = {(r["market"], r["segment"]) for r in rows}
    assert ("totals", "full") in got
    assert ("totals", "q1") in got
    assert ("totals", "h2") in got


def test_a_string_valued_map_still_uses_the_call_level_segment():
    # Backward compatibility: existing callers pass {raw: name} and rely on the
    # `segment=` argument.
    rows = quote_rows_from_oddsapi_events(
        [_event("totals")], market_map={"totals": "totals"}, segment="full"
    )
    assert {r["segment"] for r in rows} == {"full"}


def test_a_tuple_entry_never_falls_back_to_the_call_level_segment():
    # A caller that requests totals_q1 and tags it `full` shows a first-quarter
    # total as a full-game line -- worse than never asking. So the tuple's
    # segment must win even when `segment=` says otherwise.
    rows = quote_rows_from_oddsapi_events(
        [_event("totals_q1")], market_map={"totals_q1": ("q1", "totals")}, segment="full"
    )
    assert {r["segment"] for r in rows} == {"q1"}


def test_mlb_inning_segments_flow_through_the_same_path():
    keys = segment_market_keys("mlb")
    rows = quote_rows_from_oddsapi_events([_event("totals_1st_5_innings")], market_map=keys)
    assert {(r["market"], r["segment"]) for r in rows} == {("totals", "first5")}
