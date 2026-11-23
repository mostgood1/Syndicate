"""`structured_response.top_opportunities` comes from the board artifact.

The lane this covers exists because `M1` added a board-wide TABLE while leaving
the headline reading the snapshot, so chat and the board still answered from two
pools and still disagreed (measured 23.81% vs 14.09%). The check that matters is
therefore not "is there a table" but "is the headline the board's own picks,
in the board's order" -- reproduced here as `test_regression_top_pick_predicate_holds`,
written the way `scripts/ask_syndicate_regression.py` writes it. (Until todo
#861, 2026-11-23, the predicate was "headline max edge == board max
`model_edge_pct`", which made losing models the headline.)

Row fixtures below are trimmed copies of real `/api/board/layer2-shortlist`
rows fetched 2026-08-15, including the side/projection-side mismatch that makes
`model_prob_over` mean the opposite of what its name says.
"""
from __future__ import annotations

from unittest import mock

import pytest

from syndicate.blueprints import ask_the_syndicate_adapter as adapter


def _row(**over):
    row = {
        "sport": "nfl",
        "market": "totals",
        "side": "over",
        "line": 39.5,
        "player_name": None,
        "home_team": "Buffalo Bills",
        "away_team": "Carolina Panthers",
        "model_edge_pct": 6.35,
        "ev_pct": -2.8895,
        "score": {"score": 5.0178},
        "projection": {
            "side": "over",
            "model_prob_over": 0.5442,
            "market_fair_prob_over": 0.4807,
        },
    }
    row.update(over)
    return row


def _patch_shortlist(monkeypatch, payload):
    import pipeline.intelligence_state as state

    monkeypatch.setattr(state, "read_layer2_shortlist", lambda _date: payload, raising=False)


# --- the probability mapping, which is where a wrong number would come from ---

def test_probability_is_taken_directly_when_sides_agree():
    model_pct, market_pct = adapter._board_row_probabilities(_row())
    assert (model_pct, market_pct) == (54.42, 48.07)


def test_probability_is_complemented_when_the_row_side_opposes_the_projection():
    """The case that makes the field's name a lie.

    Real shape: a row whose own side is `under` carrying an `over` projection.
    Its stated edge is the NEGATIVE of `model_prob_over - market_fair_prob_over`,
    so the row's own probability is the complement. 10 of 19 live model-bearing
    rows looked like this -- taking the field at its name gets the majority wrong.
    """
    row = _row(side="under", model_edge_pct=-6.35)
    model_pct, market_pct = adapter._board_row_probabilities(row)
    assert (model_pct, market_pct) == (45.58, 51.93)


def test_probability_is_absent_when_it_cannot_be_reconciled_to_the_row_edge():
    """Absent, never invented -- the house rule for published probabilities."""
    row = _row(model_edge_pct=99.0)
    assert adapter._board_row_probabilities(row) == (None, None)


def test_probability_is_absent_when_the_projection_block_is_missing():
    assert adapter._board_row_probabilities(_row(projection={})) == (None, None)


# --- ranking: the headline is the BOARD'S picks, in the board's order ----------
#
# `[2026-11-23, lane surface-consistency-oversight, todo #861]`. This section
# used to assert that the headline led with the board's MAX `model_edge_pct`,
# and that model-bearing rows outrank EV-only rows. On the fleet 2026-11-23 that
# rule put 22-28 point "edges" from models measured to LOSE to the market at
# the top of Ask, above every row the board Suggested. The board's own flag
# (`_stamp_suggested`) and its own score are now the contract.

def test_board_picks_outrank_non_picks_whatever_their_model_edge():
    """The measured case: a non-pick with a 28-point model edge and a high score
    must sort below a Suggested row with a modest score."""
    losing_model = _row(model_edge_pct=28.15, ev_pct=-8.3, score={"score": 3.6}, suggested=False)
    pick = _row(model_edge_pct=None, ev_pct=4.1, score={"score": 2.1}, suggested=True, projection={})
    assert adapter._board_pick_rank_key(pick) > adapter._board_pick_rank_key(losing_model)
    stronger_pick = _row(ev_pct=3.0, score={"score": 2.5}, suggested=True)
    assert adapter._board_pick_rank_key(stronger_pick) > adapter._board_pick_rank_key(pick)


