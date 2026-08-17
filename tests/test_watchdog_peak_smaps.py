"""The peak SMAPS trigger must fire INSIDE an excursion and not at baseline.

Why this file exists: every census this process had was firing at
`SYNDICATE_MEMORY_WATCHDOG_CENSUS_MB` (1500MB anon), which is the ELEVATED
BASELINE. Measured 2026-08-17, they fired at anon 1610MB and 1700MB while the
excursions that actually OOM-kill the worker peak at 3700-4000MB. So every
census on record describes what the process HOLDS, not what the excursion
ALLOCATES -- and the two had been read as if they were the same thing.

The regression that matters is therefore not "does it fire" but "does it
DECLINE to fire at the levels that were already covered". A trigger that fires
at 1700MB would silently reproduce the original defect while looking installed,
which is the failure mode this whole module's history is made of.
"""

from __future__ import annotations

import io
import contextlib

import pytest

from syndicate.features.shared import memory_observability as mo


# --- the discriminating case: baseline must NOT fire -------------------------

@pytest.mark.parametrize("baseline_anon", [1500.0, 1610.0, 1700.0, 2000.0])
def test_does_not_fire_at_the_baseline_levels_already_censused(baseline_anon):
    """1610 and 1700 are the anon levels the OLD censuses actually fired at."""
    assert not mo.watchdog_should_peak_smaps(anon_mb=baseline_anon, fired_count=0), (
        f"anon={baseline_anon}MB is baseline; firing here reproduces the defect "
        "of characterising what the process holds instead of the excursion"
    )


@pytest.mark.parametrize("excursion_anon", [2600.0, 2900.0, 3500.0, 3998.0])
def test_fires_inside_the_excursion(excursion_anon):
    """3998MB is the measured peak of the 00:19:48Z kill."""
    assert mo.watchdog_should_peak_smaps(anon_mb=excursion_anon, fired_count=0)


def test_threshold_boundary_is_inclusive_and_just_below_is_not():
    assert mo.watchdog_should_peak_smaps(anon_mb=2600.0, fired_count=0)
    assert not mo.watchdog_should_peak_smaps(anon_mb=2599.9, fired_count=0)


# --- budget ------------------------------------------------------------------

def test_respects_its_own_per_process_cap():
    cap = mo._PEAK_SMAPS_MAX_PER_PROCESS
    assert mo.watchdog_should_peak_smaps(anon_mb=3500.0, fired_count=cap - 1)
    assert not mo.watchdog_should_peak_smaps(anon_mb=3500.0, fired_count=cap)


def test_fires_more_than_once_because_growth_needs_two_points():
    """A single peak sample cannot show which regions GREW."""
    assert mo._PEAK_SMAPS_MAX_PER_PROCESS >= 2
    assert mo.watchdog_should_peak_smaps(anon_mb=3500.0, fired_count=1)


def test_peak_budget_is_separate_from_the_baseline_census_budget():
    """The two must not starve each other.

    The baseline censuses call `log_smaps_anon_breakdown` through
    `_run_censuses`, and that function is capped by `_SMAPS_MAX_PER_PROCESS`.
    If the shared cap cannot absorb baseline + peak, the peak reads are dropped
    SILENTLY by the cap check and the instrument looks installed while emitting
    nothing.
    """
    assert mo._PEAK_SMAPS_STATE is not mo._SMAPS_STATE
    assert mo._SMAPS_MAX_PER_PROCESS >= mo._PEAK_SMAPS_MAX_PER_PROCESS + 1


# --- unmeasurable input ------------------------------------------------------

def test_absent_anon_does_not_fire():
    """No measurement -> no census. An instrument must not act on a null."""
    assert not mo.watchdog_should_peak_smaps(anon_mb=None, fired_count=0)


# --- the silent-cap defect this change also fixes ----------------------------

def test_capped_out_smaps_announces_itself_instead_of_returning_silently():
    """A capped-out instrument must be distinguishable from one that found nothing."""
    saved = mo._SMAPS_STATE["count"]
    try:
        mo._SMAPS_STATE["count"] = mo._SMAPS_MAX_PER_PROCESS
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = mo.log_smaps_anon_breakdown("test_reason")
        out = buf.getvalue()
        assert result is None
        assert "SMAPS_SKIPPED_CAPPED" in out, (
            "a capped-out SMAPS returned None in silence; a missing SMAPS_ANON "
            "must be attributable to the cap rather than inferred"
        )
        assert "test_reason" in out
    finally:
        mo._SMAPS_STATE["count"] = saved


# --- wiring ------------------------------------------------------------------

def test_hook_is_wired_into_the_sampler_before_the_emit_gate():
    """`_watchdog_should_emit` suppresses samples when the number is not moving.

    A trigger placed after it would inherit that blind spot -- the same reason
    the climb rate is computed on every sample rather than every emitted one.
    """
    import inspect

    src = inspect.getsource(mo)
    assert "_watchdog_maybe_peak_smaps(payload)" in src, "hook is not called"
    body = src[src.index("_watchdog_maybe_dump_allocations(payload, climb)"):]
    hook = body.index("_watchdog_maybe_peak_smaps(payload)")
    gate = body.index("_watchdog_should_emit(")
    assert hook < gate, "peak SMAPS hook must run BEFORE the emit gate"
