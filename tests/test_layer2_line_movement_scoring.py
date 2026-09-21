"""A LINE move contributes to the board score, and can fire steam.

Lane `layer2-line-movement-scoring`, 2026-09-20.

THE DEFECT THESE PIN. `_movement_from_opening` withholds `movement_price_delta`
whenever the line moved -- correctly, because a price at a different handicap is
not a price move -- and until this lane NOTHING replaced it. Measured on the
served `/api/board/layer2-shortlist` payload at 2026-09-20T16:23:40Z (build 79 s
old, 2,000 rows of 5,556): `score.movement_component` was non-null on 1,886 rows
and **the 114 nulls were exactly the 114 `movement_basis=line_moved` rows**.
Because the steam detector reads that same withheld delta, steam on a line move
was not rare -- it was structurally impossible.

ORDER OF THESE TESTS IS THE ENGINE STANDARD'S, NOT ALPHABETICAL. Reachability
first (`off != on`), because a correctness test passes just as happily on an
inert feature -- `docs/ai_context/model_engine_standard.md`, written after an
audit found 26 consumed-but-unfed fields in the platform's most mature engine,
every one silent and every one with passing tests.
"""

from __future__ import annotations

import importlib

import pytest

from syndicate.features.shared import layer2_board
from syndicate.features.shared.opportunity_signals import (
    _SCORE_MOVEMENT_CAP_PCT,
    _SCORE_MOVEMENT_LINE_WEIGHT,
    _SCORE_MOVEMENT_WEIGHT,
    blended_score,
)


# ---------------------------------------------------------------------------
# 1. REACHABILITY -- off != on. Before any correctness assertion.
# ---------------------------------------------------------------------------
def test_line_movement_is_reachable_off_differs_from_on():
    """The term must actually move a score, or every test below is decoration."""
    off = blended_score(ev_pct=3.0, movement_line_prob_delta_pp=None)
    on = blended_score(ev_pct=3.0, movement_line_prob_delta_pp=4.0)
    assert off is not None and on is not None
    assert on["score"] != off["score"], "line movement is INERT -- nothing else here means anything"
    assert on["value_pct"] > off["value_pct"]
    assert off["movement_component"] is None
    assert on["movement_component"] > 0


def test_a_line_moved_row_would_have_scored_exactly_zero_before():
    """The production shape: line moved, so no price delta exists at all.

    This is the 114-row case from the served board. Without the line term the
    row's movement contribution is None; with it, it is non-zero.
    """
    before = blended_score(ev_pct=2.5, movement_price_delta=None)
    after = blended_score(ev_pct=2.5, movement_price_delta=None, movement_line_prob_delta_pp=-3.2)
    assert before["movement_component"] is None
    assert after["movement_component"] < 0
    assert after["score"] < before["score"]


# ---------------------------------------------------------------------------
# 2. THE CALIBRATED PRICE TERM IS NOT RE-TUNED
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("delta", [-40.0, -15.0, -1.0, 1.0, 15.0, 40.0, 2000.0])
def test_same_line_rows_are_byte_identical(delta):
    """A row whose line did NOT move must score to the last decimal as before.

    The engine standard's rule about adding a MECHANISM to a calibrated engine:
    it must not silently re-fit what was already absorbing the signal. Nothing
    was absorbing line movement (those rows scored 0.0), so this change is
    additive in a blank region -- and this test is what proves the claim rather
    than asserting it.
    """
    baseline = blended_score(ev_pct=4.0, movement_price_delta=delta)
    with_line_param = blended_score(
        ev_pct=4.0, movement_price_delta=delta, movement_line_prob_delta_pp=None
    )
    assert with_line_param == baseline


def test_price_wins_when_both_are_supplied_so_the_cap_cannot_be_breached():
    """Upstream never sends both. The `elif` is what makes that safe anyway.

    Summing them would put two movement terms in one score and breach the cap
    the whole mechanism rests on. Preferring the CALIBRATED half keeps the new
    half inert, which is the safe direction for a disagreement.
    """
    both = blended_score(ev_pct=1.0, movement_price_delta=20.0, movement_line_prob_delta_pp=9.0)
    price_only = blended_score(ev_pct=1.0, movement_price_delta=20.0)
    assert both == price_only
    assert both["movement_kind"] == "price"


