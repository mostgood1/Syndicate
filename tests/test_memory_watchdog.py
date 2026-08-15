"""`#435` -- the memory watchdog, and the two failure shapes it exists for.

Six OOM kills were sampled on 2026-08-14/15 for the last instrumented line
before death. Four sat at 99-100%; TWO sat at **71.9%** and **22.7%** seconds
before the process was killed. Every existing sample is taken at a stage
BOUNDARY, so those two are multi-GB allocations INSIDE one stage -- invisible,
and precisely the ones that would name the allocator.

So the tests below are not "does it log". They pin that the FLOOR trigger catches
the slow ratchet, the DELTA trigger catches the fast excursion BEFORE it reaches
the floor, and that an unreadable split emits rather than going quiet -- because
the reading taken while things are worst is the one that must not be dropped.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from syndicate.features.shared import memory_observability as mo


def _payload(*, pct: float, unreclaimable_mb: float | None) -> dict:
    return {
        "stage": "watchdog",
        "memory_pct_of_max": pct,
        "memory_unreclaimable_mb": unreclaimable_mb,
        "memory_anon_mb": unreclaimable_mb,
    }


def test_floor_trigger_fires_at_or_above_the_floor():
    # The slow-ratchet shape: 99-100% at the last sample, four of six kills.
    assert mo._watchdog_should_emit(_payload(pct=60.0, unreclaimable_mb=100.0), 100.0) is True
    assert mo._watchdog_should_emit(_payload(pct=99.1, unreclaimable_mb=3443.5), 3443.5) is True


def test_below_the_floor_and_not_moving_stays_silent():
    # `learnings.md`: worker periodic work is never free (`#241` restart loop).
    # At rest this must produce nothing at all.
    assert mo._watchdog_should_emit(_payload(pct=21.8, unreclaimable_mb=502.4), 502.4) is False


def test_delta_trigger_catches_the_fast_excursion_below_the_floor():
    # THE 00:04:47 KILL. Last boundary sample was 537.5MB at 22.7%, then dead
    # 2.6 seconds later. The floor alone would never have fired; the delta must.
    assert mo._watchdog_should_emit(_payload(pct=22.7, unreclaimable_mb=537.5), 300.0) is True
    # ...and the 22:48:35 kill, 1389.7MB at 71.9% nineteen seconds before death.
    assert mo._watchdog_should_emit(_payload(pct=71.9, unreclaimable_mb=1389.7), 1300.0) is True


def test_first_sample_below_the_floor_does_not_emit():
    # No baseline yet means no delta to compute. Emitting here would make every
    # boot log a sample that says nothing.
    assert mo._watchdog_should_emit(_payload(pct=10.0, unreclaimable_mb=200.0), None) is False


def test_an_unreadable_split_on_a_real_cgroup_emits_rather_than_going_quiet():
    # Unknown must not be silent. A cgroup this cannot parse is exactly when the
    # sample matters most, and `log_container_memory`'s own comment records that
    # absent keys must never read as a false all-clear. `memory.current` IS
    # readable here, so this is a real anomaly on a real cgroup.
    assert mo._watchdog_should_emit(_payload(pct=5.0, unreclaimable_mb=None), 100.0) is True


def test_a_machine_with_no_cgroup_at_all_says_so_once_then_goes_quiet():
    # The other unknown, and conflating the two floods the log: on any dev
    # machine NOTHING is readable, and emitting every tick forever would bury
    # the signal this instrument exists to surface.
    mo._WATCHDOG_STATE.pop("unmeasurable_reported", None)
    blind = {"stage": "watchdog", "memory_pct_of_max": None, "memory_unreclaimable_mb": None,
             "memory_anon_mb": None}
    try:
        assert mo._watchdog_should_emit(blind, None) is True     # says so once
        assert mo._watchdog_should_emit(blind, None) is False    # then quiet
        assert mo._watchdog_should_emit(blind, 100.0) is False
    finally:
        mo._WATCHDOG_STATE.pop("unmeasurable_reported", None)


def test_thresholds_are_env_overridable_without_a_code_change():
    with patch.dict("os.environ", {"SYNDICATE_MEMORY_WATCHDOG_FLOOR_PCT": "35"}):
        assert mo._watchdog_should_emit(_payload(pct=40.0, unreclaimable_mb=1.0), 1.0) is True
    with patch.dict("os.environ", {"SYNDICATE_MEMORY_WATCHDOG_DELTA_MB": "50"}):
        assert mo._watchdog_should_emit(_payload(pct=1.0, unreclaimable_mb=160.0), 100.0) is True


def test_enabled_by_default_and_killable_by_env():
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("SYNDICATE_MEMORY_WATCHDOG", None)
        assert mo.memory_watchdog_enabled() is True
    for off in ("0", "false", "no", "off", "OFF"):
        with patch.dict("os.environ", {"SYNDICATE_MEMORY_WATCHDOG": off}):
            assert mo.memory_watchdog_enabled() is False, off


def test_payload_builder_is_the_same_one_the_logger_uses(capfd):
    # The reclaimable expression was ONCE computed twice independently, and a fix
    # to the guard left the logged line contradicting the decision it explained
    # (see `log_container_memory`'s docstring). The watchdog must not become the
    # second copy -- so pin that both go through `container_memory_payload`.
    built = mo.container_memory_payload("unit-test", extra_key=7)
    assert built["stage"] == "unit-test" and built["extra_key"] == 7
    assert capfd.readouterr().err == ""  # builds WITHOUT printing

    logged = mo.log_container_memory("unit-test", extra_key=7)
    err = capfd.readouterr().err
    assert "CONTAINER_MEMORY" in err
    assert set(logged) == set(built)
    emitted = json.loads(err.split("CONTAINER_MEMORY ", 1)[1].splitlines()[0])
    assert emitted["stage"] == "unit-test"


def test_logging_a_stage_records_it_for_attribution():
    # This is what turns "4GB at 00:40:59" into "the excursion began N seconds
    # into stage X" -- the sentence nobody has been able to write about this bug.
    mo.log_container_memory("cards_context_page_cache_hit")
    assert mo._WATCHDOG_STATE["last_stage"] == "cards_context_page_cache_hit"
    assert isinstance(mo._WATCHDOG_STATE["last_stage_at"], float)


def test_start_is_idempotent_and_never_raises():
    saved = mo._WATCHDOG_STATE.get("thread")
    try:
        mo._WATCHDOG_STATE["thread"] = object()  # pretend one is already running
        assert mo.start_memory_watchdog() is False
        with patch.dict("os.environ", {"SYNDICATE_MEMORY_WATCHDOG": "0"}):
            mo._WATCHDOG_STATE["thread"] = None
            assert mo.start_memory_watchdog() is False
    finally:
        mo._WATCHDOG_STATE["thread"] = saved


# --- #435 step three: the dump trigger ---------------------------------------
#
# The numbers below are the REAL excursion measured 2026-08-15 01:38, so these
# tests fail if the trigger would have missed the event it was built for.


def test_climb_rate_matches_the_measured_excursion():
    # 01:38:23 -> 01:38:25, 2184.2 -> 2500.3MB across 2.37s
    rate = mo.watchdog_excursion_climb_mb_per_s(2184.219, 2500.27, 2.373)
    assert rate is not None and 130 < rate < 137
    # and it must not invent a rate from missing data
    assert mo.watchdog_excursion_climb_mb_per_s(None, 100.0, 2.0) is None
    assert mo.watchdog_excursion_climb_mb_per_s(100.0, 200.0, 0) is None


def test_the_trigger_fires_on_the_measured_excursion():
    assert mo.watchdog_should_dump_allocations(
        climb_mb_per_s=133.2, anon_mb=2500.27, already_dumped=False
    ) is True


def test_the_trigger_ignores_a_high_but_STABLE_process():
    # This worker sits high for most of its life. A traceback dump there costs
    # memory on a process at its ceiling and tells us nothing.
    assert mo.watchdog_should_dump_allocations(
        climb_mb_per_s=0.4, anon_mb=3400.0, already_dumped=False
    ) is False


def test_the_trigger_ignores_ordinary_warm_up_below_the_floor():
    # Boot climbs fast too -- 361 -> 1486MB in the first pass. Rate alone would
    # fire there and waste the one dump we allow ourselves.
    assert mo.watchdog_should_dump_allocations(
        climb_mb_per_s=90.0, anon_mb=800.0, already_dumped=False
    ) is False


def test_the_dump_is_once_per_boot():
    assert mo.watchdog_should_dump_allocations(
        climb_mb_per_s=133.2, anon_mb=2500.27, already_dumped=True
    ) is False


def test_tracing_off_announces_itself_at_the_moment_it_would_have_fired(capfd):
    # An instrument that is OFF must say so WHEN it would have fired. Silence
    # from a disabled instrument is indistinguishable from "nothing happened",
    # which is the exact mistake that made a log grep read as "no OOM" tonight.
    mo._WATCHDOG_STATE.pop("allocations_dumped", None)
    try:
        with patch.object(mo, "allocation_tracing_enabled", return_value=False):
            mo._watchdog_dump_allocations_now(
                {"memory_anon_mb": 2500.27, "last_stage": "board_contract_games_normalized"},
                133.2,
            )
        out = capfd.readouterr().out
        assert "WATCHDOG_EXCURSION_NO_TRACING" in out
        assert "SYNDICATE_TRACEMALLOC_DIAG=1" in out
    finally:
        mo._WATCHDOG_STATE.pop("allocations_dumped", None)


def test_tracing_on_emits_the_allocation_census(capfd):
    mo._WATCHDOG_STATE.pop("allocations_dumped", None)
    try:
        with patch.object(mo, "allocation_tracing_enabled", return_value=True), patch.object(
            mo, "allocation_snapshot", return_value={"traced_mb": 1234.5, "top": ["site-a"]}
        ):
            mo._watchdog_dump_allocations_now(
                {"memory_anon_mb": 2500.27, "last_stage": "cards_context_sim_games_loaded"},
                133.2,
            )
        err = capfd.readouterr().err
        assert "WATCHDOG_EXCURSION_ALLOCATIONS" in err
        assert "site-a" in err and "cards_context_sim_games_loaded" in err
    finally:
        mo._WATCHDOG_STATE.pop("allocations_dumped", None)


def test_a_failing_snapshot_never_escapes(capfd):
    mo._WATCHDOG_STATE.pop("allocations_dumped", None)
    try:
        with patch.object(mo, "allocation_tracing_enabled", return_value=True), patch.object(
            mo, "allocation_snapshot", side_effect=RuntimeError("boom")
        ):
            mo._watchdog_dump_allocations_now({"memory_anon_mb": 2500.27}, 133.2)
        assert "WATCHDOG_ALLOCATION_DUMP_FAILED" in capfd.readouterr().out
    finally:
        mo._WATCHDOG_STATE.pop("allocations_dumped", None)


def test_the_dump_never_runs_on_the_sampler_thread():
    """MEASURED 2026-08-15 02:11-02:16: with tracing at nframe=3 the worker
    emitted its START line and then ZERO samples before dying 5.5 minutes later,
    where the previous build emitted 567. `take_snapshot()` walks every live
    traced allocation in C holding the GIL, so the one call the trigger makes
    starved the sampler -- and since the print happens after the snapshot
    returns, it looked like the trigger had never fired.

    So: the scheduler must hand off and return, never call the dump inline.
    """
    mo._WATCHDOG_STATE.pop("allocations_dumped", None)
    started = {}

    class _FakeThread:
        def __init__(self, target=None, args=(), name=None, daemon=None):
            started["target"] = target
            started["daemon"] = daemon
            started["name"] = name

        def start(self):
            started["started"] = True

    try:
        with patch.object(mo, "allocation_tracing_enabled", return_value=True), patch.object(
            mo, "allocation_snapshot", side_effect=AssertionError("must not run inline")
        ), patch("threading.Thread", _FakeThread):
            mo._watchdog_maybe_dump_allocations({"memory_anon_mb": 2500.27}, 133.2)
        assert started.get("started") is True
        assert started.get("daemon") is True
        assert started.get("target") is mo._watchdog_dump_allocations_now
    finally:
        mo._WATCHDOG_STATE.pop("allocations_dumped", None)
