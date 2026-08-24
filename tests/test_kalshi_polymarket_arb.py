"""Kalshi vs Polymarket US moneyline arb detection.

The Kalshi-side fixtures reuse the SAME resolution path
`tests/test_kalshi_board_join.py::test_a_club_alias_still_matches_the_game`
already proves works (`TEX`/`CHW` through `team_aliases`, blob `TEXCWS`) --
not reinvented here, so a real alias-map regression shows up in both places
rather than only one.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_polymarket_arb as mod


@pytest.fixture(autouse=True)
def _register_test_series(monkeypatch):
    from syndicate.features.shared import kalshi_catalogue

    monkeypatch.setitem(kalshi_catalogue.SERIES_SPORT, "KXTESTML", "mlb")
    yield


def _kalshi_moneyline_market(*, subject="TEX", yes_american=-150, no_american=130, ticker=None):
    return {
        "series": "KXTESTML",
        "ticker": ticker or "KXTESTML-26AUG24TEXCWS-T1",
        "event_ticker": "KXTESTML-26AUG24TEXCWS",
        "title": f"{subject} wins?",
        "yes_american": yes_american,
        "no_american": no_american,
    }


def _board_rows(*, away="TEX", home="CHW", event_id="e1", sport="mlb"):
    return [{"sport": sport, "event_id": event_id, "home_team": home, "away_team": away}]


def _polymarket_row(*, teams=("Rangers", "White Sox"), prices=("0.42", "0.58"), game_date="2026-08-24", market_id="pm1"):
    return {
        "id": market_id,
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
        "outcomes": list(teams),
        "outcomePrices": list(prices),
        "gameStartTime": f"{game_date}T20:00:00Z",
        "feeCoefficient": 0.02,
        "orderPriceMinTickSize": "0.001",
        "minimumTradeQty": "1",
        "status": "MARKET_STATUS_OPEN",
    }


# --- resolve_kalshi_moneylines -----------------------------------------------


def test_resolves_a_real_moneyline_market_to_the_board_game():
    result = mod.resolve_kalshi_moneylines([_kalshi_moneyline_market()], _board_rows())
    assert result["refusals"] == {}
    assert len(result["markets"]) == 1
    m = result["markets"][0]
    assert m["sport"] == "mlb"
    assert m["home_team"] == "CHW"
    assert m["away_team"] == "TEX"
    assert m["game_date"] == "2026-08-24"
    # subject=TEX is the AWAY team here, so TEX's yes price is the away price.
    assert m["away_probability"] == pytest.approx(mod_implied(-150), abs=1e-6)
    assert m["home_probability"] == pytest.approx(mod_implied(130), abs=1e-6)


def mod_implied(price):
    from syndicate.features.shared.opportunity_signals import implied_probability

    return implied_probability(price)


def test_a_non_moneyline_market_is_silently_not_counted():
    market = _kalshi_moneyline_market()
    market["title"] = "TEX total bases over 8.5?"  # a different grammar entirely
    result = mod.resolve_kalshi_moneylines([market], _board_rows())
    assert result["markets"] == []
    assert result["refusals"] == {}


def test_an_unresolvable_event_is_a_named_refusal(monkeypatch):
    from syndicate.features.shared import kalshi_catalogue

    monkeypatch.setitem(kalshi_catalogue.SERIES_SPORT, "KXTESTML", "mlb")
    # No board rows at all -> no game to match.
    result = mod.resolve_kalshi_moneylines([_kalshi_moneyline_market()], [])
    assert result["markets"] == []
    assert any(k.startswith("event_") for k in result["refusals"])


def test_a_market_with_no_price_is_refused_by_name():
    market = _kalshi_moneyline_market(yes_american=None, no_american=None)
    result = mod.resolve_kalshi_moneylines([market], _board_rows())
    assert result["markets"] == []
    assert result["refusals"] == {"no_price": 1}


# --- resolve_polymarket_moneylines ------------------------------------------


def test_resolves_a_real_polymarket_moneyline_row():
    result = mod.resolve_polymarket_moneylines([_polymarket_row()])
    assert result["refusals"] == {}
    assert len(result["markets"]) == 1
    m = result["markets"][0]
    assert m["teams"] == [("Rangers", 0.42), ("White Sox", 0.58)]
    assert m["game_date"] == "2026-08-24"
    assert m["fee_coefficient"] == 0.02


def test_a_non_moneyline_row_is_silently_not_counted():
    row = _polymarket_row()
    row["sportsMarketTypeV2"] = "SPORTS_MARKET_TYPE_SPREAD"
    result = mod.resolve_polymarket_moneylines([row])
    assert result["markets"] == []
    assert result["refusals"] == {}


def test_json_encoded_outcomes_are_decoded():
    import json

    row = _polymarket_row()
    row["outcomes"] = json.dumps(row["outcomes"])
    row["outcomePrices"] = json.dumps(row["outcomePrices"])
    result = mod.resolve_polymarket_moneylines([row])
    assert len(result["markets"]) == 1
    assert result["markets"][0]["teams"] == [("Rangers", 0.42), ("White Sox", 0.58)]


def test_a_three_sided_row_is_refused_by_name():
    row = _polymarket_row(teams=("A", "B"), prices=("0.3", "0.3"))
    row["outcomes"] = ["A", "B", "C"]
    result = mod.resolve_polymarket_moneylines([row])
    assert result["markets"] == []
    assert list(result["refusals"].keys()) == ["not_two_sided:3v2"]


def test_a_row_missing_gamestarttime_is_refused_by_name():
    row = _polymarket_row()
    row["gameStartTime"] = ""
    result = mod.resolve_polymarket_moneylines([row])
    assert result["markets"] == []
    assert result["refusals"] == {"no_game_start": 1}


def test_an_out_of_range_price_is_refused_by_name():
    row = _polymarket_row(prices=("1.0", "0.0"))
    result = mod.resolve_polymarket_moneylines([row])
    assert result["markets"] == []
    assert result["refusals"] == {"price_out_of_range": 1}


# --- join_kalshi_polymarket_moneylines --------------------------------------


def test_joins_the_same_game_by_team_set_and_date_not_slug_position():
    kalshi = mod.resolve_kalshi_moneylines([_kalshi_moneyline_market()], _board_rows())["markets"]
    # Polymarket lists the SAME two teams in the OPPOSITE order from Kalshi's
    # ticker blob -- proving the join is not positional.
    polymarket = mod.resolve_polymarket_moneylines(
        [_polymarket_row(teams=("White Sox", "Rangers"), prices=("0.55", "0.45"))]
    )["markets"]
    joined = mod.join_kalshi_polymarket_moneylines(kalshi, polymarket)
    assert joined["refusals"] == {}
    assert len(joined["matches"]) == 1
    m = joined["matches"][0]
    assert m["home_team"] == "CHW"
    assert m["away_team"] == "TEX"
    # White Sox (home=CHW) priced at 0.55, Rangers (away=TEX) priced at 0.45 --
    # assigned by NAME, matching the correct side despite the swapped order.
    assert m["polymarket_home_probability"] == pytest.approx(0.55)
    assert m["polymarket_away_probability"] == pytest.approx(0.45)


def test_no_polymarket_row_on_the_date_is_a_named_refusal():
    kalshi = mod.resolve_kalshi_moneylines([_kalshi_moneyline_market()], _board_rows())["markets"]
    joined = mod.join_kalshi_polymarket_moneylines(kalshi, [])
    assert joined["matches"] == []
    assert joined["refusals"] == {"no_polymarket_match": 1}


def test_a_different_date_does_not_match():
    kalshi = mod.resolve_kalshi_moneylines([_kalshi_moneyline_market()], _board_rows())["markets"]
    polymarket = mod.resolve_polymarket_moneylines(
        [_polymarket_row(teams=("White Sox", "Rangers"), game_date="2026-08-25")]
    )["markets"]
    joined = mod.join_kalshi_polymarket_moneylines(kalshi, polymarket)
    assert joined["matches"] == []
    assert joined["refusals"] == {"no_polymarket_match": 1}


def test_two_polymarket_rows_for_the_same_game_is_ambiguous_not_guessed():
    kalshi = mod.resolve_kalshi_moneylines([_kalshi_moneyline_market()], _board_rows())["markets"]
    polymarket = mod.resolve_polymarket_moneylines(
        [
            _polymarket_row(teams=("White Sox", "Rangers"), market_id="pm1"),
            _polymarket_row(teams=("White Sox", "Rangers"), market_id="pm2"),
        ]
    )["markets"]
    joined = mod.join_kalshi_polymarket_moneylines(kalshi, polymarket)
    assert joined["matches"] == []
    assert joined["refusals"] == {"ambiguous_polymarket_match": 1}


# --- detect_arb_opportunities ------------------------------------------------


def _matched_game(*, kalshi_home=0.40, kalshi_away=0.63, pm_home=0.55, pm_away=0.45):
    return {
        "sport": "mlb",
        "event_id": "e1",
        "home_team": "CHW",
        "away_team": "TEX",
        "game_date": "2026-08-24",
        "kalshi_home_probability": kalshi_home,
        "kalshi_away_probability": kalshi_away,
        "kalshi_ticker": "KXTESTML-26AUG24TEXCWS-T1",
        "polymarket_home_probability": pm_home,
        "polymarket_away_probability": pm_away,
        "polymarket_market_id": "pm1",
        "polymarket_fee_coefficient": 0.02,
        "polymarket_tick": "0.001",
        "polymarket_min_qty": "1",
    }


def test_a_real_price_gap_is_flagged_as_an_opportunity():
    # combo: kalshi_home(0.40) + polymarket_away(0.45) = 0.85 -- well under 1.
    match = _matched_game(kalshi_home=0.40, kalshi_away=0.63, pm_home=0.55, pm_away=0.45)
    result = mod.detect_arb_opportunities([match], fee_buffer=0.04)
    assert len(result) == 1
    r = result[0]
    assert r["best_combo"] == "home_on_kalshi_away_on_polymarket"
    assert r["best_combo_cost"] == pytest.approx(0.85)
    assert r["raw_edge"] == pytest.approx(0.15)
    assert r["edge_after_buffer"] == pytest.approx(0.11)
    assert r["is_opportunity"] is True


def test_agreeing_venues_are_not_flagged():
    # Both venues price this ~50/50 with normal vig -- no real gap.
    match = _matched_game(kalshi_home=0.52, kalshi_away=0.52, pm_home=0.51, pm_away=0.51)
    result = mod.detect_arb_opportunities([match], fee_buffer=0.04)
    assert result[0]["is_opportunity"] is False


def test_the_cheaper_combo_is_selected_when_only_one_side_has_a_gap():
    # home_on_kalshi + away_on_polymarket = 0.52+0.51=1.03 (no gap)
    # away_on_kalshi + home_on_polymarket = 0.52+0.40=0.92 (real gap)
    match = _matched_game(kalshi_home=0.52, kalshi_away=0.52, pm_home=0.40, pm_away=0.51)
    result = mod.detect_arb_opportunities([match], fee_buffer=0.04)
    r = result[0]
    assert r["best_combo"] == "away_on_kalshi_home_on_polymarket"
    assert r["best_combo_cost"] == pytest.approx(0.92)
    assert r["is_opportunity"] is True


def test_default_fee_buffer_is_documented_not_zero():
    assert mod.DEFAULT_FEE_BUFFER > 0


def test_every_match_is_returned_even_when_not_an_opportunity():
    """A near-miss is still useful signal -- not silently dropped."""
    match = _matched_game(kalshi_home=0.50, kalshi_away=0.50, pm_home=0.50, pm_away=0.50)
    result = mod.detect_arb_opportunities([match])
    assert len(result) == 1
    assert result[0]["is_opportunity"] is False


# --- run_arb_scan (the end-to-end entry point) -------------------------------


def test_run_arb_scan_reports_named_reasons_for_every_missing_input(monkeypatch):
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist", lambda date: None
    )
    result = mod.run_arb_scan(selected_date="2026-08-24")
    assert result["status"] == "error"
    assert result["reason"] == "no_board_rows"


def test_run_arb_scan_end_to_end_with_stubbed_inputs(monkeypatch):
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": _board_rows()},
    )
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda path: {"markets": [_kalshi_moneyline_market()]},
    )

    from syndicate.features.shared import polymarket_us_markets

    def _fake_fetch_markets(**kwargs):
        assert kwargs["open_only"] is True
        assert kwargs["drop_settled"] is True
        return {
            "status": "ok",
            "markets": [_polymarket_row(teams=("White Sox", "Rangers"), prices=("0.55", "0.45"))],
        }

    monkeypatch.setattr(polymarket_us_markets, "fetch_markets", _fake_fetch_markets)

    result = mod.run_arb_scan(selected_date="2026-08-24")
    assert result["status"] == "ok"
    assert result["kalshi_moneylines_resolved"] == 1
    assert result["polymarket_moneylines_resolved"] == 1
    assert result["matched_games"] == 1
    assert len(result["opportunities"]) == 1