# ---------------------------------------------------------------------------
# 3. THE CAP STILL BOUNDS THE WHOLE MOVEMENT TERM
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pp", [5.0, 25.0, 100.0, 1e6])
def test_line_contribution_never_exceeds_the_shared_cap(pp):
    for signed in (pp, -pp):
        result = blended_score(ev_pct=0.0, movement_line_prob_delta_pp=signed)
        assert abs(result["movement_component"]) <= _SCORE_MOVEMENT_CAP_PCT + 1e-12


def test_line_move_reports_capped_like_a_price_move_does():
    """`movement_capped` used to read `bool(move)` and would say False here.

    That is this field's own 2026-08-21 defect -- a field named for a different
    quantity than the one it carries.
    """
    saturated = blended_score(ev_pct=0.0, movement_line_prob_delta_pp=500.0)
    assert saturated["movement_capped"] is True
    assert saturated["movement_kind"] == "line"


# ---------------------------------------------------------------------------
# 4. UNITS AND SIGN
# ---------------------------------------------------------------------------
def test_one_probability_point_scores_like_the_measured_cents_equivalent():
    """The coefficient is DERIVED, not chosen: 6.192 cents per probability point.

    Measured over the 1,413 rows of the 2026-09-20 served board carrying both a
    cents delta and a probability delta. A 1 pp line move must therefore score
    about what a 6.192-cent price move scores -- that equivalence is the reason
    the two halves of one term can share a cap.
    """
    one_pp = blended_score(ev_pct=0.0, movement_line_prob_delta_pp=1.0)["movement_component"]
    equivalent_cents = blended_score(ev_pct=0.0, movement_price_delta=6.192)["movement_component"]
    assert one_pp == pytest.approx(equivalent_cents, rel=1e-6)
    assert _SCORE_MOVEMENT_LINE_WEIGHT == pytest.approx(_SCORE_MOVEMENT_WEIGHT * 6.192, rel=1e-3)


def test_toward_the_pick_is_positive_and_away_is_negative():
    """One convention reaches `blended_score`: positive = market moved toward us.

    The price half is NEGATED at its call site to reach this convention; the
    line half is already signed by `movement_vs_pick`. Negating the line half
    too would reward every move that went away from the pick -- the exact defect
    fixed for the price half on 2026-09-15.
    """
    toward = blended_score(ev_pct=0.0, movement_line_prob_delta_pp=6.0)
    away = blended_score(ev_pct=0.0, movement_line_prob_delta_pp=-6.0)
    assert toward["movement_component"] > 0 > away["movement_component"]
    assert toward["movement_component"] == pytest.approx(-away["movement_component"])


def test_score_movement_kind_does_not_collide_with_movement_basis():
    """Two DIFFERENT questions, so two different names -- pinned deliberately.

    `_movement_from_opening` publishes `movement_basis` ("same_book" /
    "best_of_n" / "line_moved"): WHERE the comparison came from. The score
    publishes `movement_kind` ("price" / "line"): WHICH COEFFICIENT scored it.
    The card builder spreads the movement block onto the row at TOP level while
    the score dict lands under `score`, so reusing one name would put two fields
    of the same name and different meaning in one payload and leave the UI
    reading whichever the spread order happened to win.
    """
    result = blended_score(ev_pct=1.0, movement_line_prob_delta_pp=3.0)
    assert result["movement_kind"] == "line"
    assert "movement_basis" not in result, (
        "the score must NOT publish `movement_basis` -- that name belongs to the "
        "movement block and carries a different vocabulary"
    )
    producer_vocabulary = {"same_book", "best_of_n", "line_moved"}
    assert result["movement_kind"] not in producer_vocabulary


def test_zero_is_published_and_distinguished_from_absent():
    """"We compared and it had not moved" != "we had no opening to compare"."""
    absent = blended_score(ev_pct=1.0)
    assert absent["movement_component"] is None
    assert absent["movement_kind"] is None
    zero = blended_score(ev_pct=1.0, movement_line_prob_delta_pp=0.0)
    assert zero["movement_component"] == 0.0


# ---------------------------------------------------------------------------
# 5. THE PRODUCER: _movement_from_opening
# ---------------------------------------------------------------------------
def _row(*, side="over", line, price, fair, event_id="E1", market="totals"):
    return {
        "event_id": event_id,
        "market": market,
        "side": side,
        "line": line,
        "quote": {"price": price, "fair_probability": fair, "bookmaker": "betmgm"},
    }


