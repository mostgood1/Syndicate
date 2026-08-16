"""`structured_response.top_opportunities` comes from the board artifact.

The lane this covers exists because `M1` added a board-wide TABLE while leaving
the headline reading the snapshot, so chat and the board still answered from two
pools and still disagreed (measured 23.81% vs 14.09%). The check that matters is
therefore not "is there a table" but "does the headline's max edge equal the
board's max `model_edge_pct`" -- reproduced here as
`test_regression_divergence_predicate_holds`, which is deliberately written the
same way `scripts/ask_syndicate_regression.py` writes it.

Row fixtures below are trimmed copies of real `/api/board/layer2-shortlist`
rows fetched 2026-08-15, including the side/projection-side mismatch that makes
`model_prob_over` mean the opposite of what its name says.
"""
from __future__ import annotations

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


# --- ranking: the top row must BE the board's maximum ------------------------

def test_model_bearing_rows_outrank_ev_only_rows():
    """Ranking on edge alone would drop most of the board.

    Only 19 of 105 live rows carried `model_edge_pct`. An EV-only row with a
    huge EV must still sort below the weakest model-bearing row, or the headline
    stops being the board's model headline.
    """
    ev_only = _row(model_edge_pct=None, ev_pct=99.0, projection={})
    weak_model = _row(model_edge_pct=0.1)
    assert adapter._board_rank_key(weak_model) > adapter._board_rank_key(ev_only)


def test_top_opportunities_lead_with_the_boards_max_edge(monkeypatch):
    rows = [_row(model_edge_pct=e) for e in (1.2, 6.35, -4.0, 3.1)]
    _patch_shortlist(monkeypatch, {"rows": rows})
    top = adapter._board_top_opportunities({}, {"selected_date": "2026-08-15"})
    assert [item["edge"] for item in top] == [6.35, 3.1, 1.2, -4.0]
    assert all(item["source"] == "layer2_shortlist" for item in top)


# --- the fallbacks, so an answer never gets worse than before -----------------

@pytest.mark.parametrize(
    "payload",
    [None, {}, {"rows": []}, {"rows": None}],
    ids=["reader-returned-none", "empty-payload", "no-rows", "rows-is-null"],
)
def test_absent_artifact_falls_back_rather_than_emptying_the_headline(monkeypatch, payload):
    _patch_shortlist(monkeypatch, payload)
    assert adapter._board_top_opportunities({}, {}) is None


def test_sport_filter_that_matches_nothing_falls_back(monkeypatch):
    _patch_shortlist(monkeypatch, {"rows": [_row(sport="nfl")]})
    assert adapter._board_top_opportunities({"sport": "nhl"}, {}) is None


def test_sport_filter_is_exact_so_nba_does_not_match_wnba(monkeypatch):
    _patch_shortlist(monkeypatch, {"rows": [_row(sport="wnba")]})
    assert adapter._board_top_opportunities({"sport": "nba"}, {}) is None


def test_a_raising_reader_degrades_instead_of_failing_the_answer(monkeypatch):
    import pipeline.intelligence_state as state

    def _boom(_date):
        raise RuntimeError("artifact store unavailable")

    monkeypatch.setattr(state, "read_layer2_shortlist", _boom, raising=False)
    assert adapter._board_top_opportunities({}, {}) is None


# --- the schema actually prefers the board -----------------------------------

def test_market_summary_prefers_the_board_over_the_snapshot(monkeypatch):
    _patch_shortlist(monkeypatch, {"rows": [_row(model_edge_pct=6.35)]})
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
    _patch_shortlist(monkeypatch, {"rows": [_row(model_edge_pct=6.35)]})
    schema = adapter._market_summary_schema(
        {"recommendations": []}, question="Ohtani's exact stats for tomorrow?", context={}
    )
    assert schema["top_opportunities"] == []
    assert "no opportunities" in schema["rationale_summary"]["summary"].lower()


def test_summary_reports_a_board_edge_as_a_percent_not_635(monkeypatch):
    """`Best edge 635.0%` was served live for 14 minutes.

    Snapshot rows carry `edge` as a fraction, board rows as a percent, and the
    sentence multiplied by 100 unconditionally.
    """
    _patch_shortlist(monkeypatch, {"rows": [_row(model_edge_pct=6.35)]})
    schema = adapter._market_summary_schema(
        {"recommendations": [{"selection": "x", "edge": 0.1}]}, question="biggest edges?", context={}
    )
    summary = schema["rationale_summary"]["summary"]
    # 6.3, not 6.4: 6.35 is fractionally below the tie in binary float, so
    # `.1f` rounds down. Asserting the real production value rather than a
    # tidier one keeps this honest about what the user actually sees.
    assert "Best edge 6.3%." in summary, summary
    assert "635" not in summary


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

def test_regression_divergence_predicate_holds(monkeypatch):
    """Written the way `ask_syndicate_regression.py:450-458` writes it.

    Testing my own paraphrase of the check would prove nothing about the check.
    Board truth is `max(model_edge_pct)` over the shortlist; chat's claim is
    `max(edge)` over `structured_response.top_opportunities`; the harness fails
    the case when they differ by more than 0.5.
    """
    board_rows = [_row(model_edge_pct=e) for e in (1.2, 6.35, -4.0, 3.1, 5.9)]
    _patch_shortlist(monkeypatch, {"rows": board_rows})

    board_top = max(r["model_edge_pct"] for r in board_rows)
    schema = adapter._market_summary_schema(
        {"recommendations": [{"selection": "SNAPSHOT", "edge": 13.59}]},
        question="What are the biggest edges on the board tonight?",
        context={},
    )
    claimed = [float(r["edge"]) for r in schema["top_opportunities"] if isinstance(r.get("edge"), (int, float))]
    top_claimed_pct = max(claimed) * 100.0 if max(claimed) < 1.5 else max(claimed)

    assert abs(top_claimed_pct - board_top) <= 0.5, (
        f"top_edge_diverges_from_board:{top_claimed_pct:.2f}_vs_{board_top:.2f}"
    )
