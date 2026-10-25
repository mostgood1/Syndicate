"""A pregame card the serve-time scoreboard join turns live gets the build's pregame-probability rule (lane
live-winpct-blank, 2026-10-25). Measured that day: 501 of 648 live NFL cards at 12:14 PM CT still carried Win% and
"Our sim has"; DEN @ ARI rendered "SIM: 55%" five minutes after its 3:05 PM kickoff."""
from __future__ import annotations

from pipeline.intelligence_state import _withhold_pregame_probability_on_live_card as withhold


def _card(**extra):
    card = {"sport": "nfl", "kind": "game", "market": "spreads", "segment": "h1", "side": "home", "line": 2.5,
            "model_probability": 0.5533, "sim_view": "agrees", "sim_view_basis": "projection_vs_line",
            "detail": "Our sim has ARI +2.5 at 55.3%; the no-vig market across 6 books says 51.2%. It projects an "
                      "average of -0.7 against the +2.5 line."}
    card.update(extra)
    return card


def test_a_pregame_nfl_card_turned_live_loses_its_win_pct_and_is_labelled():
    card = _card()
    withhold(card)
    assert card["model_probability"] is None and card["sim_model_probability"] == 0.5533
    assert card["pregame_on_live"] is True
    assert card["sim_view"] == "unpriced" and card["sim_unpriced_reason"] == "live" and "sim_view_basis" not in card
    assert card["detail"] == "It projects an average of -0.7 against the +2.5 line."


def test_a_contradiction_on_a_live_line_is_not_kept():
    card = _card(sim_view="contradicts", sim_line_gap=3.1, sim_disagreement_pct=-4.0)
    withhold(card)
    assert card["sim_view"] == "unpriced" and "sim_line_gap" not in card and "sim_disagreement_pct" not in card


def test_live_resim_cards_other_sports_and_already_withheld_cards_are_left_alone():
    for card in (_card(live_aware=True), _card(sport="soccer"), _card(sport="mlb"),
                 _card(pregame_on_live=True, model_probability=None)):
        before = dict(card)
        withhold(card)
        assert card == before
    ncaaf = _card(sport="ncaaf")
    withhold(ncaaf)
    assert ncaaf["model_probability"] is None


def test_a_card_with_no_sim_view_keeps_none_and_no_detail_is_fine():
    card = _card(sim_view="none", model_probability=None, detail=None)
    withhold(card)
    assert card["sim_view"] == "none" and card["pregame_on_live"] is True and card["detail"] is None