def _opening(*, line, price, fair, captured_at, key, bookmaker="betmgm"):
    return {
        "key": key,
        "line": line,
        "price": price,
        "fair_probability": fair,
        "bookmaker": bookmaker,
        "captured_at": captured_at,
    }


def _curve(row, points):
    """`{line: fair}` -- what the board prices the SAME bet at, at each line,
    RIGHT NOW. Alternate lines are published side by side, which is what makes a
    same-bet comparison possible without any model."""
    return {layer2_board.movement_join_key(row): dict(points)}


def _now_iso(minutes_ago: float) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def test_line_move_emits_a_probability_delta_where_it_used_to_emit_nothing():
    row = _row(line=7.5, price=-110, fair=0.61)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(30), key=key)}
    # Our bet was `over 8.5` at .52; the market now prices that SAME bet at .43.
    out = layer2_board._movement_from_opening(row, openings, _curve(row, {8.5: 0.43, 7.5: 0.61}))

    assert out["movement_basis"] == "line_moved"
    assert out.get("movement_price_delta") is None, "the price gate must still withhold this"
    assert out["movement_vs_pick"] == "away"
    assert out["movement_line_prob_basis"] == "same_bet_exact"
    assert out["movement_line_prob_delta_pp"] == pytest.approx(-9.0, abs=1e-6)
    assert out.get("movement_line_sign_conflict") is None


def test_line_move_toward_the_pick_is_signed_positive():
    row = _row(line=9.5, price=-110, fair=0.60)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(30), key=key)}
    out = layer2_board._movement_from_opening(row, openings, _curve(row, {8.5: 0.63, 9.5: 0.60}))
    assert out["movement_vs_pick"] == "toward"
    assert out["movement_line_prob_delta_pp"] > 0
    assert out.get("movement_line_sign_conflict") is None


def test_the_magnitude_is_interpolated_when_the_open_line_is_not_quoted_now():
    row = _row(line=9.5, price=-110, fair=0.60)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(30), key=key)}
    out = layer2_board._movement_from_opening(row, openings, _curve(row, {8.0: 0.70, 9.0: 0.60}))
    assert out["movement_line_prob_basis"] == "same_bet_interpolated"
    assert out["movement_line_prob_delta_pp"] == pytest.approx(13.0, abs=1e-6)


def test_the_magnitude_is_NEVER_extrapolated_past_the_observed_lines():
    """Past the ends the probability curve flattens; a straight line overstates."""
    row = _row(line=9.5, price=-110, fair=0.60)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(30), key=key)}
    out = layer2_board._movement_from_opening(row, openings, _curve(row, {9.0: 0.60, 10.0: 0.55}))
    assert out.get("movement_line_prob_delta_pp") is None


def test_no_curve_means_no_line_term_rather_than_the_old_wrong_one():
    """48% of line-moved rows have no curve point at their opening line. They get
    NOTHING -- not the cross-handicap number that could contradict itself."""
    row = _row(line=9.5, price=-110, fair=0.60)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(30), key=key)}
    assert layer2_board._movement_from_opening(row, openings, None).get("movement_line_prob_delta_pp") is None


def test_same_line_row_emits_no_line_probability_delta():
    """Emitting it anyway would publish a second movement number nothing reads.

    `book_prices` on both ends so this exercises the SAME-BOOK basis, which is
    the one the price term is calibrated on and the only one steam accepts.
    """
    row = _row(line=8.5, price=-105, fair=0.53)
    row["quote"]["book_prices"] = {"betmgm": -105}
    key = layer2_board.movement_join_key(row)
    opening = _opening(line=8.5, price=-120, fair=0.52, captured_at=_now_iso(30), key=key)
    opening["book_prices"] = {"betmgm": -120}
    out = layer2_board._movement_from_opening(row, {key: opening})
    assert out["movement_basis"] == "same_book"
    assert out.get("movement_line_prob_delta_pp") is None
    assert out.get("movement_price_delta") is not None


