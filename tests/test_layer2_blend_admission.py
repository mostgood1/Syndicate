"""Admission is decided by the BLENDED score, not by raw EV.

Before 2026-08-22 `_row_value_pct` read `ev_pct` first and fell back to
`score.value_pct` only when EV was absent -- which, on a scored row, it never
is. So the simulation could REORDER the board but could never put a row ON it:
admission ran on price alone, upstream of anything the sim had to say.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.layer2_board import _row_admitted_by_blend, _row_value_pct


def _row(ev_pct, value_pct=None):
    row = {"ev_pct": ev_pct}
    if value_pct is not None:
        row["score"] = {"score": value_pct, "value_pct": value_pct}
    return row


def test_the_blended_value_is_what_admission_reads():
    # EV alone would be -0.4; the sim carried the blend to +1.1.
    assert _row_value_pct(_row(-0.4, value_pct=1.1)) == pytest.approx(1.1)


def test_the_old_behaviour_would_have_returned_the_raw_ev():
    """The control. Without this change the same row reports -0.4 and is cut by
    any floor above it, so the assertion above is not vacuously true."""
    row = _row(-0.4, value_pct=1.1)
    assert row["ev_pct"] == pytest.approx(-0.4)
    assert _row_value_pct(row) != pytest.approx(row["ev_pct"])


def test_a_row_with_no_score_block_is_judged_exactly_as_before():
    assert _row_value_pct(_row(3.2)) == pytest.approx(3.2)


def test_a_score_block_without_a_value_pct_falls_back_to_ev():
    assert _row_value_pct({"ev_pct": 2.5, "score": {"score": 9.9}}) == pytest.approx(2.5)


def test_a_row_the_blend_rescued_is_counted():
    """The instrument. A rule that changes what reaches the board silently is
    one nobody can tell apart from a different slate."""
    assert _row_admitted_by_blend(_row(-0.4, value_pct=1.1), floor=0.5) is True


def test_a_row_that_cleared_the_floor_on_its_own_is_not_counted():
    assert _row_admitted_by_blend(_row(2.0, value_pct=3.1), floor=0.5) is False


def test_a_row_the_blend_could_not_rescue_is_not_counted():
    # Still below the floor even with the full sim allowance.
    assert _row_admitted_by_blend(_row(-8.0, value_pct=-6.5), floor=0.5) is False


def test_the_sim_cannot_rescue_a_materially_bad_price():
    """The bound that makes handing admission to the blend defensible at all.
    An uncapped sim term here would let an unvalidated model admit arbitrarily
    bad prices -- the 2026-08-08 failure with a wider blast radius than
    ranking."""
    from syndicate.features.shared.opportunity_signals import _SCORE_SIM_CAP_PCT, blended_score

    scored = blended_score(ev_pct=-6.0, model_edge=400.0, books_quoting=7, book_age_seconds=60)
    assert scored is not None
    row = {"ev_pct": -6.0, "score": scored}
    # The blend moved it by at most the cap, so a floor anywhere above
    # (-6.0 + cap) still rejects it.
    assert _row_value_pct(row) <= -6.0 + _SCORE_SIM_CAP_PCT + 1e-9
    assert _row_admitted_by_blend(row, floor=0.0) is False


def test_a_marginal_row_is_exactly_what_the_sim_can_rescue():
    from syndicate.features.shared.opportunity_signals import blended_score

    scored = blended_score(ev_pct=-0.5, model_edge=12.0, books_quoting=7, book_age_seconds=60)
    assert scored is not None
    row = {"ev_pct": -0.5, "score": scored}
    assert _row_admitted_by_blend(row, floor=0.0) is True


def test_the_admission_counter_survives_the_endpoint_hop():
    """THE HOP THAT HAS FAILED FOUR TIMES. `/api/board/layer2-shortlist`
    hand-builds its payload from an explicit key list, and `#373`, `#381`,
    `#391` and `#397` each record a counter that existed at the builder and was
    invisible here -- three of them costing an investigation. This pins it."""
    from syndicate.app import app

    payload = {
        "rows": [],
        "written_at": "2026-08-22T20:00:00Z",
        "rows_below_value_floor": 7,
        "rows_admitted_by_blend": 3,
    }
    client = app.test_client()
    import pipeline.intelligence_state as state

    original = state.read_layer2_shortlist
    try:
        state.read_layer2_shortlist = lambda date: payload
        response = client.get("/api/board/layer2-shortlist?sport=all&date=2026-08-22")
        body = response.get_json()
    finally:
        state.read_layer2_shortlist = original

    assert body["shortlist_present"] is True
    assert body["rows_admitted_by_blend"] == 3
    # Its mirror must still be there too -- they are only interpretable together.
    assert body["rows_below_value_floor"] == 7
