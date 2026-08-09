"""#285 -- the worker must hand freed heap back to the KERNEL, not just to Python.

`gc.collect()` returns memory to Python's allocator. The cgroup guards that
decide whether the board builds read the kernel's number, and those are not the
same number. Measured on refresh-worker 2026-08-09 under `#290`'s control
condition (hydrated overview blocked on every cycle, so it is excluded by
construction):

    01:03:43   container 2564.9 MB   gc_objects 381,063
    01:05:22   container 2654.2 MB   gc_objects 308,068
               container  +89.3 MB   gc_objects  -72,995

A collection ran, 73,000 objects went away, and the resident set went UP.

The consequence, measured 19:55-21:12Z across 25 pool builds with no exceptions
in either direction: `pool = 0` on 24 of 25, and on 24 of 24 of those a memory
guard had fired 3-43s earlier (23x `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb
sports_done=0`, 1x `MEMORY_GUARD_ABORT stage=build_candidate_pool_start`). The
one cycle with `pool = 590` had no guard fire at all.

What these tests pin is ORDERING and ATTRIBUTION, not the release itself -- the
release is the kernel's business and cannot be asserted from a test process.
Ordering, because a trim that runs after the guard has already read cannot
change that guard's verdict, and that is the entire mechanism. Attribution,
because the gc and the trim must stay separable in the emitted line: a drop
caused by the collection reported as a trim release would be evidence for the
wrong one of `#285`'s two open hypotheses.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from syndicate.features.shared import memory_observability


@pytest.fixture(autouse=True)
def _reset_trim_resolution():
    # The resolver caches, deliberately (one dlopen per process). Every test
    # here rebinds it, so the cache has to be cleared both ways or the second
    # test in a run inherits the first one's fake.
    original = dict(memory_observability._MALLOC_TRIM_STATE)
    yield
    memory_observability._MALLOC_TRIM_STATE.clear()
    memory_observability._MALLOC_TRIM_STATE.update(original)


def test_resolution_announces_which_branch_it_took(capsys):
    # This binding cannot be executed anywhere in this repo's dev environment
    # (Windows, no WSL, no Docker), so the first proof it works is a production
    # log line. A failed dlopen and a trim that released nothing are both
    # silence otherwise. What is asserted here is that the line exists and
    # names the branch -- NOT that it says available, which is false on the
    # machine running this test and true on Render.
    memory_observability._MALLOC_TRIM_STATE.clear()
    memory_observability._MALLOC_TRIM_STATE.update(
        {"resolved": False, "fn": None, "libc": None, "unavailable_reason": ""}
    )
    capsys.readouterr()

    memory_observability._resolve_malloc_trim()

    line = next(
        chunk for chunk in capsys.readouterr().out.splitlines() if chunk.startswith("MALLOC_TRIM_INIT ")
    )
    payload = json.loads(line[len("MALLOC_TRIM_INIT ") :])
    assert set(payload) == {"available", "library", "platform", "pid", "unavailable_reason"}
    # Whichever branch this machine took, it has to be self-describing: either
    # it bound and names the library, or it did not and names the reason.
    assert bool(payload["available"]) is (payload["unavailable_reason"] is None)

    # Resolution is cached, so the line is emitted once per process and does
    # not become per-cycle noise in the worker's log.
    capsys.readouterr()
    memory_observability._resolve_malloc_trim()
    assert "MALLOC_TRIM_INIT" not in capsys.readouterr().out


def test_returns_none_when_libc_has_no_malloc_trim(monkeypatch):
    # Windows and musl take this branch on every call, as does every developer
    # machine in this repo. None means "no trim was attempted" and must stay
    # distinguishable from "trimmed and released nothing" -- collapsing those
    # is how a null result gets read as evidence about the allocator.
    monkeypatch.setattr(memory_observability, "_resolve_malloc_trim", lambda: None)
    assert memory_observability.release_freed_memory_to_os("unit-test") is None


def test_a_raising_trim_never_propagates(monkeypatch):
    # This runs inside the board-build loop. An optimisation that can kill the
    # cycle it is optimising is worse than no optimisation.
    def _boom(_size):
        raise OSError("libc said no")

    monkeypatch.setattr(memory_observability, "_resolve_malloc_trim", lambda: _boom)
    assert memory_observability.release_freed_memory_to_os("unit-test") is None


def test_gc_and_trim_are_attributed_separately(capsys, monkeypatch):
    # The load-bearing assertion of the whole change. anon moves 1500 -> 1490
    # across the collection and 1490 -> 900 across the trim; the line must
    # credit 590MB to the trim and not 600MB, because only the trim half
    # discriminates hypothesis (1) allocator retention from (2) live
    # str/bytes/ndarray the heap census cannot enumerate.
    readings = iter([1500, 1490, 900])
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {"anon": next(readings) * 1024 * 1024},
    )
    monkeypatch.setattr(memory_observability, "_current_process_rss_bytes", lambda: 1400 * 1024 * 1024)
    monkeypatch.setattr(memory_observability, "_resolve_malloc_trim", lambda: (lambda _size: 1))

    payload = memory_observability.release_freed_memory_to_os("unit-test")

    assert payload is not None
    assert payload["anon_before_mb"] == pytest.approx(1500.0)
    assert payload["anon_after_gc_mb"] == pytest.approx(1490.0)
    assert payload["anon_after_mb"] == pytest.approx(900.0)
    assert payload["anon_released_by_trim_mb"] == pytest.approx(590.0)
    assert payload["anon_released_mb"] == pytest.approx(600.0)

    # #37: emitted with print(..., flush=True), not logger.info, or Render's
    # collector never sees it and this experiment reports nothing at all.
    emitted = capsys.readouterr().out
    assert "MALLOC_TRIM " in emitted
    line = next(chunk for chunk in emitted.splitlines() if chunk.startswith("MALLOC_TRIM "))
    assert json.loads(line[len("MALLOC_TRIM ") :])["reason"] == "unit-test"


def test_collect_first_can_be_disabled(monkeypatch):
    # Kept honest: with the collection off there is no post-gc reading to
    # attribute from, so the trim's share must equal the whole delta rather
    # than silently reporting None.
    readings = iter([1200, 800])
    monkeypatch.setattr(
        memory_observability,
        "_read_container_memory_stat",
        lambda: {"anon": next(readings) * 1024 * 1024},
    )
    monkeypatch.setattr(memory_observability, "_current_process_rss_bytes", lambda: None)
    monkeypatch.setattr(memory_observability, "_resolve_malloc_trim", lambda: (lambda _size: 1))

    payload = memory_observability.release_freed_memory_to_os("unit-test", collect_first=False)

    assert payload["gc_collected"] is None
    assert payload["anon_released_by_trim_mb"] == pytest.approx(400.0)
    assert payload["anon_released_mb"] == pytest.approx(400.0)


def test_trim_runs_before_the_guard_that_starves_the_board(monkeypatch):
    """The ordering, asserted on the real `_build_candidate_pool` call path.

    A trim placed after `_abort_build_candidate_pool_if_memory_critical` would
    deploy, run, log a healthy release every cycle, and change nothing -- the
    guard has already read the number by then. That failure mode is invisible
    in production because the trim line looks exactly the same either way, so
    it is pinned here instead.
    """
    from pipeline import intelligence_state

    calls: list[str] = []

    def _fake_trim(reason: str) -> dict[str, Any] | None:
        calls.append(f"trim:{reason}")
        return None

    def _fake_guard(stage: str) -> bool:
        calls.append(f"guard:{stage}")
        # Abort at the first guard: that is the short path through this
        # function, and it is enough to prove which of the two ran first.
        return True

    monkeypatch.setattr(intelligence_state, "_release_freed_memory_to_os", _fake_trim)
    monkeypatch.setattr(intelligence_state, "_abort_build_candidate_pool_if_memory_critical", _fake_guard)
    monkeypatch.setattr(intelligence_state, "_diag_log_all_process_memory", lambda stage: None)

    manager = intelligence_state.IntelligenceStateService()
    pool = manager._build_candidate_pool("2026-08-09", "fingerprint-under-test")

    assert calls == [
        "trim:pre_build_candidate_pool_start_guard",
        "guard:build_candidate_pool_start",
    ]
    assert pool["candidate_count"] == 0


def test_the_overview_guard_is_also_preceded_by_a_trim(monkeypatch):
    # 23 of the 24 guarded cycles measured 19:55-21:12Z stopped inside
    # build_intelligence_overview on `next_sport=mlb sports_done=0`, not at the
    # caller's own guard. The trim in front of the FIRST guard therefore does
    # not cover the case that has actually been starving the board; the second
    # one, immediately before the overview call, is the one that does.
    from pipeline import intelligence_state

    calls: list[str] = []
    monkeypatch.setattr(intelligence_state, "_release_freed_memory_to_os", lambda reason: calls.append(f"trim:{reason}"))
    monkeypatch.setattr(
        intelligence_state,
        "_abort_build_candidate_pool_if_memory_critical",
        lambda stage: calls.append(f"guard:{stage}") or (stage == "post_pull_hot_artifacts"),
    )
    monkeypatch.setattr(intelligence_state, "_diag_log_all_process_memory", lambda stage: None)

    from syndicate.features.shared import artifact_publisher

    monkeypatch.setattr(artifact_publisher, "pull_hot_artifacts", lambda **_kwargs: None)
    monkeypatch.setattr(artifact_publisher, "pull_odds_history_artifacts", lambda **_kwargs: 0)

    manager = intelligence_state.IntelligenceStateService()
    manager._build_candidate_pool("2026-08-09", "fingerprint-under-test")

    assert calls == [
        "trim:pre_build_candidate_pool_start_guard",
        "guard:build_candidate_pool_start",
        "trim:pre_overview_headroom_guard",
        "guard:post_pull_hot_artifacts",
    ]