def test_best_of_n_same_line_row_also_emits_no_line_probability_delta():
    """Without `book_prices` the basis falls back to best-of-N -- still a PRICE
    row, so the line term must stay silent there too."""
    row = _row(line=8.5, price=-105, fair=0.53)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-120, fair=0.52, captured_at=_now_iso(30), key=key)}
    out = layer2_board._movement_from_opening(row, openings)
    assert out["movement_basis"] == "best_of_n"
    assert out.get("movement_line_prob_delta_pp") is None
    assert out.get("movement_price_delta") is not None


# ---------------------------------------------------------------------------
# 6. STEAM ON A LINE MOVE -- previously impossible, not merely rare
# ---------------------------------------------------------------------------
def test_steam_fires_on_a_sharp_recent_line_move():
    row = _row(line=10.5, price=-110, fair=0.62)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(20), key=key)}
    out = layer2_board._movement_from_opening(row, openings, _curve(row, {8.5: 0.62}))
    assert out.get("steam") is True
    assert out.get("steam_basis") == "line"
    assert "line 8.5" in out["steam_reason"] and "10.5" in out["steam_reason"]


def test_a_slow_line_drift_is_not_steam():
    """Both clock halves still apply. A move over eight hours is not steam."""
    row = _row(line=10.5, price=-110, fair=0.62)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(60 * 8), key=key)}
    out = layer2_board._movement_from_opening(row, openings)
    assert out.get("steam") is not True


def test_a_small_recent_line_move_is_not_steam():
    """The bar is `_STEAM_LINE_PROB_POINTS_PP`, converted from the price bar."""
    row = _row(line=8.0, price=-110, fair=0.531)
    key = layer2_board.movement_join_key(row)
    openings = {key: _opening(line=8.5, price=-110, fair=0.52, captured_at=_now_iso(20), key=key)}
    out = layer2_board._movement_from_opening(row, openings, _curve(row, {8.5: 0.531}))
    assert abs(out["movement_line_prob_delta_pp"]) < layer2_board._STEAM_LINE_PROB_POINTS_PP
    assert out.get("steam") is not True


def test_the_line_steam_bar_is_the_price_bar_in_the_other_unit():
    """One definition of "sharp" across both halves, not two that drift apart."""
    assert layer2_board._STEAM_LINE_PROB_POINTS_PP == pytest.approx(
        layer2_board._STEAM_PRICE_POINTS / 6.192
    )


# ---------------------------------------------------------------------------
# 7. ADMISSION, COUNTED IN BOTH DIRECTIONS
# ---------------------------------------------------------------------------
def _scored_row(value_pct, movement_component, ev_pct=None):
    return {
        "ev_pct": value_pct if ev_pct is None else ev_pct,
        "score": {"value_pct": value_pct, "movement_component": movement_component},
    }


def test_a_row_movement_pushed_under_the_floor_is_counted():
    """The counter that did not exist: movement is a net PENALTY on the board.

    Signed mean -0.2545 EV points over the served rows, 1,151 negative against
    262 positive. Counting only promotions reported the half that essentially
    never fires.
    """
    row = _scored_row(value_pct=-2.4, movement_component=-0.9)
    assert layer2_board._row_refused_by_movement(row, -2.0) is True
    assert layer2_board._row_admitted_by_movement(row, -2.0) is False


def test_a_row_movement_carried_over_the_floor_is_counted():
    row = _scored_row(value_pct=-1.8, movement_component=+0.5)
    assert layer2_board._row_admitted_by_movement(row, -2.0) is True
    assert layer2_board._row_refused_by_movement(row, -2.0) is False


def test_a_row_the_floor_never_bound_is_counted_in_neither_direction():
    row = _scored_row(value_pct=5.0, movement_component=-0.3)
    assert layer2_board._row_admitted_by_movement(row, -2.0) is False
    assert layer2_board._row_refused_by_movement(row, -2.0) is False


def test_an_unscored_row_is_counted_in_neither_direction():
    """Unknown must not default onto either branch."""
    assert layer2_board._row_admitted_by_movement({"ev_pct": 1.0}, -2.0) is False
    assert layer2_board._row_refused_by_movement({"ev_pct": 1.0}, -2.0) is False


