"""`_iter_record_payloads` must report records AND the anon delta, at the choke point.

This trace was first placed on `recommendation_engine._load_records_from_ledger`
and produced, in production 2026-08-17 02:23:49Z:

    LEDGER_LOAD n=1 records=0 anon_delta_mb=0.2 path=evaluation_ledger.jsonl

That wrapper defaults to `DEFAULT_EVALUATION_LEDGER`, a FLAT path which does not
exist, while the 830MB chunked load reaches `_iter_record_payloads` through
`_load_chunk_records_for_window` (:2042) and `load_recent_evaluation_records`
(:2088) -- both of which default to `DEFAULT_LEDGER_PATH` and call it DIRECTLY.
One of three entry points instrumented, and the one wired to a missing file.

Two regressions follow, and both are tested below:

1. The trace belongs at the CHOKE POINT every caller shares, not at one caller.
2. `records` must travel WITH the delta. A small delta on a zero-record load
   proves nothing -- that reading was auto-scored "hypothesis KILLED" when it
   was a null measurement. A small delta on a 22,078-record load is a real
   refutation. Reporting the delta without the count invites the same error.
"""

from __future__ import annotations

import io
import contextlib

import pytest

from syndicate.features.shared import intelligence_evaluation as ie


@pytest.fixture(autouse=True)
def _reset_trace():
    saved = ie._PAYLOAD_TRACE["count"]
    ie._PAYLOAD_TRACE["count"] = 0
    yield
    ie._PAYLOAD_TRACE["count"] = saved


def test_return_value_is_unchanged_by_the_instrument():
    """An instrument that alters what it measures is worse than none."""
    rows = [{"a": 1}, {"b": 2}, {"c": 3}]
    with contextlib.redirect_stdout(io.StringIO()):
        out = ie._iter_record_payloads(rows)
    assert out == rows


def test_reports_records_and_delta_together():
    """Both numbers or neither -- a delta without a count is unreadable."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ie._iter_record_payloads([{"a": 1}] * 5)
    out = buf.getvalue()
    assert "PAYLOAD_LOAD " in out
    assert "records=5" in out, "records is what makes the delta interpretable"
    for field in ("anon_before_mb=", "anon_after_mb=", "anon_delta_mb=", "elapsed_s="):
        assert field in out, f"missing {field}"


def test_names_the_caller():
    """Which of the three entry points reached the choke point."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ie._iter_record_payloads([{"a": 1}])
    assert "callers=" in buf.getvalue()


def test_zero_record_load_is_still_labelled_as_zero():
    """The exact reading that was mis-scored as a refutation.

    A load that returned nothing must SAY records=0, so no reader (or script)
    can mistake its small delta for evidence about a large load.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ie._iter_record_payloads([])
    assert out == []
    assert "records=0" in buf.getvalue()


def test_survives_a_broken_memory_probe(monkeypatch):
    """`learnings.md`: an instrument must not be the reason a worker dies."""
    import syndicate.features.shared.memory_observability as mo

    monkeypatch.setattr(
        mo, "container_memory_payload", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no cgroups"))
    )
    rows = [{"a": 1}, {"b": 2}]
    with contextlib.redirect_stdout(io.StringIO()):
        out = ie._iter_record_payloads(rows)
    assert out == rows


def test_cap_announces_itself_rather_than_going_silent():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for _ in range(ie._PAYLOAD_TRACE_MAX + 2):
            ie._iter_record_payloads([{"a": 1}])
    out = buf.getvalue()
    assert "PAYLOAD_LOAD_TRACE_CAPPED" in out
    assert out.count("PAYLOAD_LOAD n=") == ie._PAYLOAD_TRACE_MAX


def test_loading_continues_unchanged_past_the_cap():
    rows = [{"a": 1}, {"b": 2}]
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(ie._PAYLOAD_TRACE_MAX + 4):
            out = ie._iter_record_payloads(rows)
    assert out == rows