def test_top_opportunities_are_the_boards_picks_in_board_order(monkeypatch):
    rows = [
        _row(model_edge_pct=1.2, ev_pct=2.0, score={"score": 1.0}, suggested=True),
        _row(model_edge_pct=28.15, ev_pct=-8.3, score={"score": 3.6}, suggested=False,
             suggested_reasons=["ev_below_min"]),
        _row(model_edge_pct=-4.0, ev_pct=4.5, score={"score": 2.4}, suggested=True),
        _row(model_edge_pct=3.1, ev_pct=3.0, score={"score": 1.8}, suggested=True),
        _row(model_edge_pct=9.0, ev_pct=1.0, score={"score": 9.9}, suggested=False,
             suggested_reasons=["suspect_stale_quote", "ev_below_min"]),
    ]
    _patch_shortlist(monkeypatch, {"rows": rows})
    top, excluded = adapter._board_top_opportunities({}, {"selected_date": "2026-08-15"})
    # board order (score), not model edge; the -4.0 model edge is the board's
    # pick on price and is published, with the sim's view in its prose
    assert [item["EV"] for item in top] == [4.5, 3.0, 2.0]
    assert [item["board_rank"] for item in top] == [1, 2, 3]
    assert all(item["suggested"] is True and item["source"] == "layer2_shortlist" for item in top)
    assert (excluded.count, excluded.considered) == (2, 5)
    assert dict(excluded.reasons) == {"ev_below_min": 2, "suspect_stale_quote": 1}


# --- the fallbacks, so an answer never gets worse than before -----------------
#
# `#517` made every branch return a 2-tuple, `(rows_or_None, exclusion)`; the
# import-failure branch once returned a bare None and the destructuring caller
# raised instead of degrading. Since todo #861 the second term is a
# `_BoardExclusion` (count, considered, sport, the board's reasons), so the
# answer can say WHY the board picks nothing rather than a bare "nothing".

_NOTHING = adapter._BoardExclusion()


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"rows": []}, {"rows": None}],
    ids=["reader-returned-none", "empty-payload", "no-rows", "rows-is-null"],
)
def test_absent_artifact_falls_back_rather_than_emptying_the_headline(monkeypatch, payload):
    _patch_shortlist(monkeypatch, payload)
    assert adapter._board_top_opportunities({}, {}) == (None, _NOTHING)


def test_a_sport_with_no_board_lines_is_an_explained_empty_answer(monkeypatch):
    """Not a fallback any more: the snapshot is cross-sport, and an NHL question
    must not be answered with NFL rows (todo #861)."""
    _patch_shortlist(monkeypatch, {"rows": [_row(sport="nfl", suggested=True, ev_pct=3.0)]})
    top, excluded = adapter._board_top_opportunities({"sport": "nhl"}, {})
    assert top == [] and excluded.no_rows_for_sport and excluded.sport == "nhl"


def test_sport_filter_is_exact_so_nba_does_not_match_wnba(monkeypatch):
    _patch_shortlist(monkeypatch, {"rows": [_row(sport="wnba", suggested=True, ev_pct=3.0)]})
    top, excluded = adapter._board_top_opportunities({"sport": "nba"}, {})
    assert top == [] and excluded.no_rows_for_sport


def test_an_unimportable_reader_degrades_instead_of_raising_typeerror(monkeypatch):
    """`#517`. The import-failure branch returned a BARE `None` while every
    other branch -- and the sole caller, which destructures -- uses a 2-tuple.
    So the one path written to DEGRADE an answer raised `TypeError: cannot
    unpack non-sequence NoneType` instead, turning a soft failure hard.

    Untested until now because the other degradation path (`read_layer2_
    shortlist` raising) returns the tuple correctly, so the two read as one
    case. They are not: this one fires when the MODULE cannot be imported at
    all, which is what a broken environment produces.
    """
    import sys

    with mock.patch.dict(sys.modules, {"pipeline.intelligence_state": None}):
        assert adapter._board_top_opportunities({}, {}) == (None, _NOTHING)


def test_a_raising_reader_degrades_instead_of_failing_the_answer(monkeypatch):
    import pipeline.intelligence_state as state

    def _boom(_date):
        raise RuntimeError("artifact store unavailable")

    monkeypatch.setattr(state, "read_layer2_shortlist", _boom, raising=False)
    assert adapter._board_top_opportunities({}, {}) == (None, _NOTHING)


# --- the schema actually prefers the board -----------------------------------

