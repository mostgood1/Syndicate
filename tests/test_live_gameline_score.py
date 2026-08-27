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
        _grid_row("g4", "final", 4, 4),   # level -- a BAD ROW in baseball
        _grid_row("g5", "final", None, 2),
    ]
    assert build_finals_index(grid, sport="mlb") == {"g1": True, "g2": False}


def test_a_tie_is_never_coerced_into_a_winner():
    """Baseball does not tie, so an equal-score final is a BAD ROW. Guessing a
    winner from it would inject a fabricated outcome into the score."""
    assert build_finals_index([_grid_row("g", "final", 3, 3)], sport="mlb") == {}


def test_a_soccer_draw_is_a_real_outcome_and_is_scored_as_not_a_home_win():
    """THE REGRESSION THIS FILE EXISTS TO HOLD. Dropping draws conditioned the
    soccer population on the OUTCOME VARIABLE ITSELF -- measured 2026-08-27,
    17-38% of matches per date silently removed. A draw is not a missing
    outcome; for "did the home side win" it is a well-defined False."""
    assert build_finals_index([_grid_row("g", "final", 1, 1)], sport="soccer") == {"g": False}


def test_the_same_grid_scores_differently_for_mlb_and_soccer():
    """OFF != ON. Without this, a sport-blind implementation still passes every
    other test in this file."""
    grid = [_grid_row("g1", "final", 2, 1), _grid_row("g2", "final", 1, 1)]
    assert build_finals_index(grid, sport="mlb") == {"g1": True}
    assert build_finals_index(grid, sport="soccer") == {"g1": True, "g2": False}


def test_an_unknown_sport_does_not_get_the_permissive_branch():
    """A sport in neither table must be SKIPPED and COUNTED, never folded into
    the draw-bearing branch -- calling a level final "not a home win" for a
    sport that cannot draw would fabricate the outcome the original rule feared.
    """
    diag = {}
    assert build_finals_index([_grid_row("g", "final", 1, 1)], diagnostics=diag) == {}
    assert diag["sport_known"] is False
    assert diag["draws_scored_as_not_a_home_win"] is False
    assert diag["finals_skipped_level_sport_unknown"] == 1
    assert diag["finals_skipped_level"] == 0


def test_the_level_final_counters_make_an_exclusion_visible():
    """The exclusion went unnoticed for weeks because nothing counted it."""
    grid = [_grid_row("g1", "final", 3, 1), _grid_row("g2", "final", 2, 2)]
    diag = {}
    build_finals_index(grid, sport="mlb", diagnostics=diag)
    assert (diag["finals_seen"], diag["finals_level"], diag["finals_skipped_level"]) == (2, 1, 1)
    diag2 = {}
    build_finals_index(grid, sport="soccer", diagnostics=diag2)
    assert (diag2["finals_seen"], diag2["finals_level"], diag2["finals_skipped_level"]) == (2, 1, 0)


def test_model_and_market_are_scored_on_identical_rows():
    """The load-bearing assertion. If the market were scored on a different
    population the comparison would be meaningless, and it would still LOOK
    like a number.

    NOTE its blind spot, found 2026-08-27: EVERY record in this fixture carries
    a market price, so the populations cannot diverge here no matter what the
    implementation does. It asserted a property on data that could not violate
    it, and passed for weeks while production ran n 94 vs 90. The real
    regression test is the one below.
    """
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


def test_the_difference_is_paired_when_a_row_carries_no_market_price():
    """THE REGRESSION. `market_fair_prob` can be absent where
    `model_home_win_prob` is not, so the market list is a SUBSET of the model
    list. Subtracting their Briers spans two different row sets and describes no
    population at all. Measured on pooled MLB `last_per_game` 2026-08-27:
    model n 94 vs market n 90.
    """
    finals = {"g1": True, "g2": False}
    recs = [_rec("g1", 0.80, 0.60), _rec("g2", 0.30, None)]
    block = score_ledger_records(recs, finals)["all_records"]

    # The populations really do diverge on this fixture ...
    assert block["model"]["n"] == 2
    assert block["market"]["n"] == 1
    assert block["rows_without_market_prob"] == 1

    # ... and the difference is taken ONLY on the row both sides have.
    assert block["model_paired"]["n"] == 1
    assert block["populations_matched"] is True
    # paired model: (0.8-1)^2 = 0.04   market: (0.6-1)^2 = 0.16  -> -0.12
    assert block["model_paired"]["brier"] == pytest.approx(0.04)
    assert block["model_minus_market_brier"] == pytest.approx(-0.12)
    # The pre-fix value was model_all(0.065) - market(0.16) = -0.095. If this
    # ever reads -0.095 again the pairing has been lost.
    assert block["model_minus_market_brier"] != pytest.approx(-0.095)

    # `model` is deliberately UNCHANGED -- the model's score over all its rows
    # is a real quantity, it is just not what the difference may use.
    assert block["model"]["brier"] == pytest.approx(0.065)


def test_every_population_is_paired_not_just_all_records():
    """`last_per_game` was the cut that got quoted, and `priceable_only` only
    LOOKED immune (25,504/25,504) because priceable rows happen to carry a
    price. That is a property of the data, not a guarantee."""
    finals = {"g1": True, "g2": False}
    recs = [_rec("g1", 0.80, 0.60), _rec("g2", 0.30, None)]
    out = score_ledger_records(recs, finals)
    for cut in ("all_records", "last_per_game", "priceable_only"):
        block = out[cut]
        assert block["populations_matched"] is True, cut
        assert block["model_paired"]["n"] == block["market"]["n"], cut


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
