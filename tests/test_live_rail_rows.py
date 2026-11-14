"""The games rail's live lines between whole-board polls: `/api/board/live-rail` (todo #803, lane
live-rail-fast-poll).

The page swaps these rows into the rail every ~15 s, so they must be the rows the board itself would serve for
the same overlay. Pinned: the endpoint's rows equal the board path's (`_merge_inplay_overlay` + the board
contract) for the same overlay, field by field on what the rail reads; props and non-live rows are not served;
rows are trimmed to the rail's fields; the off switch serves nothing (off != on); a failure never raises; and
the route serves the body uncached.
"""
from __future__ import annotations

import json
import os

import pytest

from pipeline import intelligence_state as st
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.shared import book_grid_artifact as bga
from syndicate.features.shared import live_rail_rows as lrr

DATE = "2026-11-14"
BUILT = "2026-11-14T21:20:15.000000+00:00"


def _game(event, market, side, line, *, segment="full", p=0.6, fair=0.5, age=40.0, state="live", kind="game",
          player=None):
    return {
        "sport": "ncaab", "sport_slug": "ncaab", "kind": kind, "candidate_type": kind, "event_id": event,
        "matchup": "Coppin St Eagles @ South Florida Bulls", "home_team": "South Florida Bulls",
        "away_team": "Coppin St Eagles", "home_key": "south florida", "away_key": "coppin st",
        "commence_time": "2026-11-14T18:00:00Z", "market": market, "segment": segment, "side": side,
        "line": line, "odds": -110, "market_state": state, "live_model_probability": p, "live_aware": True,
        "model_edge_pct": round((p - fair) * 100, 2), "book_age_seconds": age, "player_name": player,
        "quote": {"fair_probability": fair, "books_quoting": 8, "book_age_seconds": age, "bookmaker": "fanduel",
                  "quote_seen_age_seconds": 5.0, "price": -110},
        "price_grid_generated_at": BUILT, "source": "layer2_inplay_overlay", "inplay_overlay": True,
        "team": "South Florida Bulls" if side == "home" else ("Coppin St Eagles" if side == "away" else None),
        "sim_ladder": [{"line": line, "p": p}], "detail": "a field the rail never reads",
    }


OVERLAY = [
    _game("ev1", "totals", "over", 152.5, p=0.64),
    _game("ev1", "totals", "under", 152.5, p=0.36),
    _game("ev1", "spreads", "home", -27.5, p=0.54),
    _game("ev1", "spreads", "away", 27.5, p=0.46),
    _game("ev1", "totals", "under", 74.5, segment="h1", p=0.6, fair=0.515, age=118.9),
    _game("ev2", "h2h", "home", None, p=0.9, fair=0.85, age=13.0),
    # An overlay card with the age only on its quote: the board path's per-card backfill lifts it to the row,
    # which is the age the rail reads first -- so the endpoint must run the same per-card steps.
    {k: v for k, v in _game("ev2", "totals", "over", 141.5, p=0.58, age=22.0).items() if k != "book_age_seconds"},
    _game("ev3", "player_points", "over", 18.5, kind="prop", player="Some Player"),   # a prop: not served
    _game("ev4", "totals", "over", 140.5, state="pregame"),                           # not live: not served
]


@pytest.fixture(autouse=True)
def _overlay(monkeypatch):
    monkeypatch.delenv(lrr.FLAG, raising=False)
    monkeypatch.setattr(bga, "inplay_overlay_cards",
                        lambda date, **_: ([dict(c) for c in OVERLAY], {"sports": {"ncaab": len(OVERLAY)}, "newest_written_at": "2026-11-14T21:20:20Z"}))


def _board_path_rows():
    cards: list = []
    st._merge_inplay_overlay(cards, DATE, start=0)
    contract = build_intelligence_board_contract({"recommendations": cards})
    promoted = st._promote_board_contract_cards({"board_contract": contract})
    return [lrr.trim_row(r) for r in promoted.get("top_opportunities") or [] if lrr._is_live_game_row(r)]


def _key(row):
    return (row.get("event_id"), row.get("market"), row.get("segment"), row.get("side"), str(row.get("line")))


def test_the_endpoint_serves_the_board_paths_rows_for_the_same_overlay():
    body = lrr.live_rail_payload(DATE)
    board = _board_path_rows()
    assert body["ok"] is True and body["enabled"] is True
    assert body["rows"], "the overlay's live game rows must be served"
    assert sorted(map(_key, body["rows"])) == sorted(map(_key, board))
    by_key = {_key(r): r for r in board}
    for row in body["rows"]:
        assert row == by_key[_key(row)], _key(row)


def test_props_and_non_live_rows_are_not_served():
    rows = lrr.live_rail_payload(DATE)["rows"]
    assert {r["event_id"] for r in rows} == {"ev1", "ev2"}
    assert all(r["kind"] == "game" and r["market_state"] == "live" for r in rows)


def test_rows_carry_only_the_rails_fields():
    rows = lrr.live_rail_payload(DATE)["rows"]
    for row in rows:
        assert set(row) <= set(lrr.ROW_FIELDS) | {"quote"}
        assert set(row.get("quote") or {}) <= set(lrr.QUOTE_FIELDS)
        assert "sim_ladder" not in row and "detail" not in row
    lifted = next(r for r in rows if r["event_id"] == "ev2" and r["market"] == "totals")
    assert lifted["book_age_seconds"] == 22.0, "the board's per-card backfill lifts the quote's age to the row"
    h1 = next(r for r in rows if r["segment"] == "h1")
    assert h1["quote"]["fair_probability"] == 0.515 and h1["book_age_seconds"] == 118.9
    assert h1["price_grid_generated_at"] == BUILT and h1["live_model_probability"] == 0.6


def test_the_body_says_how_fresh_the_overlay_is_and_how_long_it_took():
    body = lrr.live_rail_payload(DATE)
    assert body["newest_written_at"] == "2026-11-14T21:20:20Z" and body["sports"] == {"ncaab": len(OVERLAY)}
    assert isinstance(body["elapsed_ms"], int) and body["date"] == DATE


def test_the_off_switch_serves_nothing(monkeypatch):
    """Reachability: off != on."""
    assert lrr.live_rail_payload(DATE)["rows"]
    monkeypatch.setenv(lrr.FLAG, "off")
    body = lrr.live_rail_payload(DATE)
    assert body["enabled"] is False and body["rows"] == []


def test_a_failure_returns_no_rows_and_the_reason(monkeypatch):
    monkeypatch.setattr(bga, "inplay_overlay_cards", lambda date, **_: (_ for _ in ()).throw(OSError("disk")))
    body = lrr.live_rail_payload(DATE)
    assert body["ok"] is False and body["error"] == "OSError" and body["rows"] == []


def test_no_overlay_serves_no_rows(monkeypatch):
    monkeypatch.setattr(bga, "inplay_overlay_cards", lambda date, **_: ([], {"sports": {}, "newest_written_at": None}))
    body = lrr.live_rail_payload(DATE)
    assert body["ok"] is True and body["rows"] == []


def test_the_route_serves_it_uncached():
    from flask import Flask

    from syndicate.blueprints import intelligence as bp

    app = Flask(__name__)
    app.register_blueprint(bp.intelligence_bp)
    resp = app.test_client().get(f"/api/board/live-rail?date={DATE}")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["date"] == DATE and {r["event_id"] for r in body["rows"]} == {"ev1", "ev2"}
    assert len(json.dumps(body)) < 20_000
