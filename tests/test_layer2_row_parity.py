"""A Layer 2 CARD carries movement, a sparkline, a face and a sentence.

Lane `layer2-row-parity`. Served board 2026-09-15 15:25Z: of 3,070 rows, the 58
from the legacy candidate pipeline had headshots, explainers and sparklines and
the 2,959 Layer 2 rows had none. These pin the card builder's half; the pieces
are unit-tested in `test_clv_price_trail.py` and `test_layer2_row_context.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone

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


def test_the_sparkline_rides_the_card_from_the_trail():
    row = _row()
    now = int(datetime.now(timezone.utc).timestamp())
    trail = {
        movement_join_key(row): [
            (now - 3600, 6.5, 0.40, 150.0, "polymarket"),
            (now - 1800, 6.5, 0.42, 145.0, "polymarket"),
        ]
    }
    card = layer2_rows_to_board_cards([row], price_trail=trail)[0]
    assert card["movement_series_basis"] == "fair"
    values = [value for _, value in card["movement_series"]]
    assert values[0] == 4000 and values[-1] == 4417, "rising: the market moved toward the over"
    assert card["movement_series"][-1][0] >= 59, "x is minutes since the first point"


def test_no_trail_means_no_sparkline():
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
