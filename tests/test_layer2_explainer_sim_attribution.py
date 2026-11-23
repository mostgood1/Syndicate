""""Our sim has X at Y%" must quote the SIM'S number (todo #861 step 1b, lane surface-consistency-oversight).

Measured on the fleet 2026-11-23: 733 of 1,151 pregame Layer 2 rows with a sim ladder served a model probability
EQUAL to the market fair (book blend weight 0), and 643 carried a raw sim more than 5 pp away. The explainer quoted
the served number under the sim's name: Cedric Coward over 2.5 threes read "Our sim has ... at 39.0%" while the sim's
own ladder said 59.2%.
"""
from __future__ import annotations

import re

import pytest

from syndicate.features.shared import layer2_row_context as ctx
from syndicate.features.shared.layer2_row_context import row_explainer


@pytest.fixture(autouse=True)
def _no_data_evidence(monkeypatch):
    # the recency/season evidence reads data/; only the model sentence is under test here
    monkeypatch.setattr(ctx, "row_season_text", lambda row, context: "")
    monkeypatch.setattr(ctx, "row_recent_matchup_text", lambda row, context: "")
    monkeypatch.setattr(ctx, "row_narrative", lambda row, context: None)


def _coward(**projection_over):
    projection = {
        "side": "over", "model_prob_over": 0.3901, "p_model_raw": 0.592, "p_book": 0.3901,
        "book_blend": "applied", "book_blend_w": 0.0, "projected": 2.982, "basis": "empirical_sim_ladder",
    }
    projection.update(projection_over)
    return {"sport": "nba", "event_id": "e", "market": "player_threes", "segment": "full", "side": "over",
            "line": 2.5, "player_name": "Cedric Coward", "projection": projection}


QUOTE = {"price": 170, "bookmaker": "bovada", "fair_probability": 0.38676, "books_quoting": 7}
TAIL = "; the no-vig market across 7 books says 38.7%."


def _first_sentence(text: str) -> str:
    return text.split("%.", 1)[0] + "%."


def test_a_sim_with_no_weight_is_quoted_as_itself_and_the_board_number_named_as_the_market():
    text = row_explainer(_coward(), QUOTE)
    assert _first_sentence(text) == (
        "Our sim has Cedric Coward over 2.5 threes at 59.2%, but it carries no weight in this market yet, "
        "so the board uses the market's number" + TAIL
    )
    assert "39.0%" not in text


def test_a_partial_blend_names_both_numbers():
    text = row_explainer(_coward(book_blend_w=0.4, model_prob_over=0.4709), QUOTE)
    assert _first_sentence(text) == (
        "Our sim has Cedric Coward over 2.5 threes at 59.2%, weighted 40% against the market "
        "for a board probability of 47.1%" + TAIL
    )


def test_a_calibration_without_a_blend_names_both_numbers():
    text = row_explainer(_coward(book_blend="calibrated", book_blend_w=None, model_prob_over=0.55), QUOTE)
    assert _first_sentence(text) == "Our sim has Cedric Coward over 2.5 threes at 59.2%, calibrated to 55.0% for this market" + TAIL


def test_when_the_served_number_is_the_sims_the_sentence_is_unchanged():
    text = row_explainer(_coward(model_prob_over=0.592), QUOTE)
    assert _first_sentence(text) == "Our sim has Cedric Coward over 2.5 threes at 59.2%" + TAIL
    no_raw = _coward(model_prob_over=0.62)
    no_raw["projection"].pop("p_model_raw")
    assert row_explainer(no_raw, QUOTE).startswith("Our sim has Cedric Coward over 2.5 threes at 62.0%" + TAIL)


def test_the_sims_number_is_mapped_to_the_rows_own_side():
    row = _coward()
    row["side"] = "under"
    text = row_explainer(row, {**QUOTE, "fair_probability": 0.61324})
    assert text.startswith("Our sim has Cedric Coward under 2.5 threes at 40.8%, but it carries no weight")


def test_a_live_row_keeps_the_live_resims_number_and_ignores_the_pregame_raw():
    row = _coward(basis="live_resim", model_prob_over=0.45)
    assert row_explainer(row, QUOTE).startswith("The live re-sim has Cedric Coward over 2.5 threes at 45.0%" + TAIL)


def test_the_simulation_share_sentence_uses_the_sims_own_number():
    # mean below the line, sim prices the over above 50%: "N% of its simulations finish over it" is about the draws
    text = row_explainer(_coward(projected=2.4), QUOTE)
    assert "but 59.2% of its simulations finish over it" in text


def test_the_live_strip_regex_still_removes_the_whole_sentence():
    """`intelligence_state` strips this sentence from cards that turn live, with this exact pattern."""
    text = row_explainer(_coward(), QUOTE)
    stripped = re.sub(r"^Our sim has [^;]*; the no-vig market[^;]*? says \d+(?:\.\d+)?%\.\s*", "", text, count=1)
    assert "Our sim" not in stripped and "no-vig market" not in stripped


def test_the_cheat_sheet_still_recognises_the_lead():
    from syndicate.features.shared.cheat_sheets import _ASK_MODEL_LEADS

    assert row_explainer(_coward(), QUOTE).startswith(_ASK_MODEL_LEADS)
