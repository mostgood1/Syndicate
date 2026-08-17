"""The board-state caller must not build analytics it never reads.

Stack dump 2026-08-17 03:48Z named `build_intelligence_evaluation_bundle` as the
allocator in two frames -- `_latest_by_recommendation_id` over the 830MB chunk
stream, and `_aggregate_performance_rows`. Both serve `history` and
`performance_analytics`.

`maybe_record_board_state_to_evaluation_ledger` (intelligence_state.py:2054)
calls the bundle with `query_type="board_state"` for the `persist=True` SIDE
EFFECT, then checks `if not recommendations` and returns. It never reads either
field. On every board cycle that was 830,832,574 bytes / 22,078 records reduced,
normalised and aggregated six ways, producing `sample_size=0` and
`reliability_multiplier=1.0` in 49.7 seconds, and discarded.

The two load-bearing safety properties, both tested here:

1. `persist` does NOT cover the analytics -- it flows only to `record_prediction`
   and the recommendation/portfolio-event writers. Skipping them cannot change
   what reaches the ledger, which is the caller's entire purpose.
2. The default is TRUE, because the two API callers DO read these fields. An
   opt-in would have silently emptied them.
"""

from __future__ import annotations

import io
import contextlib
import inspect

from syndicate.features.shared import intelligence_evaluation as ie


def _bundle(**kw):
    return ie.build_intelligence_evaluation_bundle(
        query={"question": "q", "selected_date": "2026-08-16", "sport": "all", "query_type": "board_state"},
        response={"recommendations": [], "selected_date": "2026-08-16"},
        persist=False,
        **kw,
    )


def test_default_still_builds_the_analytics():
    """The API callers read these. An opt-in default would have emptied them."""
    sig = inspect.signature(ie.build_intelligence_evaluation_bundle)
    assert sig.parameters["include_history_analytics"].default is True


def test_skipping_returns_the_same_SHAPE_not_missing_keys():
    """A consumer that reads without checking must get {} , not a KeyError."""
    with contextlib.redirect_stdout(io.StringIO()):
        bundle = _bundle(include_history_analytics=False)
    assert "history" in bundle and "performance_analytics" in bundle
    assert bundle["history"] == {}
    assert bundle["performance_analytics"] == {}


def test_skipping_does_not_touch_the_ledger():
    """The point of the change: no ledger read at all."""
    calls = []
    real = ie.load_recent_evaluation_records

    def spy(**kw):
        calls.append(kw)
        return real(**kw)

    ie.load_recent_evaluation_records = spy
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _bundle(include_history_analytics=False)
        assert calls == [], f"ledger was read despite the skip: {calls}"
        with contextlib.redirect_stdout(io.StringIO()):
            _bundle(include_history_analytics=True)
        assert calls, "default path should still read the ledger"
    finally:
        ie.load_recent_evaluation_records = real


def test_the_skip_announces_itself():
    """An absent LEDGER_CHUNKS_ACCEPTED is how tonight's readings were nearly
    misread. A skip must be visible, not inferred from silence."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _bundle(include_history_analytics=False)
    out = buf.getvalue()
    assert "BUNDLE_ANALYTICS_SKIPPED" in out
    assert "board_state" in out


def test_persist_still_reaches_the_prediction_record_when_analytics_are_skipped():
    """`persist` must be independent of the analytics.

    If skipping the analytics also skipped persistence, the board_state caller
    would silently stop recording -- the exact opposite of its purpose.
    """
    src = inspect.getsource(ie.build_intelligence_evaluation_bundle)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    persist_at = code.index("record_prediction(")
    guard_at = code.index("if not include_history_analytics:")
    assert persist_at < guard_at, (
        "record_prediction must run BEFORE the analytics guard, so a skip can "
        "never suppress persistence"
    )


# --- the call site -----------------------------------------------------------

def test_board_state_caller_opts_out():
    import pipeline.intelligence_state as st

    src = inspect.getsource(st.maybe_record_board_state_to_evaluation_ledger)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#")).replace(" ", "")
    assert "include_history_analytics=False" in code, (
        "the board-state caller is building analytics it does not read"
    )
    assert "persist=True" in code, "persistence must remain -- it is the caller's purpose"
