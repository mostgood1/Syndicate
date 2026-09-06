"""The query payload's opt-in row-diagnostic drop.

WHY THIS EXISTS. `/api/intelligence/query` is **81% of web's chronic egress**
(measured 2026-09-06: 131.1 MB of 162.3 MB of edge traffic over a spike-free
6-hour window, 59 calls, median 2.53 MB each -- and that median is ALREADY
gzipped). `trace` and `score_breakdown` ride on every row of three 2,004-row
lists and NOTHING reads them.

The order here is deliberate (`learnings.md`, reachability before correctness):
first that the flag actually changes the payload, then that it drops the right
things, then the four ways it must decline to act.
"""

from __future__ import annotations

import copy

import pytest

from syndicate.blueprints import intelligence as intel


def _row(**extra):
    row = {
        "sport": "mlb",
        "market": "h2h",
        "side": "home",
        "board_score_components": {"a": 1},
        "quote": {"fair_probability": 0.5},
        "trace": {"steps": ["a"] * 40},
        "score_breakdown": {"parts": ["b"] * 40},
    }
    row.update(extra)
    return row


def _payload():
    rows = [_row(), _row(side="away")]
    return {
        "top_opportunities": copy.deepcopy(rows),
        "ranked_all": copy.deepcopy(rows),
        "recommendations": copy.deepcopy(rows),
        "board_contract": {"cards": copy.deepcopy(rows), "lane_counts": {"mlb": 2}},
    }


def test_the_flag_is_OFF_unless_asked():
    """Absent means NO. Dropping keys is a contract change."""
    assert intel._row_diagnostics_drop_requested({}) is False
    assert intel._row_diagnostics_drop_requested({"drop_row_diagnostics": False}) is False
    assert intel._row_diagnostics_drop_requested(None) is False
    assert intel._row_diagnostics_drop_requested({"drop_row_diagnostics": True}) is True


def test_off_and_on_differ_and_the_saving_is_real():
    """off != on, asserted on SIZE -- a drop that saves nothing is inert."""
    import json

    before = _payload()
    after = intel._drop_unconsumed_row_diagnostics(before)

    assert len(json.dumps(after)) < len(json.dumps(before)) * 0.7
    # and the input was not mutated -- the caller may still need it
    assert "trace" in before["ranked_all"][0]


def test_it_drops_from_ALL_THREE_lists_and_the_nested_cards():
    """The payload carries the same rows four ways; missing one leaks 25%."""
    out = intel._drop_unconsumed_row_diagnostics(_payload())

    for key in ("top_opportunities", "ranked_all", "recommendations"):
        for row in out[key]:
            assert "trace" not in row, key
            assert "score_breakdown" not in row, key
    for row in out["board_contract"]["cards"]:
        assert "trace" not in row
        assert "score_breakdown" not in row


def test_it_KEEPS_everything_a_consumer_reads():
    """`board_score_components` looks like the same kind of field and is NOT
    droppable: `intelligence.html:~3085` reads it. So does `quote`, in both
    consumers."""
    out = intel._drop_unconsumed_row_diagnostics(_payload())

    row = out["ranked_all"][0]
    assert row["board_score_components"] == {"a": 1}
    assert row["quote"] == {"fair_probability": 0.5}
    assert row["sport"] == "mlb" and row["market"] == "h2h" and row["side"] == "home"
    # untouched siblings of `cards` survive
    assert out["board_contract"]["lane_counts"] == {"mlb": 2}


def test_it_DECLARES_what_it_dropped():
    """A missing key must not read as "the server had no value" -- that is a
    different fact and the one that sends someone debugging upstream."""
    out = intel._drop_unconsumed_row_diagnostics(_payload())
    assert out["_dropped_row_fields"] == ["trace", "score_breakdown"]


def test_it_stays_SILENT_when_it_dropped_nothing():
    """No declaration on a payload that never carried the fields, so the key's
    presence always means a real drop happened."""
    clean = {"ranked_all": [{"sport": "mlb", "quote": {}}]}
    out = intel._drop_unconsumed_row_diagnostics(clean)
    assert "_dropped_row_fields" not in out


@pytest.mark.parametrize("bad", [None, [], "nope", 42])
def test_it_never_raises_on_a_shape_it_did_not_expect(bad):
    """This runs in a request path; a size optimisation must never 500."""
    assert intel._drop_unconsumed_row_diagnostics(bad) is bad


def test_a_row_list_that_is_not_a_list_is_left_alone():
    out = intel._drop_unconsumed_row_diagnostics({"ranked_all": {"not": "a list"}})
    assert out["ranked_all"] == {"not": "a list"}


def test_lists_NOT_named_are_untouched():
    """Named explicitly rather than walked, so a future list elsewhere in the
    payload is not silently stripped by this function."""
    payload = {"some_other_list": [_row()]}
    out = intel._drop_unconsumed_row_diagnostics(payload)
    assert "trace" in out["some_other_list"][0]
