"""Layer 2 does not seat a basketball prop whose player is OUT on the injury feed.

Board rows are built from bookmaker quotes, so an OUT player's quote reached
Layer 2 and -- with no projection -- ranked on market EV alone.
`board_enrichment._flag_out_player_props` stamps `player_availability` (Layer 1
keeps the row, marked); `select_shortlist` leaves the line unseated, pre-bucket,
and counts it. A property of the line (the bet voids), not a market verdict, so
it fits the 2026-10-05 stop-market-withholding directive. Questionable and
doubtful players are never flagged upstream and stay priced.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.layer2_board import select_shortlist

_NOW = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)
_MEASURED = {"model_skill": {"status": "measured", "sample_games": 120}}


def _prop(player: str, sport: str = "wnba", **extra: object) -> dict:
    row = {
        "sport": sport,
        "kind": "prop",
        "market": "player_threes",
        "player_name": player,
        "side": "over",
        "event_id": f"evt-{player}",
        "commence_time": "2026-10-07T23:30:00Z",
        "ev_pct": 2.5,
        "model_edge_pct": 4.1,
        "projection": _MEASURED,
        "quote": {"price": 118, "fair_probability": 0.44, "fair_method": "consensus_no_vig", "books_quoting": 4},
        "score": {"score": 2.5, "value_pct": 2.5},
    }
    row.update(extra)
    return row


def _out(status: str = "OUT") -> dict:
    return {"player_availability": {"status": status, "reason": "player OUT on the injury feed"}}


def test_an_out_player_is_not_seated_and_is_counted():
    rows = [_prop("Allisha Gray", **_out()), _prop("Jewell Loyd"), _prop("Rhyne Howard")]
    result = select_shortlist(rows, now=_NOW)
    seated = {row.get("player_name") for row in result["rows"]}
    assert "Allisha Gray" not in seated
    assert {"Jewell Loyd", "Rhyne Howard"} <= seated
    assert result["rows_player_out_on_feed"] == 1
    assert result["rows_player_out_on_feed_by_sport"] == {"wnba": 1}


def test_off_is_not_on_the_same_row_seats_without_the_flag():
    # Reachability: identical row, flag removed -> seated. So the exclusion above
    # is this gate, not some other rule.
    result = select_shortlist([_prop("Allisha Gray"), _prop("Rhyne Howard")], now=_NOW)
    assert "Allisha Gray" in {row.get("player_name") for row in result["rows"]}
    assert result["rows_player_out_on_feed"] == 0
    assert result["rows_player_out_on_feed_by_sport"] == {}


def test_only_confirmed_out_statuses_gate():
    rows = [_prop("A One", **_out("SUSPENDED")), _prop("B Two", **_out("DOUBTFUL")), _prop("C Three")]
    result = select_shortlist(rows, now=_NOW)
    seated = {row.get("player_name") for row in result["rows"]}
    assert "A One" not in seated
    assert "B Two" in seated
    assert result["rows_player_out_on_feed"] == 1


def test_counted_per_sport():
    rows = [_prop("Gray", **_out()), _prop("Butler", sport="nba", **_out()), _prop("Howard")]
    result = select_shortlist(rows, now=_NOW)
    assert result["rows_player_out_on_feed_by_sport"] == {"nba": 1, "wnba": 1}


# ---------------------------------------------------------------------------
# END TO END, through the rebuild production uses (lane layer2-out-gate-reach).
#
# The tests above hand rows straight to select_shortlist. Production does not:
# build_layer2_rows rebuilds every candidate from _IDENTITY_FIELDS plus explicit
# fields, and until 2026-10-07 player_availability was not one of them -- so the
# gate was unreachable (fleet: 9 Allisha Gray rows flagged per WNBA build, served
# rows_player_out_on_feed 0). These go grid row -> build_layer2_rows ->
# select_shortlist, the path the fleet runs.
# ---------------------------------------------------------------------------

from syndicate.features.shared.layer2_board import build_layer2_rows


def _grid_prop(player: str, **extra: object) -> dict:
    row = {
        "sport": "wnba", "event_id": f"evt-{player}", "kind": "prop", "market": "player_threes", "segment": "full",
        "line": 1.5, "player_name": player, "home_team": "Atlanta Dream", "away_team": "New York Liberty",
        "commence_time": "2026-10-07T23:30:00Z", "sides": ["over", "under"], "books_quoting": 4,
        # THREE TWO-SIDED BOOKS, NOT AN EMPTY `cells`
        # `[2026-10-20, lane no-market-price-test-fallout]`.
        #
        # This was `"cells": {}` with only `best` populated. Since `dd499146`
        # that is exactly a `rows_no_market_price` row: `_resolve_fair` needs a
        # book quoting BOTH sides (`_two_sided_prices_by_book`), an empty
        # `cells` yields no fair, `ev` is guarded on `fair is not None`, and
        # `select_shortlist` then refuses a model edge with no market price. So
        # `opportunities` came back EMPTY and all five end-to-end tests read as
        # "nobody seated" -- the gate never ran at all, which is indistinguishable
        # from the gate working.
        #
        # Production props always carry book prices, so the refusal is right and
        # the fixture was unrealistic.
        #
        # THE PRICES ARE NOT ARBITRARY, and a first attempt at them failed. With
        # a SINGLE book's de-vig, `EV = fair x decimal - 1` reduces to
        # `1/S - 1` where `S` is that book's overround -- so betting a book's own
        # price against its own de-vig is ALWAYS minus the hold, and three
        # tightly-matched books gave `ev_pct -2.85` and
        # `rows_below_value_floor 4`. Value requires the best price to beat the
        # CONSENSUS, which is real price-shopping and is what these books now
        # describe: FanDuel is lopsided (over +118 against an expensive -140
        # under, so its own de-vig reads 0.440), while the other two are tight.
        # Median de-vigged `over` 0.474 against +118 (decimal 2.18) is about
        # +3.3% EV, which clears the value floor and seats the row -- and a
        # seated row is the precondition for these tests observing the gate at
        # all.
        "cells": {
            "fanduel": {"over": {"price": 118, "age_seconds": 30.0},
                        "under": {"price": -140, "age_seconds": 30.0}},
            "draftkings": {"over": {"price": 100, "age_seconds": 30.0},
                           "under": {"price": -120, "age_seconds": 30.0}},
            "betmgm": {"over": {"price": 102, "age_seconds": 30.0},
                       "under": {"price": -122, "age_seconds": 30.0}},
        },
        "best": {"over": {"price": 118, "bookmaker": "fanduel", "books_quoting": 4, "age_seconds": 30.0},
                 "under": {"price": -140, "bookmaker": "draftkings", "books_quoting": 4, "age_seconds": 30.0}},
        "projection": {"edge_vs_market_pct": 6.0, "model_skill": {"status": "measured", "sample_games": 120}},
        # SETTLED 2026-10-12 against a real payload: without `game`, build_layer2_rows
        # rebuilds both sides, scores them, and then opportunity_gate demotes every one
        # to `watchlist` -- so `opportunities` came back EMPTY and the five end-to-end
        # tests below asserted against empty sets for two days while reading as a
        # gate failure. 128 real prop rows from /api/board/book-grid give
        # by_lane {'opportunity': 186, 'dead': 36}, and of the ten keys a real row
        # carries that this fixture lacked, adding `game` ALONE flips it from
        # {'watchlist': 2} to {'opportunity': 2}. Shape copied from a real row
        # (2026_05_BUF_LA); only `state` is load-bearing here, the rest is realism.
        "game": {
            "game_key": "2026_10_NYL_ATL",
            "matchup": "NYL @ ATL",
            "state": "pregame",
            "start_time_utc": "2026-10-07T23:30:00+00:00",
            "home_score": None,
            "away_score": None,
            "status_token": "6:30P CT",
        },
    }
    row.update(extra)
    return row


def _seated_through_rebuild(grid: list[dict]) -> tuple[set, dict]:
    opportunities = build_layer2_rows([dict(r) for r in grid])["opportunities"]
    result = select_shortlist(opportunities, now=_NOW)
    return {row.get("player_name") for row in result["rows"]}, result


def test_the_flag_survives_build_layer2_rows():
    opportunities = build_layer2_rows([_grid_prop("Allisha Gray", **_out())])["opportunities"]
    assert opportunities, "fixture must produce candidates"
    assert all((row.get("player_availability") or {}).get("status") == "OUT" for row in opportunities)


def test_end_to_end_an_out_player_is_not_seated():
    seated, result = _seated_through_rebuild([_grid_prop("Allisha Gray", **_out()), _grid_prop("Rhyne Howard")])
    assert "Rhyne Howard" in seated
    assert "Allisha Gray" not in seated
    assert result["rows_player_out_on_feed"] >= 1


def test_end_to_end_off_is_not_on():
    # The same grid without the flag seats her -- so the exclusion above is the gate.
    seated, result = _seated_through_rebuild([_grid_prop("Allisha Gray"), _grid_prop("Rhyne Howard")])
    assert "Allisha Gray" in seated
    assert result["rows_player_out_on_feed"] == 0


# ---------------------------------------------------------------------------
# NAMED REFUSALS (lane layer2-out-gate-named). The counter alone said "4 rows
# gated" on 2026-10-07 and whose they were could only be inferred from the
# Layer 1 sweep log. The sample names them, bounded per sport like
# rows_stale_quote_sample.
# ---------------------------------------------------------------------------


def test_the_sample_names_the_gated_players():
    _, result = _seated_through_rebuild([_grid_prop("Allisha Gray", **_out()), _grid_prop("Rhyne Howard")])
    sample = result["rows_player_out_on_feed_sample"]
    assert {row["player_name"] for row in sample} == {"Allisha Gray"}
    first = sample[0]
    assert first["sport"] == "wnba" and first["market"] == "player_threes" and first["line"] == 1.5
    assert first["availability"]["status"] == "OUT"
    assert len(sample) == result["rows_player_out_on_feed"]


def test_the_sample_is_empty_when_nothing_is_gated():
    _, result = _seated_through_rebuild([_grid_prop("Allisha Gray"), _grid_prop("Rhyne Howard")])
    assert result["rows_player_out_on_feed_sample"] == []


def test_the_sample_is_capped_per_sport():
    from syndicate.features.shared import layer2_board as l2

    grid = [_grid_prop(f"Out Player {i}", **_out()) for i in range(l2._OUT_SAMPLE_PER_SPORT + 5)]
    _, result = _seated_through_rebuild(grid)
    assert result["rows_player_out_on_feed"] > l2._OUT_SAMPLE_PER_SPORT
    assert len(result["rows_player_out_on_feed_sample"]) == l2._OUT_SAMPLE_PER_SPORT