# ---------------------------------------------------------------------------
# 8. THE HARNESS SCORES WHAT PRODUCTION SCORES
# ---------------------------------------------------------------------------
def test_harness_curve_matches_production():
    """`decompose_movement_clv` copies the curve so it can screen a CANDIDATE
    weight offline. Copied code drifts, so the equality is pinned here."""
    harness = importlib.import_module("scripts.decompose_movement_clv")
    for move in (-2000.0, -40.0, -6.0, -1.0, 1.0, 6.0, 40.0, 2000.0):
        mine = harness.movement_contribution(move, _SCORE_MOVEMENT_WEIGHT, _SCORE_MOVEMENT_CAP_PCT)
        theirs = blended_score(ev_pct=0.0, movement_price_delta=move)["movement_component"]
        assert mine == pytest.approx(theirs, abs=5e-5), f"harness drifted from production at {move}"


def test_harness_american_cents_matches_production():
    harness = importlib.import_module("scripts.decompose_movement_clv")
    for price in (-104, 104, -250, 250, -110, 110):
        assert harness.american_cents(price) == pytest.approx(layer2_board._american_cents(price))


# ---------------------------------------------------------------------------
# 9. THE TWO GAPS THE FIRST PRODUCTION READING EXPOSED (2026-09-20, post-deploy)
# ---------------------------------------------------------------------------


def test_a_moneyline_never_takes_the_line_gate():
    """32 served rows scored NOTHING because the line gate fired on a market
    with no handicap: 23 h2h, 8 h2h_3_way, all with a price at both ends.

    Suppressing a PRICE comparison to guard against a handicap change is only
    meaningful where a handicap exists. On a moneyline it is pure loss.
    """
    row = _row(side="home", line=None, price=-140, fair=0.57, market="h2h")
    row["quote"]["book_prices"] = {"betmgm": -140}
    key = layer2_board.movement_join_key(row)
    opening = _opening(line=1.5, price=-120, fair=0.55, captured_at=_now_iso(30), key=key)
    opening["book_prices"] = {"betmgm": -120}
    out = layer2_board._movement_from_opening(row, {key: opening})

    assert out.get("movement_line_gate_waived") == "moneyline_has_no_handicap"
    assert out["movement_state"] != "no_comparable_price"
    assert out.get("movement_price_delta") is not None, "the price comparison must survive"


def test_a_prop_is_NOT_exempted_from_the_line_gate():
    """The exemption must not reintroduce the +1.0 vs -1.5 false positive."""
    row = _row(side="over", line=2.5, price=-110, fair=0.55, market="batter_hits")
    key = layer2_board.movement_join_key(row)
    opening = _opening(line=1.5, price=-110, fair=0.52, captured_at=_now_iso(30), key=key)
    out = layer2_board._movement_from_opening(row, {key: opening})
    assert out.get("movement_line_gate_waived") is None
    assert out["movement_basis"] == "line_moved"
    assert out.get("movement_price_delta") is None, "a price at a different handicap is not a price move"


def test_a_missing_opening_fair_leaves_the_row_UNSCORED_on_purpose():
    """An implied-from-price fallback was tried here and REVERTED.

    On a line-moved row the two prices belong to DIFFERENT BETS, so their
    difference measures the handicap change, not the market: home +1.0 @ -104
    (p .5098) -> home -1.5 @ +122 (p .4505) makes the probability FALL 5.94 pp
    while `_line_move_vs_pick` correctly calls the same move "toward". Sign and
    magnitude disagreed, and it reached steam.

    Better a row with no movement term than one with a confidently wrong one.
    """
    row = _row(side="over", line=9.5, price=-130, fair=0.58)
    key = layer2_board.movement_join_key(row)
    opening = _opening(line=8.5, price=110, fair=None, captured_at=_now_iso(30), key=key)
    opening.pop("fair_probability")
    out = layer2_board._movement_from_opening(row, {key: opening})
    assert out.get("movement_line_prob_delta_pp") is None
    assert out.get("steam") is not True


def test_a_present_opening_fair_still_scores():
    row = _row(side="over", line=9.5, price=-130, fair=0.58)
    key = layer2_board.movement_join_key(row)
    opening = _opening(line=8.5, price=110, fair=0.50, captured_at=_now_iso(30), key=key)
    out = layer2_board._movement_from_opening(row, {key: opening}, _curve(row, {8.5: 0.58}))
    assert out["movement_vs_pick"] == "toward"
    assert out["movement_line_prob_delta_pp"] == pytest.approx(8.0, abs=1e-6)
