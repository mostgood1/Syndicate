"""A Layer 2 CARD carries movement, a sparkline, a face and a sentence.

Lane `layer2-row-parity`. Served board 2026-09-15 15:25Z: of 3,070 rows, the 58
from the legacy candidate pipeline had headshots, explainers and sparklines and
the 2,959 Layer 2 rows had none. These pin the card builder's half; the pieces
are unit-tested in `test_clv_price_trail.py` and `test_layer2_row_context.py`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards, movement_join_key


def _row(**over):
    row = {
        "sport": "mlb",
        "event_id": "e1",
        "market": "strikeouts",
        "segment": "full",
        "side": "over",
        "line": 6.5,
        "player_name": "Sean Manaea",
        "kind": "prop",
        "ev_pct": 5.13,
        "home_team": "New York Mets",
        "away_team": "Baltimore Orioles",
        "quote": {
            "price": 138,
            "bookmaker": "polymarket",
            "fair_probability": 0.4417,
            "books_quoting": 8,
            "book_prices": {"polymarket": 138},
        },
        "score": {"score": 5.7},
        "projection": {"model_prob_over": 0.5323, "projected": 6.801, "player_id": "640455"},
    }
    row.update(over)
    return row


def test_an_mlb_prop_card_has_a_face_and_a_sentence():
    card = layer2_rows_to_board_cards([_row()])[0]
    assert "/people/640455/headshot/" in card["headshot_url"]
    assert card["player_id"] == "640455"
    assert card["detail"].startswith(
        "Our sim has Sean Manaea over 6.5 strikeouts at 53.2%; the no-vig market across 8 books says 44.2%."
    )


def _opened(row, *, price, minutes_ago, book="polymarket", fair=0.4417):
    key = movement_join_key(row)
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {key: {"key": key, "captured_at": stamp, "price": price, "line": row["line"],
                  "bookmaker": book, "book_prices": {book: price}, "fair_probability": fair}}


def test_the_sparkline_draws_the_market_consensus_from_our_open():
    """User decision 2026-10-02: "the sparkline ... needs to be about the MARKET
    movement, not about a single book". Here polymarket SHORTENED (+160 -> +138)
    while the no-vig consensus FELL (46.0% -> 44.17%): the line and the arrow both
    follow the market, and no book's price is drawn."""
    row = _row()  # published now at +138 on polymarket, consensus 0.4417
    now = int(datetime.now(timezone.utc).timestamp())
    trail = {movement_join_key(row): [(now - 1800, 6.5, 150.0, "polymarket", 0.455), (now - 900, 6.5, 120.0, "betmgm", 0.45)]}
    card = layer2_rows_to_board_cards([row], openings=_opened(row, price=160, minutes_ago=60, fair=0.46), price_trail=trail)[0]
    assert card["movement_series_basis"] == "consensus"
    assert [v for _, v in card["movement_series"]] == [4600, 4550, 4500, 4417]
    assert card["movement_vs_pick"] == "away", "the market fell, whatever polymarket did"
    assert card["movement_series"][-1][1] < card["movement_series"][0][1]
    assert card["movement_series"][-1][0] >= 59, "x is minutes since our publish"


def test_a_consensus_move_draws_a_line_before_the_trail_has_points():
    row = _row()
    card = layer2_rows_to_board_cards([row], openings=_opened(row, price=160, minutes_ago=30, fair=0.46))[0]
    assert [v for _, v in card["movement_series"]] == [4600, 4417]


def test_a_single_book_move_with_the_market_held_draws_no_line():
    row = _row()
    card = layer2_rows_to_board_cards([row], openings=_opened(row, price=160, minutes_ago=30))[0]
    assert "movement_series" not in card
    assert card["movement_vs_pick"] == "flat"


def test_no_price_move_means_no_sparkline():
    card = layer2_rows_to_board_cards([_row()])[0]
    assert "movement_series" not in card


def test_the_row_context_brings_the_write_up():
    text = "His modeled workload cap still reaches roughly 115 pitches."
    context = {"narratives": {("prop", "sean manaea", "strikeouts", "over", 6.5): {"text": text, "player_id": None}}}
    card = layer2_rows_to_board_cards([_row()], row_context=context)[0]
    assert card["detail"].endswith(text)


def test_a_game_card_gets_a_sentence_and_no_face():
    row = _row(market="totals", side="under", line=8.5, player_name=None, kind="game",
               projection={"model_prob_over": 0.45, "projected": 8.1})
    card = layer2_rows_to_board_cards([row])[0]
    assert "headshot_url" not in card
    assert card["detail"].startswith("Our sim has the under 8.5 at")