def test_market_summary_prefers_the_board_over_the_snapshot(monkeypatch):
    _patch_shortlist(monkeypatch, {"rows": [_row(model_edge_pct=6.35, ev_pct=2.81, suggested=True)]})
    snapshot = {"recommendations": [{"selection": "SNAPSHOT ROW", "edge": 13.59}]}
    schema = adapter._market_summary_schema(snapshot, question="biggest edges?", context={})
    edges = [item["edge"] for item in schema["top_opportunities"]]
    assert edges == [6.35]
    assert "SNAPSHOT ROW" not in [item.get("selection") for item in schema["top_opportunities"]]


def test_an_empty_snapshot_is_a_refusal_and_the_board_must_not_fill_it(monkeypatch):
    """The regression this file exists to prevent a second time.

    Deployed and reverted 2026-08-15. An empty `recommendations` list is the
    engine DECLINING, and the served answer becomes "No opportunities are on
    the board right now" -- which is how a refusal reaches the user. Sourcing
    from the board unconditionally answered "Ohtani's exact stats for
    tomorrow's game" with five unrelated NFL totals (refusal 4/8 -> 3/8 against
    a same-slate control). The board may REPLACE a pool, never create one.
    """
    _patch_shortlist(monkeypatch, {"rows": [_row(model_edge_pct=6.35, ev_pct=2.81, suggested=True)]})
    schema = adapter._market_summary_schema(
        {"recommendations": []}, question="Ohtani's exact stats for tomorrow?", context={}
    )
    assert schema["top_opportunities"] == []
    assert "no opportunities" in schema["rationale_summary"]["summary"].lower()


def test_summary_reports_board_ev_as_a_percent_not_281(monkeypatch):
    """`Best edge 635.0%` was served live for 14 minutes, when the sentence
    multiplied a percent by 100. Board rows now lead with EV at the posted price
    (todo #861), and the same scale rule holds: a percent is printed as one.
    """
    _patch_shortlist(monkeypatch, {"rows": [_row(model_edge_pct=6.35, ev_pct=2.81, suggested=True)]})
    schema = adapter._market_summary_schema(
        {"recommendations": [{"selection": "x", "edge": 0.1}]}, question="biggest edges?", context={}
    )
    summary = schema["rationale_summary"]["summary"]
    assert "Showing the board's top 1 suggested bet in NFL" in summary, summary
    assert "Best EV +2.8% at the posted price." in summary, summary
    assert "281" not in summary and "635" not in summary


def test_snapshot_rows_still_get_the_fraction_conversion():
    """The other half: a fraction-scaled snapshot row must not become 0.1%."""
    sentence = adapter._board_summary_sentence([{"sport": "mlb", "edge": 0.1359}])
    assert "Best edge 13.6%." in sentence, sentence


def test_market_summary_keeps_the_snapshot_when_the_board_has_nothing(monkeypatch):
    _patch_shortlist(monkeypatch, {"rows": []})
    snapshot = {"recommendations": [{"selection": "SNAPSHOT ROW", "edge": 13.59}]}
    schema = adapter._market_summary_schema(snapshot, question="biggest edges?", context={})
    assert [item["selection"] for item in schema["top_opportunities"]] == ["SNAPSHOT ROW"]


# --- the predicate the lane is actually judged by ----------------------------

def test_regression_top_pick_predicate_holds(monkeypatch):
    """Written the way `ask_syndicate_regression.py`'s `top_pick_matches_board`
    writes it, with the SAME two predicates imported from the adapter.

    Board truth is the EV of the highest-ranked board pick; chat's claim is the
    EV of the headline's first row; the harness fails the case when they differ
    by more than 0.5, or when that row is not a board pick.
    """
    board_rows = [
        _row(model_edge_pct=1.2, ev_pct=2.0, score={"score": 1.0}, suggested=True),
        _row(model_edge_pct=28.15, ev_pct=-8.3, score={"score": 3.6}, suggested=False),
        _row(model_edge_pct=3.1, ev_pct=3.4, score={"score": 2.2}, suggested=True),
    ]
    _patch_shortlist(monkeypatch, {"rows": board_rows})
    picks = sorted(
        (r for r in board_rows if adapter._is_board_pick(r)), key=adapter._board_pick_rank_key, reverse=True
    )
    schema = adapter._market_summary_schema(
        {"recommendations": [{"selection": "SNAPSHOT", "edge": 13.59}]},
        question="What are the biggest edges on the board tonight?",
        context={},
    )
    first = schema["top_opportunities"][0]
    assert first["suggested"] is True
    assert abs(float(first["EV"]) - float(picks[0]["ev_pct"])) <= 0.5
