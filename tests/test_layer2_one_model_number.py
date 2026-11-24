"""ONE model number per Layer 2 card (todo #861, lane surface-consistency-oversight; user "Build one number, off").

Measured on the served board 2026-11-24 ~16:25Z: on 3,567 pregame cards, Win% (the projection's served number) minus
the fair missed the model edge (`model_probability_cal - fair`, the number the live sizer stakes on) by more than
0.5 pp on 1,594, and pointed to the opposite side of the market on 39. `SYNDICATE_LAYER2_ONE_MODEL_NUMBER` (absent =
off = today) makes the card and its sentence use the model edge's number.
"""
from __future__ import annotations

import re

import pytest

from syndicate.features.shared import layer2_row_context as ctx
from syndicate.features.shared.layer2_board import _layer2_board_columns, _model_prob_for_side
from syndicate.features.shared.layer2_row_context import ONE_MODEL_NUMBER_ENV, board_model_probability, row_explainer

STRIP = r"^Our sim has [^;]*; the no-vig market[^;]*? says \d+(?:\.\d+)?%\.\s*"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(ONE_MODEL_NUMBER_ENV, raising=False)
    # the recency/season evidence reads data/; only the model sentence is under test here
    monkeypatch.setattr(ctx, "row_season_text", lambda row, context: "")
    monkeypatch.setattr(ctx, "row_recent_matchup_text", lambda row, context: "")
    monkeypatch.setattr(ctx, "row_narrative", lambda row, context: None)


def _sarr(**over):
    """Alex Sarr over 7.5 rebounds+assists as served 2026-11-24: sim 56.2%, blend weight 5%, served 53.1%,
    current fair 54.6%, model edge +0.16 -> model_probability_cal 0.5471."""
    projection = {"side": "over", "model_prob_over": 0.5314, "p_model_raw": 0.562, "p_book": 0.5296,
                  "book_blend": "applied", "book_blend_w": 0.05, "projected": 7.9, "basis": "empirical_sim_ladder"}
    row = {"sport": "nba", "event_id": "e1", "market": "player_rebounds_assists", "segment": "full", "side": "over",
           "line": 7.5, "player_name": "Alex Sarr", "projection": projection,
           "model_probability_cal": 0.5471, "model_edge_pct": 0.16, "calibration_method": "identity"}
    row.update(over)
    return row


QUOTE = {"price": 110, "bookmaker": "fanduel", "fair_probability": 0.5455, "books_quoting": 2}
SCORE = {"score": 1.0}


def _on(monkeypatch):
    monkeypatch.setenv(ONE_MODEL_NUMBER_ENV, "on")


# ---------------------------------------------------------------- off == today


@pytest.mark.parametrize("value", [None, "", "0", "off", "false", "no"])
def test_absent_or_off_is_todays_served_number(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(ONE_MODEL_NUMBER_ENV, value)
    row = _sarr()
    assert board_model_probability(row) == _model_prob_for_side(row) == pytest.approx(0.5314)
    cols = _layer2_board_columns(row, QUOTE, SCORE)
    assert cols["model_probability"] == cols["confidence"] == pytest.approx(0.5314)
    assert "model_probability_basis" not in cols and "model_probability_projection" not in cols


def test_off_columns_and_sentence_are_byte_identical_to_absent(monkeypatch):
    absent_cols, absent_text = _layer2_board_columns(_sarr(), QUOTE, SCORE), row_explainer(_sarr(), QUOTE)
    monkeypatch.setenv(ONE_MODEL_NUMBER_ENV, "off")
    assert _layer2_board_columns(_sarr(), QUOTE, SCORE) == absent_cols
    assert row_explainer(_sarr(), QUOTE) == absent_text


# ---------------------------------------------------------------- reachability: on != off


def test_on_reaches_the_card_and_differs_from_off(monkeypatch):
    off = _layer2_board_columns(_sarr(), QUOTE, SCORE)
    _on(monkeypatch)
    on = _layer2_board_columns(_sarr(), QUOTE, SCORE)
    assert on != off
    assert on["model_probability"] == on["confidence"] == pytest.approx(0.5471)
    assert on["model_probability_projection"] == pytest.approx(0.5314)
    assert on["model_probability_basis"] == "model_edge"


def test_on_win_pct_minus_fair_is_the_model_edge(monkeypatch):
    _on(monkeypatch)
    cols = _layer2_board_columns(_sarr(), QUOTE, SCORE)
    assert (cols["confidence"] - QUOTE["fair_probability"]) * 100 == pytest.approx(0.16, abs=1e-6)


# ---------------------------------------------------------------- where on keeps the served number


def test_on_keeps_the_served_number_on_a_live_row(monkeypatch):
    _on(monkeypatch)
    for live in ({"is_live": True}, {"market_state": "live"}):
        row = _sarr(**live)
        assert board_model_probability(row) == pytest.approx(0.5314)
    row = _sarr()
    row["projection"] = {**row["projection"], "basis": "live_resim"}
    assert board_model_probability(row) == pytest.approx(0.5314)


@pytest.mark.parametrize("drop", ["model_probability_cal", "model_edge_pct"])
def test_on_keeps_the_served_number_without_the_edge_pair(monkeypatch, drop):
    _on(monkeypatch)
    row = _sarr()
    row.pop(drop)
    assert board_model_probability(row) == pytest.approx(0.5314)
    assert "model_probability_basis" not in _layer2_board_columns(row, QUOTE, SCORE)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, "x"])
