"""The live game-line model is scored against realised outcomes, vs the market.

WHY THIS EXISTS. `live-game-line-projection` closed with the ledger proven able
to produce a sample and its edges **unscored** — nobody had measured whether
those probabilities were RIGHT.

WHY WORKER-SIDE. Measured 2026-08-17 01:0xZ: the ledger matches zero
`HOT_ARTIFACT_PATTERNS` (export → `count 0`, stream → refused), both endpoints
read the serving service's disk rather than the worker's, and a FINISHED game
retains no model probability on any served surface (`{final: 14, live: 1}` →
model_prob rows `{live: 12}`). There is no retrospective path, so the score is
computed where the sample lives and rides an already-published artifact.

THE ASSERTION THAT MATTERS is that model and market are scored on **identical
rows**. A Brier score alone is worthless — predicting the market's own number
scores well and adds nothing.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.live_gameline_score import (
    build_finals_index,
    score_ledger_records,
)


def _grid_row(pk, state, home, away):
    return {"game_pk": pk, "game": {"state": state, "home_score": home, "away_score": away}}


def _rec(pk, model, market=None, priceable=True, at="2026-08-16T22:00:00Z"):
    return {
        "game_pk": pk,
        "recorded_at": at,
        "model_home_win_prob": model,
        "market_fair_prob": market,
        "priceable": priceable,
    }


def test_finals_index_takes_only_decided_final_games():
    grid = [
        _grid_row("g1", "final", 5, 3),   # home won
        _grid_row("g2", "final", 2, 7),   # home lost
        _grid_row("g3", "live", 1, 1),    # not final
        _grid_row("g4", "final", 4, 4),   # TIE -- excluded, not coerced
        _grid_row("g5", "final", None, 2),
    ]
    assert build_finals_index(grid) == {"g1": True, "g2": False}


def test_a_tie_is_never_coerced_into_a_winner():
    """Baseball does not tie, so an equal-score final is a BAD ROW. Guessing a
    winner from it would inject a fabricated outcome into the score."""
    assert build_finals_index([_grid_row("g", "final", 3, 3)]) == {}


def test_model_and_market_are_scored_on_identical_rows():
    """The load-bearing assertion. If the market were scored on a different
    population the comparison would be meaningless, and it would still LOOK
    like a number."""
    finals = {"g1": True, "g2": False}
    recs = [_rec("g1", 0.80, 0.60), _rec("g2", 0.30, 0.40)]
    out = score_ledger_records(recs, finals)
    assert out["all_records"]["model"]["n"] == out["all_records"]["market"]["n"] == 2
    # model: (0.8-1)^2 + (0.3-0)^2 = 0.04 + 0.09 -> 0.065
    assert out["all_records"]["model"]["brier"] == pytest.approx(0.065)
    # market: (0.6-1)^2 + (0.4-0)^2 = 0.16 + 0.16 -> 0.16
    assert out["all_records"]["market"]["brier"] == pytest.approx(0.16)
    # NEGATIVE means the model beat the market.
    assert out["all_records"]["model_minus_market_brier"] == pytest.approx(-0.095)


def test_a_record_whose_game_has_no_outcome_is_counted_not_dropped():
    """"We had no outcome" and "the model was wrong" must never look alike."""
    out = score_ledger_records([_rec("unknown", 0.7, 0.6)], {"g1": True})
    assert out["all_records"]["model"]["n"] == 0
    assert out["unscored"]["no_final_outcome_for_game"] == 1
    assert out["records_considered"] == 1


def test_a_certainty_is_refused_rather_than_scored():
    """A stored 0.0 or 1.0 is a certainty no 120-sim estimator can express, so
    it is far likelier a sentinel or unit error than a forecast. Scoring it
    would hand the model a perfect or maximally-wrong Brier for free."""
    out = score_ledger_records(
        [_rec("g1", 0.0, 0.5), _rec("g1", 1.0, 0.5), _rec("g1", 1.5, 0.5)], {"g1": True}
    )
    assert out["all_records"]["model"]["n"] == 0
    assert out["unscored"]["record_carries_no_model_probability"] == 3


def test_last_per_game_uses_recorded_at_not_file_order():
    """The ledger is append-only so the two normally agree -- but a merged or
    re-pulled file would silently make file order meaningless."""
    finals = {"g1": True}
    recs = [
        _rec("g1", 0.90, 0.5, at="2026-08-16T23:00:00Z"),   # latest, listed FIRST
        _rec("g1", 0.10, 0.5, at="2026-08-16T21:00:00Z"),
    ]
    out = score_ledger_records(recs, finals)
    assert out["last_per_game"]["model"]["n"] == 1
    # 0.90 is the last word -> (0.9-1)^2 = 0.01
    assert out["last_per_game"]["model"]["brier"] == pytest.approx(0.01)
    assert out["all_records"]["model"]["n"] == 2


def test_priceable_only_measures_the_gate_and_all_records_measures_the_model():
    """`priceable` is a FIELD not a filter, exactly so both are available."""
    finals = {"g1": True, "g2": True}
    recs = [_rec("g1", 0.9, 0.5, priceable=True), _rec("g2", 0.1, 0.5, priceable=False)]
    out = score_ledger_records(recs, finals)
    assert out["priceable_only"]["model"]["n"] == 1
    assert out["all_records"]["model"]["n"] == 2
    assert out["priceable_only"]["model"]["brier"] < out["all_records"]["model"]["brier"]


def test_an_empty_sample_reports_None_not_zero():
    """A 0.0 Brier reads as a perfect model. Empty must be None."""
    out = score_ledger_records([], {"g1": True})
    assert out["all_records"]["model"]["brier"] is None
    assert out["all_records"]["model"]["n"] == 0
    assert out["all_records"]["model_minus_market_brier"] is None


def test_a_row_with_no_market_price_still_scores_the_model():
    """The model population must not shrink just because a market number is
    missing -- but the COMPARISON must then decline rather than compare across
    different rows."""
    out = score_ledger_records([_rec("g1", 0.8, None)], {"g1": True})
    assert out["all_records"]["model"]["n"] == 1
    assert out["all_records"]["market"]["n"] == 0
    assert out["all_records"]["model_minus_market_brier"] is None
