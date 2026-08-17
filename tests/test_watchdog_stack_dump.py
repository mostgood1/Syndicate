"""The stack dump must fire inside an excursion, name every thread, and be cheap.

This is the instrument of last resort. Measured across seven excursions on
2026-08-16/17, nothing in the logs distinguishes an excursion from a quiet
window: zero stage markers in a 16s excursion, artifact-pull activity at the
same rate in excursion and control arms, thread-classified activity identical
between excursion 00:31 and control 00:36, and two excursions (23:42, 00:08)
that produced 8 and 6 log rows respectively -- all of them the watchdog's own
samples -- while anon climbed at 25-160 MB/s.

The allocating code emits nothing, so log correlation cannot name it. A stack
dump does not require the code to volunteer anything.

`all_threads=True` is the load-bearing detail, not a flag: `_WATCHDOG_STATE` is
process-global, so `last_stage` names the last thread to SPEAK rather than the
one allocating. That mistake cost an evening and a retraction.
"""

from __future__ import annotations

import io
import contextlib

import pytest

from syndicate.features.shared import memory_observability as mo


@pytest.fixture(autouse=True)
def _reset():
    saved = mo._STACK_DUMP_STATE["count"]
    mo._STACK_DUMP_STATE["count"] = 0
    yield
    mo._STACK_DUMP_STATE["count"] = saved


# --- the gate -----------------------------------------------------------------

@pytest.mark.parametrize("baseline", [1500.0, 1610.0, 1700.0, 2000.0, 2599.9])
def test_does_not_fire_below_the_excursion_threshold(baseline):
    """1610/1700 are the anon levels the OLD censuses fired at -- baseline, not
    excursion. A dump there describes what the process holds at rest."""
    assert not mo.watchdog_should_stack_dump(anon_mb=baseline, fired_count=0)


@pytest.mark.parametrize("excursion", [2600.0, 2894.0, 3401.0, 3998.0])
def test_fires_inside_the_excursion(excursion):
    """2894 / 3401 are real peak-SMAPS readings from 2026-08-17."""
    assert mo.watchdog_should_stack_dump(anon_mb=excursion, fired_count=0)


def test_absent_measurement_does_not_fire():
    """An instrument must not act on a null."""
    assert not mo.watchdog_should_stack_dump(anon_mb=None, fired_count=0)


def test_fires_more_than_once_so_a_stable_stack_is_distinguishable():
    """One sample cannot tell a stable stack from a coincidence.

    A stack shows where threads ARE, not what they ALLOCATED. Repeat samples are
    what separate 'this is the allocator' from 'this is where it happened to be'.
    """
    assert mo._STACK_DUMP_MAX_PER_PROCESS >= 2
    assert mo.watchdog_should_stack_dump(anon_mb=3000.0, fired_count=1)


def test_respects_its_cap():
    cap = mo._STACK_DUMP_MAX_PER_PROCESS
    assert mo.watchdog_should_stack_dump(anon_mb=3000.0, fired_count=cap - 1)
    assert not mo.watchdog_should_stack_dump(anon_mb=3000.0, fired_count=cap)


def test_stack_dump_budget_is_independent_of_the_smaps_budget():
    """The two must not starve each other -- the peak-SMAPS trigger nearly
    shipped silently capped out by a budget it shared with the baseline census."""
    assert mo._STACK_DUMP_STATE is not mo._PEAK_SMAPS_STATE
    assert mo._STACK_DUMP_STATE is not mo._SMAPS_STATE


# --- the emit -----------------------------------------------------------------

def test_emits_a_locatable_header_and_footer():
    """faulthandler writes raw frames with no context; without a header the dump
    is an orphan block of tracebacks in the middle of the log."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        mo._watchdog_maybe_stack_dump(
            {"memory_anon_mb": 3000.0, "last_stage": "board_contract_end", "climb_mb_per_s": 142.0}
        )
    out = buf.getvalue()
    assert "WATCHDOG_STACK_DUMP_BEGIN n=1" in out
    assert "WATCHDOG_STACK_DUMP_END n=1" in out
    assert "anon_mb=3000.0" in out
    assert "last_stage=board_contract_end" in out


def test_the_dump_actually_contains_stack_frames():
    """The point of the instrument. A header with no frames is a no-op."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        mo._watchdog_maybe_stack_dump({"memory_anon_mb": 3000.0})
    out = buf.getvalue()
    assert 'File "' in out and "line " in out, "no traceback frames were written"


def test_does_not_fire_at_baseline_end_to_end():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        mo._watchdog_maybe_stack_dump({"memory_anon_mb": 1700.0})
    assert buf.getvalue() == ""


def test_exhaustion_announces_itself():
    """A silent cap makes 'exhausted' and 'never fired' look identical."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        for _ in range(mo._STACK_DUMP_MAX_PER_PROCESS + 2):
            mo._watchdog_maybe_stack_dump({"memory_anon_mb": 3000.0})
    out = buf.getvalue()
    assert "WATCHDOG_STACK_DUMP_EXHAUSTED" in out
    assert out.count("WATCHDOG_STACK_DUMP_BEGIN") == mo._STACK_DUMP_MAX_PER_PROCESS


def test_never_raises_even_when_faulthandler_is_unusable(monkeypatch):
    """`learnings.md`: an instrument must not be the reason a worker dies."""
    import faulthandler

    monkeypatch.setattr(
        faulthandler, "dump_traceback", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
    )
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        mo._watchdog_maybe_stack_dump({"memory_anon_mb": 3000.0})  # must not raise


# --- wiring -------------------------------------------------------------------

def test_hook_runs_before_the_emit_gate():
    """`_watchdog_should_emit` suppresses samples when the number is not moving;
    a trigger downstream of it inherits that blind spot."""
    import inspect

    src = inspect.getsource(mo)
    body = src[src.index("_watchdog_maybe_dump_allocations(payload, climb)"):]
    assert body.index("_watchdog_maybe_stack_dump(payload)") < body.index("_watchdog_should_emit(")


def test_the_fallback_is_used_and_announced_when_faulthandler_cannot_write():
    """The defect this file caught: a BEGIN header followed by no frames.

    faulthandler needs a real fileno. Against any wrapped stderr it raises, and
    without the fallback the instrument emits a header and nothing else -- which
    reads as 'ran, found nothing' rather than 'could not run'.
    """
    buf = io.StringIO()  # no fileno, exactly like a wrapped stderr
    with contextlib.redirect_stderr(buf):
        mo._watchdog_maybe_stack_dump({"memory_anon_mb": 3000.0})
    out = buf.getvalue()
    assert "WATCHDOG_STACK_DUMP_FAULTHANDLER_UNAVAILABLE" in out, "fallback not announced"
    assert 'File "' in out, "fallback produced no frames"
    assert "wrote=True" in out, "END must report whether anything was written"


def test_end_marker_reports_whether_frames_were_written():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        mo._watchdog_maybe_stack_dump({"memory_anon_mb": 3000.0})
    assert "WATCHDOG_STACK_DUMP_END n=1 wrote=" in buf.getvalue()
