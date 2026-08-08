"""L2-A IS the main board: the swap, and the guard on it.

The legacy pool carried 229 game + 18 prop rows against Layer 1's 2,726 priced
instances -- starved, not stale. Measured 2026-08-08 on the first production
L2-A build: 239 rows selected from 8,277 opportunities across mlb/wnba/soccer,
while the board itself was serving candidate_count=0 for MLB during a live
13-game slate.

The swap happens at ONE choke point (`_hydrate_board_response_payload`), which
every board response already passes through. Per-endpoint swaps would be the
same rule written several times -- what #244 cost and #245 removed.
"""

from __future__ import annotations

import pytest

from syndicate.blueprints import intelligence as bp


def _l2_row(sport="mlb", side="home", player=None, price=-115, ev=4.2, score=4.1):
    return {
        "sport": sport,
        "kind": "prop" if player else "game",
        "market": "batter_hits" if player else "h2h",
        "segment": "full",
        "line": 0.5 if player else None,
        "player_name": player,
        "side": side,
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "event_id": "823349",
        "commence_time": "2026-08-08T23:05:00Z",
        "ev_pct": ev,
        "board_lane": "opportunity",
        "quote": {"price": price, "bookmaker": "draftkings", "books_quoting": 7},
        "score": {"score": score, "ev_component": ev},
    }


@pytest.fixture
def shortlist(monkeypatch):
    store = {"rows": []}

    def _read(date):
        # The worker builds cards and persists them; web only reads and slices.
        # Building them here mirrors what build_layer2_shortlist writes.
        from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

        return {"rows": store["rows"], "cards": layer2_rows_to_board_cards(store["rows"])}

    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", _read)
    return store


def test_layer2_rows_become_the_board(shortlist):
    shortlist["rows"] = [_l2_row(player="Aaron Judge"), _l2_row()]
    out = bp._hydrate_board_response_payload({"selected_date": "2026-08-08", "sport": "mlb"})

    assert out["board_source"] == "layer2_shortlist"
    assert out["candidate_count"] == 2
    assert len(out["top_opportunities"]) == 2
    assert len(out["recommendations"]) == 2


def test_a_game_row_shows_the_team_not_the_literal_word_candidate(shortlist):
    """The card normaliser falls back to the string "candidate" when nothing
    identifies the pick, so every game line would render identically."""
    shortlist["rows"] = [_l2_row(side="home")]
    out = bp._hydrate_board_response_payload({"selected_date": "2026-08-08", "sport": "mlb"})
    assert out["top_opportunities"][0]["selection"] == "New York Yankees"


def test_a_prop_row_shows_the_player(shortlist):
    shortlist["rows"] = [_l2_row(player="Aaron Judge")]
    out = bp._hydrate_board_response_payload({"selected_date": "2026-08-08", "sport": "mlb"})
    assert out["top_opportunities"][0]["selection"] == "Aaron Judge"


def test_the_recommended_price_survives_to_the_card(shortlist):
    """Settlement grades against the price the shortlist ranked. If the card
    carries a different number, the board recommends one bet and grades another."""
    shortlist["rows"] = [_l2_row(price=-137)]
    card = bp._hydrate_board_response_payload({"selected_date": "2026-08-08", "sport": "mlb"})["top_opportunities"][0]
    assert card["odds"] == -137
    assert card["quote"]["price"] == -137


def test_an_empty_shortlist_leaves_the_existing_board_untouched(shortlist):
    """A new ranker must not be able to blank a board that works."""
    shortlist["rows"] = []
    existing = {
        "selected_date": "2026-08-08",
        "sport": "mlb",
        "top_opportunities": [{"selection": "legacy row"}],
        "recommendations": [{"selection": "legacy row"}],
        "candidate_count": 1,
    }
    out = bp._hydrate_board_response_payload(existing)

    # Identity, NOT exact dict equality: opportunity_gate has annotated every
    # served row since #245 (board_lane/market_state/gate), so a row that came
    # through untouched still gains those keys. Asserting equality here failed
    # against correct behaviour.
    assert [row["selection"] for row in out["top_opportunities"]] == ["legacy row"]
    assert out.get("board_source") is None
    assert out["candidate_count"] == 1


def test_an_unreadable_shortlist_leaves_the_board_untouched(monkeypatch):
    def _boom(_date):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", _boom)
    existing = {"selected_date": "2026-08-08", "sport": "mlb", "top_opportunities": [{"selection": "legacy"}]}
    out = bp._hydrate_board_response_payload(existing)
    assert [row["selection"] for row in out["top_opportunities"]] == ["legacy"]
    assert out.get("board_source") is None


def test_sport_scoped_requests_only_get_that_sport(shortlist):
    """Without this a sport-scoped board shows every sport's rows."""
    shortlist["rows"] = [_l2_row(sport="mlb"), _l2_row(sport="wnba"), _l2_row(sport="soccer")]
    out = bp._hydrate_board_response_payload({"selected_date": "2026-08-08", "sport": "wnba"})

    assert out["candidate_count"] == 1
    assert out["top_opportunities"][0]["sport"] == "wnba"


def test_all_returns_every_sport(shortlist):
    shortlist["rows"] = [_l2_row(sport="mlb"), _l2_row(sport="wnba")]
    out = bp._hydrate_board_response_payload({"selected_date": "2026-08-08", "sport": "all"})
    assert out["candidate_count"] == 2


def test_translated_cards_survive_the_real_board_contract():
    """Proven against the actual normaliser, not a stand-in: the board contract
    is what every downstream surface reads."""
    from syndicate.features.intelligence_board import build_intelligence_board_contract
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    cards = layer2_rows_to_board_cards([_l2_row(player="Aaron Judge"), _l2_row()])
    contract = build_intelligence_board_contract({"recommendations": cards})
    produced = contract.get("cards") or []

    assert len(produced) == 2
    assert {c.get("selection") for c in produced} == {"Aaron Judge", "New York Yankees"}
    assert all(c.get("odds") is not None for c in produced)


def test_web_does_not_transform_only_reads_and_slices():
    """ARTIFACT-BASED. The web service reads precomputed artifacts; it does not
    compute. An earlier version mapped rows->cards per request, which both put
    compute in the request path AND meant the persisted artifact was not what
    the board displayed -- so what was recommended was recorded nowhere."""
    import inspect

    from syndicate.blueprints import intelligence as blueprint

    source = inspect.getsource(blueprint._layer2_board_cards)
    assert "layer2_rows_to_board_cards" not in source, "web is transforming rows again"
    assert '"cards"' in source or "'cards'" in source, "web is not reading the persisted cards"


def test_the_worker_persists_the_cards():
    """The other half: if the worker stops writing them, web reads nothing and
    the board silently falls back to the legacy pool."""
    import inspect

    from pipeline import layer2_shortlist

    source = inspect.getsource(layer2_shortlist.build_layer2_shortlist)
    assert "layer2_rows_to_board_cards" in source
    assert 'shortlist["cards"]' in source
