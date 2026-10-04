"""Stale-quote sample + bettable reprice ages (lane `layer2-stale-quote-sample`, 2026-10-04)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared.layer2_board import build_layer2_rows, select_shortlist

_NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS"):
            monkeypatch.delenv(key, raising=False)


def _grid_row(best_book, best_price, cells):
    return {
        "sport": "mlb", "kind": "game", "event_id": "e1", "market": "totals", "segment": "full",
        "line": 8.5, "player_name": None, "home_team": "H", "away_team": "A",
        "commence_time": "2026-10-04T20:00:00Z", "sides": ["over", "under"], "books_quoting": 3,
        "game": {"state": "pregame"},
        "best": {
            "over": {"price": best_price, "bookmaker": best_book, "age_seconds": 50000.0, "seen_age_seconds": 40000.0, "books_quoting": 3},
            "under": {"price": -110, "bookmaker": "draftkings", "age_seconds": 100.0, "seen_age_seconds": 60.0, "books_quoting": 3},
        },
        "cells": cells,
    }


def test_reachability_a_repriced_row_carries_its_bettable_books_ages():
    """The best 'over' price is at a stale non-bettable book; the row is repriced
    to DraftKings and must carry DraftKings' ages, not the stale book's."""
    cells = {
        "stalebook": {"over": {"price": 120, "line": 8.5, "age_seconds": 50000.0, "seen_age_seconds": 40000.0}},
        "draftkings": {
            "over": {"price": -105, "line": 8.5, "age_seconds": 900.0, "seen_age_seconds": 120.0},
            "under": {"price": -110, "line": 8.5, "age_seconds": 100.0, "seen_age_seconds": 60.0},
        },
    }
    result = build_layer2_rows([_grid_row("stalebook", 120, cells)])
    over = next(r for r in result["opportunities"] if r["side"] == "over")
    assert over["quote"]["bookmaker"] == "draftkings" and over["quote"]["price"] == -105
    assert over["quote"]["quote_seen_age_seconds"] == 120.0, "the bettable book's look, not the stale best's"
    assert over["quote"]["book_age_seconds"] == 900.0
    assert result["repriced_to_bettable"] >= 1


def test_an_unrepriced_row_keeps_its_best_books_ages():
    cells = {"draftkings": {
        "over": {"price": 120, "line": 8.5, "age_seconds": 50000.0, "seen_age_seconds": 40000.0},
        "under": {"price": -110, "line": 8.5, "age_seconds": 100.0, "seen_age_seconds": 60.0},
    }}
    result = build_layer2_rows([_grid_row("draftkings", 120, cells)])
    over = next(r for r in result["opportunities"] if r["side"] == "over")
    assert over["quote"]["quote_seen_age_seconds"] == 40000.0


def _row(*, sport="nhl", event="e1", line=5.5, seen, market="totals"):
    return {
        "sport": sport, "kind": "game", "event_id": event, "market": market, "segment": "full",
        "side": "over", "line": line, "ev_pct": 1.0, "league": "nhl",
        "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "quote": {"quote_seen_age_seconds": seen, "book_age_seconds": seen, "bookmaker": "fanduel",
                  "best_any_book": {"bookmaker": "betus", "price": 120}},
        "score": {"score": 1.0},
    }


def test_stale_rows_are_sampled_with_their_origin_and_superseded_ones_are_not():
    rows = [_row(event=f"e{i}", seen=7200.0) for i in range(3)]
    rows += [_row(event="s", line=5.5, seen=7200.0), _row(event="s", line=6.5, seen=300.0)]  # superseded
    out = select_shortlist(rows, now=_NOW)
    sample = out["rows_stale_quote_sample"]
    assert out["rows_stale_quote"] == 3 and out["rows_superseded_line"] == 1
    assert len(sample) == 3 and {s["event_id"] for s in sample} == {"e0", "e1", "e2"}
    first = sample[0]
    assert first["gate_age_seconds"] == 7200.0 and first["quote_bookmaker"] == "fanduel"
    assert first["best_any_book"] == "betus" and first["market"] == "totals" and "row_keys" in first


def test_the_sample_is_bounded_per_sport():
    rows = [_row(event=f"n{i}", seen=7200.0) for i in range(15)]
    rows += [_row(sport="wnba", event=f"w{i}", seen=7200.0) for i in range(3)]
    sample = select_shortlist(rows, now=_NOW)["rows_stale_quote_sample"]
    by = {}
    for s in sample:
        by[s["sport"]] = by.get(s["sport"], 0) + 1
    assert by == {"nhl": 10, "wnba": 3}