def test_on_refuses_an_out_of_range_edge_number(monkeypatch, bad):
    _on(monkeypatch)
    assert board_model_probability(_sarr(model_probability_cal=bad)) == pytest.approx(0.5314)


def test_on_maps_nothing_itself_the_stamp_is_already_side_specific(monkeypatch):
    """`model_probability_cal` is stamped on the CANDIDATE, per side (`layer2_board`'s pricing seam), so an under row
    carries the under's number and is taken as is."""
    _on(monkeypatch)
    row = _sarr(side="under", model_probability_cal=0.4529, model_edge_pct=-0.16)
    assert board_model_probability(row) == pytest.approx(0.4529)


# ---------------------------------------------------------------- the sentence names the card's number


def _first(text: str) -> str:
    return text.split("%.", 1)[0] + "%."


TAIL = "; the no-vig market across 2 books says 54.5%."


def test_on_partial_blend_sentence_names_win_pct(monkeypatch):
    _on(monkeypatch)
    text = row_explainer(_sarr(), QUOTE)
    assert _first(text) == (
        "Our sim has Alex Sarr over 7.5 rebounds assists at 56.2%, weighted 5% against the market and re-based on the "
        "current market for a board probability of 54.7%" + TAIL
    )
    assert "54.7%" in text and f"{_layer2_board_columns(_sarr(), QUOTE, SCORE)['confidence']:.1%}" == "54.7%"


def test_on_no_weight_sentence_is_unchanged_in_kind(monkeypatch):
    _on(monkeypatch)
    row = _sarr(model_probability_cal=0.5455, model_edge_pct=0.0)
    row["projection"] = {**row["projection"], "book_blend_w": 0.0, "model_prob_over": 0.5296}
    assert _first(row_explainer(row, QUOTE)) == (
        "Our sim has Alex Sarr over 7.5 rebounds assists at 56.2%, but it carries no weight in this market yet, "
        "so the board uses the market's number" + TAIL
    )


def test_on_unblended_sim_is_re_based(monkeypatch):
    """NFL / NCAAF / soccer / NHL: the served number IS the sim's (no p_model_raw), and only the re-basing moves it."""
    _on(monkeypatch)
    row = _sarr(model_probability_cal=0.5612, model_edge_pct=1.57)
    row["projection"] = {"side": "over", "model_prob_over": 0.5480, "projected": 8.1}
    assert _first(row_explainer(row, QUOTE)) == (
        "Our sim has Alex Sarr over 7.5 rebounds assists at 54.8%, re-based on the current market for a board "
        "probability of 56.1%" + TAIL
    )


def test_on_calibrated_total_names_both_steps(monkeypatch):
    _on(monkeypatch)
    row = _sarr(model_probability_cal=0.4900, model_edge_pct=-5.55)
    row["projection"] = {"side": "over", "model_prob_over": 0.4159, "p_model_raw": 0.685, "book_blend": "total_calibration"}
    assert _first(row_explainer(row, QUOTE)) == (
        "Our sim has Alex Sarr over 7.5 rebounds assists at 68.5%, calibrated for this market and re-based on the "
        "current market for a board probability of 49.0%" + TAIL
    )


def test_on_a_sub_precision_re_base_still_prints_the_cards_number(monkeypatch):
    """Replay 2026-11-24: served 0.5146 and card 0.5143 printed "51.5%" beside Win% 51.4% (3 of 1,725 rows)."""
    _on(monkeypatch)
    row = _sarr(model_probability_cal=0.5143, model_edge_pct=0.35)
    row["projection"] = {**row["projection"], "model_prob_over": 0.5146}
    cols = _layer2_board_columns(row, QUOTE, SCORE)
    assert f"{cols['confidence']:.1%}" == "51.4%"
    assert "for a board probability of 51.4%" in row_explainer(row, QUOTE)


def test_on_with_no_re_basing_the_sentence_is_todays(monkeypatch):
    row = _sarr(model_probability_cal=0.5314)
    off = row_explainer(row, QUOTE)
    _on(monkeypatch)
    assert row_explainer(row, QUOTE) == off


def test_on_wording_still_matches_the_live_strip_and_the_cheat_sheet_lead(monkeypatch):
    from syndicate.features.shared.cheat_sheets import _ASK_MODEL_LEADS

    _on(monkeypatch)
    text = row_explainer(_sarr(), QUOTE)
    assert text.startswith(_ASK_MODEL_LEADS)
    stripped = re.sub(STRIP, "", text, count=1)
    assert "Our sim" not in stripped and "no-vig market" not in stripped
