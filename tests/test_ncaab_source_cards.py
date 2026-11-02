"""`/ncaab/cards` on the WNBA parity page (user 2026-11-02: "the ncaab page needs a
complete overhaul to match nba/wnba"). NCAAB has no model, so the payload is the
D1 slate plus the market's consensus, and the page runs in its no-model mode.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.ncaab import slate
from syndicate.features.ncaab import source_cards


def _row(market, line, consensus, books=("draftkings", "fanduel")):
    return {"kind": "game", "segment": "full", "market": market, "line": line,
            "home_team": "Murray St Racers", "away_team": "Tennessee St Tigers",
            "consensus": consensus, "books": list(books)}


GAME = {
    "event_id": "401", "start_time_utc": "2026-11-02T16:30Z", "neutral_site": True, "venue": "Arena",
    "away": {"name": "Tennessee State Tigers", "abbr": "TNST", "logo": "https://logo/a.png", "score": None},
    "home": {"name": "Murray State Racers", "abbr": "MUR", "logo": "https://logo/h.png", "score": None},
    "live_state": {"in_progress": False, "final": False, "status": "11/2 - 10:30 AM", "away_linescores": [], "home_linescores": []},
}


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    source_cards._grid_cache.clear()
    grid = tmp_path / "ncaab_source" / "data" / "book_grid"
    grid.mkdir(parents=True)
    rows = [
        # Grid spread lines are in the AWAY frame: away +9 is home -9.
        _row("spreads", "9.0", {"away": -110, "home": -110}),
        _row("spreads", "12.5", {"away": -180, "home": 150}),  # alt line, far from even
        _row("totals", "165.0", {"over": -110, "under": -110}, books=("draftkings", "fanduel", "betmgm")),
        _row("h2h", None, {"home": -468, "away": 354}),
        {**_row("totals", "80.5", {"over": -110, "under": -110}), "segment": "h1"},  # a half line stays out
    ]
    (grid / "book_grid_2026-11-02.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    monkeypatch.setattr(slate, "slate_games", lambda d, refresh=None, league="ncaab": [dict(GAME)])
    monkeypatch.setattr(source_cards, "slate_games", lambda d, league="ncaab": [dict(GAME)])
    return tmp_path


def test_market_main_line_and_no_vig_win_probability(data_root):
    card = source_cards.build_ncaab_source_cards_payload("2026-11-02")["games"][0]
    betting = card["betting"]
    assert (betting["home_spread"], betting["total"]) == (-9.0, 165.0)
    assert (betting["home_ml"], betting["away_ml"]) == (-468, 354)
    assert betting["p_home_win"] + betting["p_away_win"] == pytest.approx(1.0)
    assert 0.77 < betting["p_home_win"] < 0.80
    assert betting["books"] == 3
    # Market-implied team totals, not a model: (165 + -9) / 2 and (165 - -9) / 2.
    assert (card["sim"]["score"]["away_mean"], card["sim"]["score"]["home_mean"]) == (78.0, 87.0)


def test_card_carries_what_the_parity_page_keys_on(data_root):
    payload = source_cards.build_ncaab_source_cards_payload("2026-11-02")
    card = payload["games"][0]
    assert payload["board_contract"]["sport"] == "ncaab"
    assert (card["away_tri"], card["home_tri"], card["gameType"]) == ("TNST", "MUR", "NCAAB")
    assert card["sim"]["game_id"] == "401" and card["sim"]["players_loaded"] is True
    assert card["live_state"] is None  # pregame
    assert card["odds"]["commence_time"] == "2026-11-02T16:30Z"
    assert card["game_market_recommendations"] == [] and card["prop_recommendations"] == {"away": [], "home": []}


def test_a_started_game_carries_score_clock_and_halves(data_root, monkeypatch):
    live = {**GAME,
            "away": {**GAME["away"], "score": 41}, "home": {**GAME["home"], "score": 38},
            "live_state": {"in_progress": True, "final": False, "period": 2, "clock": "12:34", "status": "12:34 - 2nd Half",
                           "away_linescores": [35, 6], "home_linescores": [30, 8]}}
    monkeypatch.setattr(source_cards, "slate_games", lambda d, league="ncaab": [live])
    card = source_cards.build_ncaab_source_cards_payload("2026-11-02")["games"][0]
    assert card["live_state"]["in_progress"] is True
    assert (card["live_state"]["away_pts"], card["live_state"]["home_pts"]) == (41, 38)
    assert card["live_state"]["periods"] == [{"period": 1, "away": 35, "home": 30}, {"period": 2, "away": 6, "home": 8}]


def test_routes_serve_the_parity_page_in_no_model_mode(data_root):
    from syndicate.app import app

    client = app.test_client()
    page = client.get("/ncaab/cards?date=2026-11-02")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'data-cards-payload-path="/ncaab/api/source/cards"' in html
    assert "hasModel: false" in html and "/wnba/cards-parity.js" in html
    assert client.get("/ncaab?date=2026-11-02").status_code == 200
    api = client.get("/ncaab/api/source/cards?date=2026-11-02").get_json()
    assert [g["event_id"] for g in api["games"]] == ["401"]
    # The shared board stays reachable, as NBA keeps it.
    assert client.get("/ncaab/cards?date=2026-11-02&client=board").status_code == 200


def test_parity_js_defaults_stay_wnba():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "syndicate" / "static" / "wnba" / "cards-parity.js").read_text(encoding="utf-8")
    assert "{ key: 'wnba', liveLens: true, simDetail: true, hasModel: true }" in js
    assert "document.body?.dataset?.cardsApiBasePath || '/wnba/api'" in js
    # `Number(null) * 100` rendered a missing EV as "EV 0.0%".
    assert "ev: row.pick.ev == null ? null : Number(row.pick.ev) * 100" in js
