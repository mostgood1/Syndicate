"""`edge_vs_market_pct` must say WHICH probability it was computed against.

THE DEFECT. `_apply_verdict` writes the LIVE edge into
`projection["edge_vs_market_pct"]` while deliberately leaving `model_prob_over`
at its PREGAME value (the live probability goes to a new `live_model_prob_over`
key, to preserve provenance). The edge therefore refers to a different
probability than the one printed beside it, and nothing said so.

Measured on the served shortlist 2026-08-16, 13 rows carrying both an edge and
the probability pair: the 7 whose edge could NOT be reproduced from
`(model_prob_over - market_fair_prob_over)` were all `live_aware`; all 6 that
reconciled were not. **7/7 separation.** One row's stated `-39.93` is exactly
`(live_model_prob_over 0.1917 - market_fair_prob_over 0.591) * 100`, where the
pregame pairing gives `+27.46`.

WHAT THIS PINS, and why it is a key rather than a rename: `edge_basis` is
ADDITIVE. `layer2_board._model_edge_for` reads `edge_vs_market_pct` directly and
it becomes the board's `model_edge_pct`, so renaming the live edge would make the
board price LIVE rows off a PREGAME edge. The last test here fails if anyone
"tidies" that into a rename.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import live_gameline_join as mod


def _apply(*, live_projected, priceable=True, edge_pp=-39.93):
    """Run `_apply_verdict` over a row shaped like the served ones."""
    row = {
        "market": "totals",
        "projection": {
            # PREGAME pair, deliberately left alone by the join.
            "model_prob_over": 0.8656,
            "market_fair_prob_over": 0.591,
            "projected": 8.95,
            "side": "over",
            "basis": "full/total_runs_dist",
        },
    }
    verdict = {
        "priceable": priceable,
        "edge_pp": edge_pp if priceable else None,
        "withheld_reason": None if priceable else "sigma",
    }
    hit = {"game_pk": "abc", "home_win_prob": 0.52, "sims_run": 120,
           "total_mean": 8.95, "as_of": "2026-08-16T22:00:00Z", "carried_forward": False}
    # `new_coverage()`, not `{}` -- `record()` increments keys it expects to
    # exist, so a bare dict raises KeyError before the assertion is reached.
    coverage = mod.new_coverage()
    mod._apply_verdict(row, row["projection"], verdict, hit, coverage,
                       live_projected=live_projected)
    return row["projection"]


def test_a_live_joined_row_says_its_edge_is_live():
    p = _apply(live_projected=0.1917)
    assert p["edge_basis"] == "live"
    assert p["live_model_prob_over"] == 0.1917
    # the pregame pair is untouched -- that is the provenance the join preserves
    assert p["model_prob_over"] == 0.8656


def test_a_row_with_no_live_projection_says_pregame():
    p = _apply(live_projected=None)
    assert p["edge_basis"] == "pregame"
    assert "live_model_prob_over" not in p


def test_the_live_edge_reconciles_against_the_live_probability_not_the_pregame_one():
    """The arithmetic the 7/7 separation was measured on."""
    p = _apply(live_projected=0.1917)
    live_pair = round((p["live_model_prob_over"] - p["market_fair_prob_over"]) * 100, 2)
    pregame_pair = round((p["model_prob_over"] - p["market_fair_prob_over"]) * 100, 2)
    assert live_pair == pytest.approx(p["edge_vs_market_pct"], abs=0.01)
    assert pregame_pair != pytest.approx(p["edge_vs_market_pct"], abs=0.01)
    # and `edge_basis` is what tells a consumer which of the two to use
    assert p["edge_basis"] == "live"


def test_a_withheld_edge_carries_no_basis():
    """No edge, no basis. Describing the vintage of a `None` is noise."""
    p = _apply(live_projected=0.1917, priceable=False)
    assert p["edge_vs_market_pct"] is None
    assert p.get("edge_basis") is None
    assert p["edge_unavailable_reason"] == "sigma"


def test_the_change_is_additive_and_must_stay_additive():
    """**Anti-regression pin.** `layer2_board._model_edge_for` reads
    `edge_vs_market_pct` directly and it becomes the board's `model_edge_pct`.
    If someone moves the live edge to `live_edge_vs_market_pct`, live rows fall
    back to the PREGAME edge and the board prices live games off it -- worse than
    the defect this fixes. That rename was proposed and withdrawn; this fails if
    it comes back.

    Uses an edge INSIDE `_MODEL_EDGE_MAX_POINTS` so the assertion is about the
    field the board reads, not about the ceiling -- see the next test."""
    from syndicate.features.shared import layer2_board

    p = _apply(live_projected=0.50, edge_pp=-12.0)
    assert p["edge_vs_market_pct"] == -12.0, "the LIVE edge must stay in the field the board reads"
    assert "live_edge_vs_market_pct" not in p, "the withdrawn rename is back"
    assert layer2_board._model_edge_for({"projection": p}, "over") == pytest.approx(-12.0)


def test_the_boards_15_point_guard_is_what_currently_catches_the_worst_rows():
    """Why the `-39.93` row is not already mispriced on the board, and why
    `edge_basis` is the thing that could eventually replace the guard.

    `layer2_board`'s own comment beside `_MODEL_EDGE_MAX_POINTS = 15.0` says:
    "The real fix is an explicit `basis` on the projection... Until projections
    carry it, this bound is the guard -- and it is a GUARD, not a calibration."
    This change supplies that basis. **It does NOT relax the bound**, and this
    test fails if someone relaxes it without revisiting the pairing."""
    from syndicate.features.shared import layer2_board

    assert layer2_board._MODEL_EDGE_MAX_POINTS == 15.0
    p = _apply(live_projected=0.1917, edge_pp=-39.93)
    assert p["edge_basis"] == "live"
    assert layer2_board._model_edge_for({"projection": p}, "over") is None, (
        "a 39.93-point edge must still be DROPPED by the guard"
    )
