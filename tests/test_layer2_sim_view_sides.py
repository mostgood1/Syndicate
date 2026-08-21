"""The Layer 2 board must never attribute a number to the sim that is about a
different side, a different quantity, or a different thing entirely.

Every test here FAILS on the pre-2026-08-21 code. That is the point: this file
exists because four defects of the same shape shipped silently, and a test that
passes both before and after a fix cannot tell anyone which state they are in.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.layer2_board import (
    _layer2_board_columns,
    _model_edge_for,
    _model_prob_for_side,
)
from syndicate.features.shared.opportunity_signals import _book_confidence
from syndicate.features.shared.prop_projections import _HITTER_BUCKETS


# --- (1) the wrong-side probability -------------------------------------

def _two_way_row(side: str) -> dict:
    """h2h row whose projection is framed on HOME at 62% against a fair .55.

    `edge_vs_market_pct` is framed on HOME too (+7.0 = (0.62 - 0.55) * 100),
    because that is what `attach_projections` writes -- `_model_edge_for` is
    what re-frames it per side, and this fixture must not do that job for it.
    """
    return {
        "market": "h2h",
        "side": side,
        "projection": {"side": "home", "model_prob_over": 0.62, "edge_vs_market_pct": 7.0},
    }


def test_model_probability_is_the_rows_own_side_not_the_projections_framing():
    # `model_prob_over` is the HOME number; the away row must not publish it.
    assert _model_prob_for_side(_two_way_row("home")) == pytest.approx(0.62)
    assert _model_prob_for_side(_two_way_row("away")) == pytest.approx(0.38)


def test_away_row_columns_do_not_carry_the_home_probability():
    """The exact defect: a coherent badge beside an incoherent probability."""
    away = _two_way_row("away")
    away["model_edge_pct"] = _model_edge_for(away, "away", 0.45)
    cols = _layer2_board_columns(away, {"fair_probability": 0.45}, {})

    assert cols["sim_view"] == "disagrees"          # was already right
    assert cols["model_probability"] == pytest.approx(0.38)   # was 0.62


def test_three_way_draw_leg_is_priced_directly_never_negated():
    """With a draw leg, 1 - P(home) is not P(away). Soccer h2h."""
    row = {
        "market": "h2h_3_way",
        "side": "draw",
        "projection": {
            "side": "home",
            "model_prob_over": 0.50,
            "draw_probability": 0.27,
            "away_probability": 0.23,
        },
    }
    assert _model_prob_for_side(row) == pytest.approx(0.27)
    row["side"] = "away"
    assert _model_prob_for_side(row) == pytest.approx(0.23)
    # ...and NOT the two-way identity, which would have said 0.50.
    assert _model_prob_for_side(row) != pytest.approx(0.50)


def test_three_way_side_we_cannot_price_is_dropped_not_negated():
    row = {
        "market": "h2h_3_way",
        "side": "away",
        "projection": {"side": "home", "model_prob_over": 0.50, "draw_probability": 0.27},
    }
    assert _model_prob_for_side(row) is None


# --- (2) Win% was the book-count multiplier -----------------------------

def test_win_pct_is_a_win_probability_not_the_books_quoting_ladder():
    """Reproduces the 2026-08-21 served board, where five distinct Win% values
    mapped 1:1 onto `_book_confidence` and nothing else."""
    row = _two_way_row("away")
    row["model_edge_pct"] = _model_edge_for(row, "away", 0.45)
    # 14 books -> _book_confidence == 1.0, which used to render as "Win% 100%".
    score = {"book_confidence": _book_confidence(14)}
    cols = _layer2_board_columns(row, {"fair_probability": 0.45}, score)

    assert score["book_confidence"] == 1.0
    assert cols["confidence"] == pytest.approx(0.38)   # the model, not the ladder
    assert cols["book_confidence"] == 1.0              # still carried, named honestly


def test_win_pct_is_blank_rather_than_a_book_count_when_there_is_no_model():
    row = {"market": "h2h", "side": "away", "projection": {}}
    cols = _layer2_board_columns(row, {"fair_probability": 0.45}, {"book_confidence": 0.5})
    assert "confidence" not in cols          # was 0.5, i.e. a rendered "50%"
    assert cols["sim_view"] == "none"


# --- (3) the live sim's own verdict -------------------------------------

def test_live_resim_dissent_is_labelled_as_live():
    row = {
        "market": "batter_runs_scored",
        "side": "under",
        "model_edge_pct": -6.0,
        "projection": {"side": "under", "model_prob_over": 0.31,
                       "basis": "live_resim", "live_prob_over": 0.31},
    }
    cols = _layer2_board_columns(row, {"fair_probability": 0.40}, {})
    assert cols["sim_view"] == "live_disagrees"
    assert cols["sim_basis"] == "live_resim"


def test_pregame_projection_in_a_live_game_is_not_labelled_live():
    """The re-sim's coverage is bounded by the live lens'. A pregame number
    sitting in a live game must stay pregame -- labelling it live is the
    fabrication the Projected column already refuses."""
    row = {
        "market": "batter_runs_scored",
        "side": "under",
        "is_live": True,
        "model_edge_pct": -6.0,
        "projection": {"side": "under", "model_prob_over": 0.31, "basis": "game_simulation"},
    }
    cols = _layer2_board_columns(row, {"fair_probability": 0.40}, {})
    assert cols["sim_view"] == "disagrees"
    assert "sim_basis" not in cols


def test_exactly_zero_edge_is_neutral_not_agreement():
    row = {"market": "h2h", "side": "home", "model_edge_pct": 0.0,
           "projection": {"side": "home", "model_prob_over": 0.55}}
    cols = _layer2_board_columns(row, {"fair_probability": 0.55}, {})
    assert cols["sim_view"] == "neutral"


# --- (4) the mean keys that never resolved ------------------------------

# The spellings the sim actually writes, read off a real `daily_summary`
# artifact at the bucket-row level (2026-07-10).
_ARTIFACT_MEAN_FIELDS = {
    "hits": "h_mean",
    "total_bases": "tb_mean",
    "rbi": "rbi_mean",
    "runs": "r_mean",
    "hits_runs_rbis": "hrr_mean",
    "doubles": "2b_mean",
    "triples": "3b_mean",
    "sb": "sb_mean",
}


@pytest.mark.parametrize("market,expected", [
    ("batter_runs_scored", "r_mean"),      # was "runs_mean"    -> always blank
    ("batter_doubles", "2b_mean"),         # was "doubles_mean" -> always blank
    ("batter_triples", "3b_mean"),         # was "triples_mean" -> always blank
])
def test_hitter_mean_keys_match_the_field_the_sim_writes(market, expected):
    assert _HITTER_BUCKETS[market][1] == expected


def test_every_hitter_market_resolves_to_a_field_that_exists():
    """A mean key naming a nonexistent field yields `projected: None` forever,
    which is indistinguishable from thin model coverage."""
    unresolved = {
        market: mean_key
        for market, (prefix, mean_key) in _HITTER_BUCKETS.items()
        if _ARTIFACT_MEAN_FIELDS.get(prefix) != mean_key
    }
    assert unresolved == {}


# --- (5) a projection that states no framing ----------------------------

@pytest.mark.parametrize("row_side,expected", [
    ("over", 0.62), ("home", 0.62), ("yes", 0.62),
    ("under", 0.38), ("away", 0.38), ("no", 0.38),
])
def test_unframed_projection_falls_back_to_the_fields_own_definition(row_side, expected):
    """`model_prob_over` is the OVER (and, for a game market, the HOME) number.
    That is a guarantee of the NAME, so a projection that omits `side` is still
    placeable -- and returning it unexamined on an `under` row would be the
    original defect one layer further out."""
    row = {"market": "totals", "side": row_side,
           "projection": {"model_prob_over": 0.62}}
    assert _model_prob_for_side(row) == pytest.approx(expected)


def test_an_unplaceable_side_is_dropped_rather_than_guessed():
    row = {"market": "h2h_3_way", "side": "draw",
           "projection": {"model_prob_over": 0.62}}   # no side, no draw_probability
    assert _model_prob_for_side(row) is None
