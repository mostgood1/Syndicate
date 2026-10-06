"""A book that stopped quoting must not win a Layer 2 row on its last price.

Lane `layer2-stale-book-pick` (2026-10-06). Measured on the fleet board that day: 8 of 10
sampled NHL stale-quote rows were one STALE bettable book winning `best_bettable` on price
(betrivers 23.8 h old against 9 books at 0.7 h) while other books quoted the same line
fresh, so the row carried the stale age and the 1h gate hid it.
"""
from __future__ import annotations

from syndicate.features.shared.layer2_board import build_layer2_rows


def _row(*, stale_price=130, fresh_price=-105, fresh_seen=600.0, stale_seen=86_000.0):
    return {
        "sport": "nhl",
        "kind": "game",
        "event_id": "evt-nhl-1",
        "market": "spreads",
        "segment": "full",
        "line": -1.5,
        "player_name": None,
        "home_team": "Montreal Canadiens",
        "away_team": "Toronto Maple Leafs",
        "commence_time": "2026-10-06T23:00:00Z",
        "sides": ["home", "away"],
        "books_quoting": 2,
        "game": {"state": "pregame", "status_token": "6:00P CT"},
        "best": {
            "home": {"price": stale_price, "bookmaker": "betrivers", "age_seconds": stale_seen,
                     "seen_age_seconds": stale_seen, "books_quoting": 2},
            "away": {"price": -150, "bookmaker": "draftkings", "age_seconds": fresh_seen,
                     "seen_age_seconds": fresh_seen, "books_quoting": 2},
        },
        "cells": {
            "betrivers": {"home": {"price": stale_price, "age_seconds": stale_seen, "seen_age_seconds": stale_seen},
                          "away": {"price": -160, "age_seconds": stale_seen, "seen_age_seconds": stale_seen}},
            "draftkings": {"home": {"price": fresh_price, "age_seconds": fresh_seen, "seen_age_seconds": fresh_seen},
                           "away": {"price": -150, "age_seconds": fresh_seen, "seen_age_seconds": fresh_seen}},
        },
    }


def _home(result):
    return next(c for c in result["opportunities"] if c["side"] == "home")


def test_a_fresh_bettable_book_beats_a_stale_better_price():
    result = build_layer2_rows([_row()])
    home = _home(result)
    assert home["quote"]["bookmaker"] == "draftkings"
    assert home["quote"]["quote_seen_age_seconds"] == 600.0
    assert result["stale_book_skipped"] == 1
    assert result["stale_book_skipped_by_sport"] == {"nhl": 1}


def test_off_is_not_on_a_fresh_best_price_is_untouched():
    """Reachability: same row with the generous book FRESH -- it wins as before."""
    result = build_layer2_rows([_row(stale_seen=300.0)])
    assert _home(result)["quote"]["bookmaker"] == "betrivers"
    assert result["stale_book_skipped"] == 0


def test_when_no_book_is_fresh_the_pick_is_unchanged():
    """Relative, not absolute: nothing fresh to prefer, so the age gate judges the line."""
    result = build_layer2_rows([_row(fresh_seen=50_000.0)])
    assert _home(result)["quote"]["bookmaker"] == "betrivers"
    assert result["stale_book_skipped"] == 0


def _live(row):
    row["game"] = {"state": "live", "status_token": "Q1 12:57"}
    return row


def test_in_play_a_book_frozen_past_the_live_clock_loses_to_a_fresh_one():
    """In play the limit is the 900 s book clock, not the pregame hour: a 1,286 s-old
    book (well under 1 h) still loses to a fresh one quoting the same line."""
    result = build_layer2_rows([_live(_row(stale_seen=1286.0, fresh_seen=40.0))])
    assert _home(result)["quote"]["bookmaker"] == "draftkings"
    assert result["stale_book_skipped"] == 1


def test_in_play_a_fresh_best_price_is_untouched():
    result = build_layer2_rows([_live(_row(stale_seen=60.0, fresh_seen=40.0))])
    assert _home(result)["quote"]["bookmaker"] == "betrivers"
    assert result["stale_book_skipped"] == 0
