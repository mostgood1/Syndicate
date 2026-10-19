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

_UNSET = object()


def _apply(*, live_projected, priceable=True, edge_pp=-39.93, model_prob=_UNSET):
    """Run `_apply_verdict` over a row shaped like the served ones.

    `model_prob` DEFAULTS TO `live_projected` RATHER THAN BEING ABSENT, because
    a verdict without it does not exist: all three pricers set `model_prob`
    before they can set `priceable` (pinned by
    `test_every_priceable_verdict_carries_the_probability_it_priced`). The old
    fixture omitted the key entirely, which is why every assertion here stayed
    green while the moneyline path shipped the wrong label -- the fixture could
    not represent the failing case. Pass it explicitly to build a verdict the
    pricers would not produce.
    """
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
        "model_prob": live_projected if model_prob is _UNSET else model_prob,
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


def test_the_moneyline_shape_says_live_even_though_it_publishes_nothing():
    """**THE DEFECT THIS FILE ORIGINALLY MISSED**, fixed 2026-09-05.

    The moneyline branch of `attach_live_gamelines` calls `_apply_verdict` with
    NO `live_projected` -- it deliberately does not publish
    `live_model_prob_over`, because `layer2_board._live_projection_columns`
    would render that home-framed probability in the Live column of away rows.
    But its edge is priced from `hit["home_win_prob"]`, the LIVE number, so the
    row's edge is live and only its publication is absent.

    This test replaces `test_a_row_with_no_live_projection_says_pregame`, which
    asserted `"pregame"` for this exact shape and was the assertion that made
    the mislabel look intended. `"pregame"` is not a reachable answer here:
    `_apply_verdict` is called only from `attach_live_gamelines`, only on a row
    matched to a live `hit`.
    """
    p = _apply(live_projected=None, model_prob=0.1917)
    assert p["edge_basis"] == "live"
    # publication is still withheld -- that half was correct and stays
    assert "live_model_prob_over" not in p
    assert "live_projected" not in p


def test_every_priceable_verdict_carries_the_probability_it_priced():
    """The implication `edge_basis` now rests on, over the REAL pricers.

    `priceable is True` must imply `model_prob is not None`, or the label falls
    back to `"pregame"` on a row that was priced live. Asserted against all
    three pricing functions rather than against a fixture, because a fixture is
    what hid the original defect.
    """
    dist = {8.0: 0.2, 9.0: 0.3, 10.0: 0.5}

    verdicts = [
        mod.price_moneyline(model_prob=0.62, market_prob=0.40, sims=1200),
        mod.price_distribution_market(dist=dist, line=8.5, side="over",
                                      market="totals", market_prob=0.35, sims=1200),
        mod.price_analytic_line_market(
            analytic={"spread": {"p_home_cover": 0.71, "line": -3.5}},
            market="spreads", line=-3.5, market_prob=0.45,
            analytic_std_err=0.02, sport="wnba",
        ),
    ]
    priceable = [v for v in verdicts if v and v.get("priceable")]
    assert len(priceable) == 3, f"fixture stopped exercising the pricers: {verdicts}"
    for verdict in priceable:
        assert verdict["model_prob"] is not None
        # and the edge really is that probability minus the market's
        assert verdict["edge_pp"] == pytest.approx(
            (verdict["model_prob"] - verdict["market_prob"]) * 100, abs=0.01
        )


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


def test_the_15_point_guard_WAS_replaced_once_the_pairing_was_revisited():
    """The successor to `test_the_boards_15_point_guard_is_what_currently_catches_
    the_worst_rows`, which asserted the `-39.93` row stays DROPPED.

    That test's own terms have now been met. It said: *"`layer2_board`'s own
    comment beside `_MODEL_EDGE_MAX_POINTS = 15.0` says: 'The real fix is an
    explicit `basis` on the projection... Until projections carry it, this bound
    is the guard'. This change supplies that basis. It does NOT relax the bound,
    and this test fails if someone relaxes it without revisiting the pairing."*

    `[2026-10-19, user decision: "replace the ceiling"]` the bound WAS relaxed,
    **and the pairing was revisited first** -- `_plausibility_refusal` now reads
    `edge_basis` and tests `live_model_prob_over` on a live row instead of the
    pregame `model_prob_over`. Reading the wrong one was a real bug in the first
    draft, caught by this file's sibling test.

    Why relaxing it was evidenced rather than convenient: of 525 rows the
    15-point bound refused, **0** implied an impossible probability and **470
    (89.5%)** implied an ORDINARY one; of 116 refused NFL-yardage markets **84
    (72.4%)** were refused on magnitude alone. Over 1,769 served rows the new
    test refuses 36 where the old refused 377.

    **This row is now ALLOWED, and it is the honest edge of the decision.** Live
    model 0.1917 against a market at 0.591 is a 40-point disagreement in which
    BOTH ends are probabilities a bettor can act on, so the plausibility bound
    has nothing to say about it; whether the model deserves to be believed is
    `_apply_skill_reliability`'s question, not this one's. Note 0.1917 sits only
    4 points above the 0.15 floor -- the thresholds are the docstring's own and
    are UNFITTED, so this row would flip if they were ever fitted.
    """
    from syndicate.features.shared import layer2_board

    # the constant still exists: it is the revert path and it still bounds the
    # modelled-fair, three-way and calibrated edges
    assert layer2_board._MODEL_EDGE_MAX_POINTS == 15.0

    p = _apply(live_projected=0.1917, edge_pp=-39.93)
    assert p["edge_basis"] == "live"
    assert p["live_model_prob_over"] == pytest.approx(0.1917)

    ref = {}
    got = layer2_board._model_edge_for({"projection": p}, "over", None, refusal=ref)
    assert got == pytest.approx(-39.93), "ordinary-vs-ordinary is no longer dropped"
    assert ref == {}

    # and the PAIRING is what makes that correct: the pregame probability on the
    # same row IS extreme, so reading it would still refuse this row
    assert layer2_board._probability_is_extreme(p["model_prob_over"])

    # the revert flag restores the old verdict exactly
    import os
    os.environ[layer2_board.PLAUSIBILITY_BOUND_ENV] = "magnitude"
    try:
        assert layer2_board._model_edge_for({"projection": p}, "over") is None
    finally:
        os.environ.pop(layer2_board.PLAUSIBILITY_BOUND_ENV, None)
