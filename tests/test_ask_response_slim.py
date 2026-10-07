"""Ask answers carry a slim board contract (the Layer 2 rail's Ask timed out at 45 s)."""

from __future__ import annotations

from syndicate.blueprints.ask_the_syndicate_adapter import _ASK_BOARD_CARD_LIMIT, _slim_board_contract


def _contract(n: int) -> dict:
    return {
        "schema": "intelligence_board_v1",
        "board_summary": {"headline": "The Syndicate board", "recommendation_count": n},
        "lane_counts": {"pregame": n},
        "cards": [{"event_id": f"e{i}", "player": f"p{i}"} for i in range(n)],
    }


def test_cards_are_capped_and_counted():
    slim = _slim_board_contract(_contract(613), None)
    assert len(slim["cards"]) == _ASK_BOARD_CARD_LIMIT
    assert slim["cards_total"] == 613 and slim["cards_served"] == _ASK_BOARD_CARD_LIMIT
    assert slim["schema"] == "intelligence_board_v1"
    assert slim["board_summary"]["recommendation_count"] == 613


def test_the_asked_game_leads_even_when_it_is_far_down_the_board():
    contract = _contract(613)
    contract["cards"].append({"event_id": "asked", "player": "Naz Hillmon"})
    slim = _slim_board_contract(contract, {"event_id": "asked"})
    assert slim["cards"][0]["player"] == "Naz Hillmon"


def test_input_contract_is_not_mutated():
    contract = _contract(40)
    _slim_board_contract(contract, None)
    assert len(contract["cards"]) == 40


def test_small_board_passes_through():
    slim = _slim_board_contract(_contract(3), None)
    assert len(slim["cards"]) == 3 and slim["cards_total"] == 3
