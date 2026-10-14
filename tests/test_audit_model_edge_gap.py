"""The gap attribution: each branch, and the two instrument defects it reports.

Every case below is a shape MEASURED on the served board 2026-10-14 23:26-23:36Z,
not an invented one. The branch counts that session found, over 809 gap rows:

    464  57.4%  CEILING: |edge| > 15 points
    291  36.0%  no probability at all: nothing to price
     48   5.9%  no market fair probability (model prob present)
      3   0.4%  no model probability (market fair present)
      3   0.4%  NOT AN OPPOSITE: projected 'home' vs row side 'draw'

The grader is tested on the verdict TEXT rather than `verdict_class` because
those two disagree on 308 served rows -- 305 of them NCAAF rows reading
"loses to the closing line by 2.86 points of total MAE" under
`verdict_class: measured`. A consumer filtering on the class admits all 308.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.audit_model_edge_gap import (  # noqa: E402
    GRADE_BEATS,
    GRADE_LOSES,
    GRADE_NEVER,
    GRADE_NO_BLOCK,
    GRADE_PARITY,
    GRADES_WITHOUT_DEMONSTRATED_EDGE,
    classify_gap_row,
    grade_skill,
)


@pytest.fixture(scope="module")
def board():
    from syndicate.features.shared import layer2_board

    return layer2_board


def _row(side="over", **projection):
    return {"side": side, "model_edge_pct": None, "projection": dict(projection)}


# --------------------------------------------------------------------------
# branch attribution
# --------------------------------------------------------------------------

def test_ceiling_branch_is_named_and_carries_the_live_constant(board):
    """The MLB row measured at 23:30Z: edge 15.87 against a 15.0 ceiling."""
    row = _row(edge_vs_market_pct=15.87, model_prob_over=0.728, market_fair_prob_over=0.5693)
    got = classify_gap_row(row, board)
    assert got.startswith("CEILING"), got
    assert str(board._MODEL_EDGE_MAX_POINTS).rstrip("0").rstrip(".") in got, got


def test_an_edge_just_under_the_ceiling_is_not_the_ceiling_branch(board):
    """Guards the boundary: the bound is `>`, not `>=`."""
    row = _row(edge_vs_market_pct=board._MODEL_EDGE_MAX_POINTS,
               model_prob_over=0.6, market_fair_prob_over=0.5)
    assert not classify_gap_row(row, board).startswith("CEILING")


def test_no_probability_at_all_is_the_soccer_corners_shape(board):
    """291 of 809: `projected` with neither probability -- nothing to price."""
    row = _row(projected=10.324, edge_vs_market_pct=None,
               model_prob_over=None, market_fair_prob_over=None)
    assert classify_gap_row(row, board) == "no probability at all: nothing to price"


def test_model_prob_present_but_no_market_fair_is_its_own_branch(board):
    row = _row(side="away", edge_vs_market_pct=None,
               model_prob_over=0.44, market_fair_prob_over=None)
    assert classify_gap_row(row, board) == "no market fair probability (model prob present)"


def test_market_fair_present_but_no_model_prob_is_the_nhl_puckline_shape(board):
    """The hockeysim rows: a market fair exists, the sim prices only one side."""
    row = _row(side="away", edge_vs_market_pct=None,
               model_prob_over=None, market_fair_prob_over=0.327)
    assert classify_gap_row(row, board) == "no model probability (market fair present)"


def test_a_modelled_fair_fallback_should_not_present_as_a_gap(board):
    """If the fallback priced it, the row should carry an edge -- say so loudly."""
    row = _row(edge_vs_market_pct=None, edge_vs_modelled_fair_pct=4.2)
    assert "should NOT be a gap row" in classify_gap_row(row, board)


def test_a_row_with_no_projection_mapping_is_not_silently_bucketed(board):
    assert classify_gap_row({"side": "over", "projection": None}, board) == "no projection mapping"
    assert classify_gap_row({"side": "over", "projection": "nope"}, board) == "no projection mapping"


def test_every_branch_string_is_distinct(board):
    """Two branches sharing a label would merge in the histogram and hide one."""
    rows = [
        _row(edge_vs_market_pct=99.0, model_prob_over=0.9, market_fair_prob_over=0.1),
        _row(projected=1.0),
        _row(edge_vs_market_pct=None, model_prob_over=0.4, market_fair_prob_over=None),
        _row(edge_vs_market_pct=None, model_prob_over=None, market_fair_prob_over=0.3),
        _row(edge_vs_market_pct=None, edge_vs_modelled_fair_pct=1.0),
        {"side": "over", "projection": None},
    ]
    labels = [classify_gap_row(r, board) for r in rows]
    assert len(set(labels)) == len(labels), labels


# --------------------------------------------------------------------------
# the skill grader, and the vocabulary defect it exists to expose
# --------------------------------------------------------------------------

def test_a_losing_verdict_under_a_measured_class_grades_as_losing():
    """The 305-row NCAAF case: this is the whole reason the grader reads text."""
    row = {"projection": {"model_skill": {
        "verdict_class": "measured",
        "verdict": "loses to the closing line by 2.86 points of total MAE "
                   "[+1.12, +4.59] over 100 games; 2.48x over-dispersed and 4.6 points high",
    }}}
    grade, cls = grade_skill(row)
    assert grade == GRADE_LOSES
    assert cls == "measured", "the class must still be returned so the caller can report the clash"


def test_never_backtested_wins_over_everything():
    row = {"projection": {"model_skill": {
        "verdict_class": "unmeasured",
        "verdict": "model never backtested -- projection is unvalidated",
    }}}
    assert grade_skill(row)[0] == GRADE_NEVER


def test_parity_text_is_not_graded_as_a_loss():
    row = {"projection": {"model_skill": {
        "verdict_class": "parity",
        "verdict": "parity with the market: Brier -0.003 [-0.009, +0.003] over 1,266 player-games",
    }}}
    assert grade_skill(row)[0] == GRADE_PARITY


def test_a_parity_verdict_that_also_says_point_worse_grades_as_a_loss():
    """The MLB run-line verdict: 'parity with the close, POINT WORSE'.

    An explicit loss beats a bare parity mention, or the grade reads kinder than
    the sentence it came from.
    """
    row = {"projection": {"model_skill": {
        "verdict_class": "parity",
        "verdict": "parity with the close, point worse: run line Brier +0.008 [-0.006, +0.021]",
    }}}
    assert grade_skill(row)[0] == GRADE_LOSES


def test_beats_the_market_is_available_as_a_grade():
    """Zero served rows graded this on 2026-10-14 -- so pin that it CAN be reached.

    A grade no fixture produces is indistinguishable from a grade the code
    cannot produce, and 'beats the market: 0' is the headline number.
    """
    row = {"projection": {"model_skill": {
        "verdict_class": "measured",
        "verdict": "beats the de-vigged close: Brier -0.012 [-0.020, -0.004] over 900 lines",
    }}}
    assert grade_skill(row)[0] == GRADE_BEATS


def test_a_verdict_that_both_beats_and_loses_is_not_graded_as_a_win():
    row = {"projection": {"model_skill": {
        "verdict": "beats the opener but loses to the closing line",
    }}}
    assert grade_skill(row)[0] == GRADE_LOSES


def test_a_missing_skill_block_is_graded_not_dropped():
    assert grade_skill({"projection": {}})[0] == GRADE_NO_BLOCK
    assert grade_skill({"projection": None})[0] == GRADE_NO_BLOCK


def test_the_weak_grades_tuple_covers_both_and_excludes_parity():
    assert set(GRADES_WITHOUT_DEMONSTRATED_EDGE) == {GRADE_LOSES, GRADE_NEVER}
    assert GRADE_PARITY not in GRADES_WITHOUT_DEMONSTRATED_EDGE
    assert GRADE_BEATS not in GRADES_WITHOUT_DEMONSTRATED_EDGE


# --------------------------------------------------------------------------
# the global-counter defect
# --------------------------------------------------------------------------

def test_the_counter_keys_checked_are_the_ones_the_payload_actually_returns():
    """Pins the four keys measured identical across all 8 sports at 23:36Z.

    If the payload renames one, this fails rather than the check quietly
    comparing four `None`s and reporting 'GLOBAL' for every board forever.
    """
    from scripts.audit_model_edge_gap import GLOBAL_COUNTER_KEYS

    assert set(GLOBAL_COUNTER_KEYS) == {
        "rows_uninformative_ev", "rows_admitted_by_blend",
        "rows_below_value_floor", "opportunities_considered",
    }


def test_identical_signatures_across_sports_are_detectable():
    """The shape the check keys on, without needing a live board."""
    import json

    from scripts.audit_model_edge_gap import GLOBAL_COUNTER_KEYS

    payload = {k: 1234 for k in GLOBAL_COUNTER_KEYS}
    sig_a = json.dumps({k: payload.get(k) for k in GLOBAL_COUNTER_KEYS}, sort_keys=True, default=str)
    sig_b = json.dumps({k: payload.get(k) for k in GLOBAL_COUNTER_KEYS}, sort_keys=True, default=str)
    assert sig_a == sig_b
    differing = dict(payload, rows_uninformative_ev=7)
    sig_c = json.dumps({k: differing.get(k) for k in GLOBAL_COUNTER_KEYS}, sort_keys=True, default=str)
    assert sig_c != sig_a


# --------------------------------------------------------------------------
# the cap rule
# --------------------------------------------------------------------------

def test_a_truncated_page_is_never_reported_as_a_share():
    from scripts.audit_model_edge_gap import LIMIT, _rows_and_cap

    rows = [{"x": i} for i in range(LIMIT)]
    _, _, cap_ok = _rows_and_cap({"rows": rows, "total_rows": LIMIT + 1})
    assert cap_ok is False
    _, _, cap_ok = _rows_and_cap({"rows": rows[:10], "total_rows": 10})
    assert cap_ok is True


def test_a_missing_total_rows_falls_back_to_the_limit_not_to_trust():
    from scripts.audit_model_edge_gap import LIMIT, _rows_and_cap

    _, _, cap_ok = _rows_and_cap({"rows": [{"x": i} for i in range(LIMIT)]})
    assert cap_ok is False, "a full page with no total_rows must not be trusted"
    _, _, cap_ok = _rows_and_cap({"rows": [{"x": 1}]})
    assert cap_ok is True
