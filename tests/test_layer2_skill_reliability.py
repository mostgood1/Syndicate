"""Measured skill moves a row's Layer 2 SCORE -- and nothing admission or sizing reads.

`[2026-09-14, user decisions: "Category now, buckets next", "Scale by measured loss",
"Switch directly"]`, lane `accuracy-assessment-0914`.

Every opportunity is still evaluated. What was measured against the market moves where
it surfaces: a row whose model's category LOSES to the market, by a margin the CI
establishes, ranks lower. Parity and unmeasured rows do not move, and nothing is ever
raised.

The load-bearing tests are the ones that prove what does NOT move: `value_pct` (the
admission floor) and the sizing inputs (stake size). The score is what reorders the
board, the per-sport and game caps, and `portfolio_commit`'s truncation -- and those
are the decision -- but a change here that silently moved admission or a stake would
be a different decision nobody made.

A two-sided -110/-110 fixture has NEGATIVE value once the vig is priced, so a correct
multiplier leaves it untouched and a wiring test built only on it would pass while
proving nothing. The wiring tests therefore pin a known positive score at the
`blended_score` seam, and a separate test runs the real path to show a bad row is not
made to look better.
"""

from __future__ import annotations

import math

import pytest

import syndicate.features.shared.layer2_board as l2
import syndicate.features.shared.measured_market_skill as mms
from syndicate.features.shared.portfolio_commit import sizing_inputs_from_row

LOSS_NOTE = {"status": "measured", "verdict_class": "loses_to_market",
             "established_loss_rel": 0.09722, "sample_games": 100}
PARITY_NOTE = {"status": "measured", "verdict_class": "parity",
               "established_loss_rel": 0.0, "sample_games": 188}
LOSS_FACTOR = 1.0 - mms.SKILL_GAIN * 0.09722


# --------------------------------------------------------------------------
# the factor
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "note",
    [
        None,
        {},
        {"status": "unmeasured", "established_loss_rel": 0.2},
        {"status": "measured"},
        PARITY_NOTE,
        {"status": "measured", "established_loss_rel": "x"},
        {"status": "measured", "established_loss_rel": float("nan")},
        {"status": "measured", "established_loss_rel": -0.3},
    ],
)
def test_nothing_short_of_an_established_loss_moves_a_score(note):
    """Unknown is neither punished nor rewarded -- no invented midpoint."""
    assert mms.skill_reliability(note) == 1.0


def test_the_factor_scales_with_the_established_loss():
    assert mms.skill_reliability({"status": "measured", "established_loss_rel": 0.00559}) == pytest.approx(
        1.0 - mms.SKILL_GAIN * 0.00559
    )
    assert mms.skill_reliability(LOSS_NOTE) == pytest.approx(LOSS_FACTOR)
    assert mms.skill_reliability({"status": "measured", "established_loss_rel": 0.5}) == mms.SKILL_FLOOR


def test_established_loss_is_the_ci_lower_bound_over_the_markets_own_error():
    # MLB live moneyline (Brier) and NCAAF pregame totals (MAE): one unit-free scale.
    assert mms.established_loss_rel({"ci95": (0.00089, 0.02045), "brier_market": 0.15931}) == pytest.approx(
        0.00559, abs=1e-5
    )
    assert mms.established_loss_rel({"ci95": (1.119, 4.594), "mae_market": 11.51}) == pytest.approx(
        0.09722, abs=1e-5
    )
    # Parity: the lower bound is below zero, so nothing is established.
    assert mms.established_loss_rel({"ci95": (-0.0046, 0.0236), "brier_market": 0.238}) == 0.0
    # No CI, or no market to scale by: unscoreable, which scores as 1.0.
    assert mms.established_loss_rel({"verdict": "no ci"}) is None
    assert mms.established_loss_rel({"ci95": (0.1, 0.2), "brier_market": 0}) is None


@pytest.mark.parametrize("key", sorted(mms.MEASURED_MARKET_SKILL))
def test_in_the_real_table_only_a_measured_LOSS_moves_a_score(key):
    sport, market, segment, phase = key
    note = dict(mms.skill_note(sport=sport, market=market, segment=segment, phase=phase), status="measured")
    factor = mms.skill_reliability(note)
    if mms.MEASURED_MARKET_SKILL[key]["verdict_class"] == mms.VERDICT_LOSES:
        assert factor < 1.0, f"{key} loses to the market but would not move"
        assert factor >= mms.SKILL_FLOOR
    else:
        assert factor == 1.0, f"{key} is {note['verdict_class']} and must not move"


def test_the_ncaaf_producer_note_carries_the_same_scoring_field():
    from syndicate.features.ncaaf import game_projections as gp

    totals = dict(gp.skill_note("totals"), status="measured")
    margins = dict(gp.skill_note("spreads"), status="measured")
    assert mms.skill_reliability(totals) == pytest.approx(1.0 - mms.SKILL_GAIN * 0.09722)
    assert mms.skill_reliability(margins) == pytest.approx(1.0 - mms.SKILL_GAIN * 0.03718)


# --------------------------------------------------------------------------
# the helper
# --------------------------------------------------------------------------


