"""The join from a committed position to its recorded opening.

This is the piece Stage C's gate rests on, and the piece the settlement join
got wrong at a cost of 4,560 `no_key_match` of 8,276. So the tests here are
mostly about the failure directions: a key that drifts, a key that cannot be
built, an opening that is not there. A test that only proves the happy path
would have passed on the broken settlement join too.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.clv_opening_ledger import _opening_key
from syndicate.features.shared.clv_position_join import (
    join_positions_to_openings,
    join_report_line,
    opening_key_for_position,
    opening_key_for_row,
)


def _row(**overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "kind": "prop",
        "market": "batter_hits",
        "segment": "full_game",
        "player_name": "Test Batter",
        "home_team": "HOU",
        "away_team": "SEA",
        "side": "Over",
        "line": 0.5,
        "quote": {"bookmaker": "DraftKings", "price": -125},
    }
    row.update(overrides)
    return row


def _position_from(row, **overrides):
    """The subset `commit_portfolio` actually stores, shaped as it stores it."""
    position = {
        "position_key": "abc123",
        "event_id": row.get("event_id"),
        "market": row.get("market"),
        "player_name": row.get("player_name"),
        "segment": row.get("segment"),
        "side": row.get("side"),
        "line": row.get("line"),
        "book": (row.get("quote") or {}).get("bookmaker"),
    }
    position.update(overrides)
    return position


def _opening(row, **overrides):
    record = {
        "key": _opening_key(row),
        "price": -125,
        "bookmaker": "draftkings",
        "captured_at": "2026-08-22T18:00:00Z",
    }
    record.update(overrides)
    return record


# --- the derivation itself -------------------------------------------------


def test_derived_key_equals_the_row_key():
    """The claim the whole module rests on, stated as a test rather than a comment."""
    row = _row()
    assert opening_key_for_position(_position_from(row)) == opening_key_for_row(row)


@pytest.mark.parametrize(
    "field,row_value,position_value",
    [
        ("side", "Over", "over"),
        ("market", "Batter_Hits", "batter_hits"),
        ("player_name", "Test Batter", "test batter"),
    ],
)
def test_case_differences_cannot_break_the_join(field, row_value, position_value):
    """Both sides normalise through `_opening_key`, so case drift is impossible.

    This is the point of calling the ledger's own function instead of
    reimplementing it -- these cases are not handled, they are unreachable.
    """
    row = _row(**{field: row_value})
    position = _position_from(row, **{field: position_value})
    assert opening_key_for_position(position) == opening_key_for_row(row)


def test_the_book_remap_is_load_bearing():
    """`book` -> `quote.bookmaker` is the one hand-written step; prove it works.

    A position that dropped the book would key to a DIFFERENT market, not to
    none -- it would match some other book's opening and produce a plausible,
    wrong CLV. That is worse than no match, so it is worth its own test.
    """
    row = _row()
    right = _position_from(row)
    wrong = _position_from(row, book=None)
    assert opening_key_for_position(right) == opening_key_for_row(row)
    assert opening_key_for_position(wrong) != opening_key_for_row(row)


def test_line_is_compared_numerically_not_textually():
    # 0.5 and "0.5" are the same bet. A string key would make them different.
    row = _row(line=0.5)
    assert opening_key_for_position(_position_from(row, line="0.5")) == opening_key_for_row(row)


def test_different_lines_are_different_bets():
    over_15 = _row(line=1.5)
    over_25 = _row(line=2.5)
    assert opening_key_for_row(over_15) != opening_key_for_row(over_25)


def test_a_position_with_no_event_id_is_unkeyable_not_wrong():
    assert opening_key_for_position(_position_from(_row(), event_id=None)) is None


# --- the join --------------------------------------------------------------


def test_matched_position_carries_the_opening_price():
    row = _row()
    report = join_positions_to_openings(
        [_position_from(row)], date="2026-08-22", openings=[_opening(row)]
    )
    assert report["matched"] == 1
    assert report["no_key_match"] == 0
    assert report["match_rate"] == 1.0
    assert report["rows"][0]["opening"]["price"] == -125
    assert report["rows"][0]["join_reason"] == "matched"


def test_a_position_with_no_opening_is_named_not_dropped():
    report = join_positions_to_openings(
        [_position_from(_row())], date="2026-08-22", openings=[]
    )
    assert report["matched"] == 0
    assert report["no_key_match"] == 1
    assert len(report["rows"]) == 1
    assert report["rows"][0]["join_reason"] == "no_key_match"
    assert report["rows"][0]["opening"] is None


def test_an_unkeyable_position_is_counted_separately_from_a_missing_opening():
    """Two different problems: we cannot ask the question, vs we asked and got nothing."""
    row = _row()
    report = join_positions_to_openings(
        [_position_from(row, event_id=None), _position_from(_row(event_id="other"))],
        date="2026-08-22",
        openings=[_opening(row)],
    )
    assert report["unkeyable"] == 1
    assert report["no_key_match"] == 1
    assert report["matched"] == 0


def test_every_counter_is_present_even_when_nothing_matched():
    """A counter that only appears when it fires cannot prove the job ran."""
    report = join_positions_to_openings([], date="2026-08-22", openings=[])
    for field in (
        "positions", "openings_loaded", "matched", "no_key_match", "unkeyable",
        "stamped_present", "stamped_matched", "derived_matched",
        "derivation_agrees", "derivation_disagrees",
    ):
        assert field in report, field
    assert report["match_rate"] is None  # not 0.0 -- there was nothing to match


def test_stamped_key_is_preferred_over_the_derivation():
    """The stamp is exact; the derivation is a reconstruction. Trust the stamp."""
    row = _row()
    position = _position_from(row, opening_key=_opening_key(row), event_id="corrupted")
    report = join_positions_to_openings(
        [position], date="2026-08-22", openings=[_opening(row)]
    )
    assert report["matched"] == 1
    assert report["stamped_matched"] == 1


def test_a_drifting_derivation_is_reported_with_an_example():
    """The measurement this module exists to take.

    A count says the derivation is wrong; the example says which key it built,
    which is the only form anybody can act on.
    """
    row = _row()
    position = _position_from(row, opening_key=_opening_key(row), side="Under")
    report = join_positions_to_openings(
        [position], date="2026-08-22", openings=[_opening(row)]
    )
    assert report["derivation_disagrees"] == 1
    assert report["derivation_agrees"] == 0
    assert report["disagreement_examples"][0]["position_key"] == "abc123"
    assert "side=under" in report["disagreement_examples"][0]["derived"]


def test_agreement_is_counted_when_both_keys_exist():
    row = _row()
    position = _position_from(row, opening_key=_opening_key(row))
    report = join_positions_to_openings(
        [position], date="2026-08-22", openings=[_opening(row)]
    )
    assert report["derivation_agrees"] == 1
    assert report["derivation_disagrees"] == 0


def test_an_unstamped_position_is_not_a_disagreement():
    """A plan committed before stamping existed is old, not broken."""
    report = join_positions_to_openings(
        [_position_from(_row())], date="2026-08-22", openings=[_opening(_row())]
    )
    assert report["stamped_present"] == 0
    assert report["derivation_disagrees"] == 0
    assert report["derived_matched"] == 1


def test_duplicate_openings_keep_the_first_sighting():
    row = _row()
    report = join_positions_to_openings(
        [_position_from(row)],
        date="2026-08-22",
        openings=[_opening(row, price=-125), _opening(row, price=+200)],
    )
    assert report["openings_loaded"] == 2
    assert report["openings_distinct_keys"] == 1
    assert report["rows"][0]["opening"]["price"] == -125


def test_report_line_names_every_counter_that_would_trigger_action():
    row = _row()
    line = join_report_line(
        join_positions_to_openings([_position_from(row)], date="2026-08-22", openings=[])
    )
    assert "CLV_POSITION_JOIN" in line
    for token in ("date=", "positions=", "matched=", "no_key_match=", "derivation_disagrees="):
        assert token in line, token


# --- the stamp, end to end -------------------------------------------------


def test_commit_portfolio_stamps_a_key_that_matches_the_ledgers_own():
    """The stamp and the ledger must agree on the SAME row, or Stage C is dead."""
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    row = _row(
        ev_pct=6.0,
        model_edge_pct=3.0,
        # `price_reliability` lives under `score`, not on the quote -- the sizer
        # refuses `no_price_reliability` otherwise, which is the refusal that
        # made an earlier version of this test skip instead of run.
        score={"score": 61.25, "price_reliability": 0.9},
    )
    plan = commit_portfolio([row], selected_date="2026-08-22")
    positions = plan.get("positions") or []
    assert positions, f"row did not size into a position: {plan.get('refusals')}"
    assert positions[0]["opening_key"] == _opening_key(row)


def test_a_committed_plan_joins_to_the_openings_recorded_from_the_same_rows():
    """End to end, on the same rows: commit, then join. This is the real check.

    Everything else here tests a piece. This tests the claim Stage C needs --
    that a plan committed from a board and the openings recorded from that same
    board actually meet.
    """
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    rows = [
        _row(ev_pct=6.0, model_edge_pct=3.0, score={"score": 61.25, "price_reliability": 0.9}),
        _row(
            event_id="evt-2",
            player_name="Other Batter",
            side="Under",
            line=1.5,
            ev_pct=5.0,
            model_edge_pct=2.5,
            score={"score": 55.0, "price_reliability": 0.8},
        ),
    ]
    plan = commit_portfolio(rows, selected_date="2026-08-22")
    positions = plan.get("positions") or []
    assert positions, plan.get("refusals")

    openings = [_opening(row, key=_opening_key(row)) for row in rows]
    report = join_positions_to_openings(positions, date="2026-08-22", openings=openings)

    assert report["matched"] == len(positions)
    assert report["no_key_match"] == 0
    assert report["unkeyable"] == 0
    # Both keys exist on every position, and they agree. If this ever fails,
    # the derivation drifted and every pre-stamp order is unjoinable.
    assert report["derivation_agrees"] == len(positions)
    assert report["derivation_disagrees"] == 0
    assert report["derived_matched"] == len(positions)
