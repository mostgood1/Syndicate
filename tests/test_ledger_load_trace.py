"""`_load_records_from_ledger` must report the anon delta across the load.

Why: production reports `LEDGER_CHUNKS_ACCEPTED count=8 bytes=830,832,574
records=22,078 streamed=1` -- the file is streamed, the RESULT is materialised.
That is the standing candidate for the +2.1..2.9GB excursions that OOM-kill
refresh-worker, and the peak-SMAPS instrument (2026-08-17 01:46:04-09Z) located
the growth to a single anonymous VMA without being able to name its allocator.

The delta is the falsifiable part. If this load runs and anon barely moves, the
hypothesis is dead regardless of how well the arithmetic fits -- which is the
point, because three prior attributions on this bug were coherent and wrong.

The FIRST test is the one that matters: an instrument must not change the thing
it measures.
"""

from __future__ import annotations

import io
import contextlib

import pytest

from syndicate.features.shared import recommendation_engine as re_mod


@pytest.fixture(autouse=True)
def _reset_trace():
    saved = re_mod._LEDGER_LOAD_TRACE["count"]
    re_mod._LEDGER_LOAD_TRACE["count"] = 0
    yield
    re_mod._LEDGER_LOAD_TRACE["count"] = saved


def _fake_payloads(monkeypatch, rows):
    monkeypatch.setattr(re_mod, "_iter_record_payloads", lambda **kw: list(rows))


def test_return_value_is_unchanged_by_the_instrument(monkeypatch, tmp_path):
    """An instrument that alters the load is worse than no instrument."""
    rows = [{"a": 1}, {"b": 2}, {"c": 3}]
    _fake_payloads(monkeypatch, rows)
    with contextlib.redirect_stdout(io.StringIO()):
        out = re_mod._load_records_from_ledger(tmp_path / "ledger.jsonl")
    assert out == rows


def test_emits_a_line_carrying_records_elapsed_and_delta(monkeypatch, tmp_path):
    _fake_payloads(monkeypatch, [{"a": 1}] * 7)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        re_mod._load_records_from_ledger(tmp_path / "ledger.jsonl")
    out = buf.getvalue()
    assert "LEDGER_LOAD " in out
    assert "records=7" in out
    for field in ("elapsed_s=", "anon_before_mb=", "anon_after_mb=", "anon_delta_mb="):
        assert field in out, f"missing {field} -- the delta is the whole point"


def test_survives_a_broken_memory_probe(monkeypatch, tmp_path):
    """If the cgroup read fails, the LOAD must still succeed.

    `learnings.md`: an instrument must not be the reason a worker dies.
    """
    import syndicate.features.shared.memory_observability as mo

    def _boom(*a, **k):
        raise RuntimeError("no cgroups here")

    monkeypatch.setattr(mo, "container_memory_payload", _boom)
    rows = [{"a": 1}, {"b": 2}]
    _fake_payloads(monkeypatch, rows)
    with contextlib.redirect_stdout(io.StringIO()):
        out = re_mod._load_records_from_ledger(tmp_path / "ledger.jsonl")
    assert out == rows


def test_cap_announces_itself_rather_than_going_silent(monkeypatch, tmp_path):
    """A silent cap makes 'capped' and 'never ran' look identical.

    This is the defect that nearly shipped in log_smaps_anon_breakdown, where a
    capped-out call returned None with no line at all.
    """
    _fake_payloads(monkeypatch, [{"a": 1}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for _ in range(re_mod._LEDGER_LOAD_TRACE_MAX + 2):
            re_mod._load_records_from_ledger(tmp_path / "ledger.jsonl")
    out = buf.getvalue()
    assert "LEDGER_LOAD_TRACE_CAPPED" in out
    assert out.count("LEDGER_LOAD n=") == re_mod._LEDGER_LOAD_TRACE_MAX


def test_cap_stops_tracing_but_never_stops_loading(monkeypatch, tmp_path):
    rows = [{"a": 1}, {"b": 2}]
    _fake_payloads(monkeypatch, rows)
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(re_mod._LEDGER_LOAD_TRACE_MAX + 5):
            out = re_mod._load_records_from_ledger(tmp_path / "ledger.jsonl")
    assert out == rows, "loading must continue unchanged after the trace cap"