def test_a_positive_score_is_lowered_and_value_pct_is_untouched():
    score = {"score": 4.0, "value_pct": 5.0, "ev_component": 5.0}
    out = l2._apply_skill_reliability(score, {"model_skill": dict(LOSS_NOTE)})
    assert out["score"] == pytest.approx(round(4.0 * LOSS_FACTOR, 4))
    assert out["value_pct"] == 5.0
    assert out["skill_reliability"] == pytest.approx(round(LOSS_FACTOR, 4))
    assert score == {"score": 4.0, "value_pct": 5.0, "ev_component": 5.0}, "the input must not be mutated"


def test_a_negative_score_is_never_made_to_look_better():
    """`blended_score`'s own rule: a less-trusted bad row must not outrank a trusted one."""
    score = {"score": -3.0, "value_pct": -3.0}
    out = l2._apply_skill_reliability(score, {"model_skill": dict(LOSS_NOTE)})
    assert out["score"] == -3.0


@pytest.mark.parametrize("projection", [None, {}, {"model_skill": dict(PARITY_NOTE)},
                                        {"model_skill": {"status": "unmeasured"}}])
def test_nothing_to_apply_returns_the_score_unchanged(projection):
    score = {"score": 4.0, "value_pct": 5.0}
    assert l2._apply_skill_reliability(score, projection) is score


def test_no_score_stays_no_score():
    assert l2._apply_skill_reliability(None, {"model_skill": dict(LOSS_NOTE)}) is None


# --------------------------------------------------------------------------
# the wiring, through the real `build_layer2_rows`
# --------------------------------------------------------------------------


def _grid_row(event_id="evt-1", player="A. Player", **overrides):
    """One two-sided market in the shape build_book_grid emits (as test_layer2_projection_carry)."""
    row = {
        "sport": "wnba",
        "event_id": event_id,
        "kind": "prop",
        "market": "player_points",
        "segment": "full",
        "line": 18.5,
        "player_name": player,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2099-01-01T00:00:00Z",
        "sides": ["over", "under"],
        "books_quoting": 2,
        "cells": {},
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
            "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0},
        },
    }
    row.update(overrides)
    return row


@pytest.fixture
def positive_score(monkeypatch):
    """A known positive score at the `blended_score` seam, so the multiplier can bite."""
    def fake(**_kwargs):
        return {"score": 4.0, "value_pct": 5.0, "ev_component": 5.0, "sim_component": 0.0}

    monkeypatch.setattr(l2, "blended_score", fake)


def _opportunities(*rows):
    return list(l2.build_layer2_rows(list(rows)).get("opportunities") or [])


def _by_side(rows):
    return {r.get("side"): r for r in rows}


def test_the_board_build_applies_it_and_moves_only_the_score(positive_score):
    plain = _by_side(_opportunities(_grid_row(projection={"edge_vs_market_pct": 6.0})))
    lossy = _by_side(_opportunities(_grid_row(projection={"edge_vs_market_pct": 6.0,
                                                          "model_skill": dict(LOSS_NOTE)})))
    assert plain and set(plain) == set(lossy), "the same rows must be built and admitted"
    for side, row in plain.items():
        other = lossy[side]
        assert other["score"]["score"] == pytest.approx(round(4.0 * LOSS_FACTOR, 4))
        assert row["score"]["score"] == 4.0
        # ADMISSION reads value_pct; SIZING reads ev_pct / model_edge_pct / price.
        assert other["score"]["value_pct"] == row["score"]["value_pct"]
        for field in ("ev_pct", "model_edge_pct", "price"):
            assert other.get(field) == row.get(field), field
        assert sizing_inputs_from_row(other) == sizing_inputs_from_row(row), "stake inputs must not move"


def test_a_measured_loss_ranks_below_an_otherwise_identical_row(positive_score):
    rows = _opportunities(
        _grid_row(event_id="evt-loss", player="Loss Player",
                  projection={"edge_vs_market_pct": 6.0, "model_skill": dict(LOSS_NOTE)}),
        _grid_row(event_id="evt-plain", player="Plain Player",
                  projection={"edge_vs_market_pct": 6.0}),
    )
    order = [r.get("event_id") for r in rows]
    assert order.index("evt-plain") < order.index("evt-loss")


def test_a_parity_note_changes_nothing(positive_score):
    plain = _by_side(_opportunities(_grid_row(projection={"edge_vs_market_pct": 6.0})))
    parity = _by_side(_opportunities(_grid_row(projection={"edge_vs_market_pct": 6.0,
                                                           "model_skill": dict(PARITY_NOTE)})))
    for side in plain:
        assert parity[side]["score"] == plain[side]["score"]


def test_on_the_REAL_scoring_path_a_negative_row_is_not_promoted_by_a_loss_note():
    plain = _by_side(_opportunities(_grid_row(projection={"edge_vs_market_pct": 6.0})))
    lossy = _by_side(_opportunities(_grid_row(projection={"edge_vs_market_pct": 6.0,
                                                          "model_skill": dict(LOSS_NOTE)})))
    assert plain, "fixture must produce candidates on the real path"
    for side, row in plain.items():
        base = row["score"]["score"]
        got = lossy[side]["score"]["score"]
        if base <= 0 or math.isclose(base, 0.0):
            assert got == base
        else:
            assert got <= base
