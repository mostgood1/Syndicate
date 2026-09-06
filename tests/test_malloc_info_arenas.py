"""Tests for the PER-ARENA `malloc_info` split. `#632`.

The libc call cannot run on any dev machine in this repo, so the parser is the
only half that can be tested and it carries every derived claim. These tests are
therefore about the ARITHMETIC and the REFUSALS -- particularly the cases where
the instrument must decline to answer rather than produce a plausible number.

Fixtures are built at PRODUCTION SCALE on purpose. The agreement tolerance has a
2 MB absolute floor, so on a toy 6 MB fixture the main arena and the all-arena
total are within tolerance of each other and nothing can be discriminated. That
is correct behaviour, it is pinned below by name, and it is also why every other
fixture here uses hundreds of megabytes.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import memory_observability


def _mb(value: float) -> int:
    return int(round(value * 1024 * 1024))


def _heap(nr: int, system_mb: float, fast_mb: float = 0.0, rest_mb: float = 0.0,
          aspace_mb: float | None = None, omit_nr: bool = False,
          omit_system: bool = False) -> str:
    attr = "" if omit_nr else f' nr="{nr}"'
    parts = [f"<heap{attr}>", "<sizes/>",
             f'<total type="fast" count="1" size="{_mb(fast_mb)}"/>',
             f'<total type="rest" count="1" size="{_mb(rest_mb)}"/>']
    if not omit_system:
        parts.append(f'<system type="current" size="{_mb(system_mb)}"/>')
    parts.append(f'<system type="max" size="{_mb(system_mb)}"/>')
    if aspace_mb is not None:
        parts.append(f'<aspace type="total" size="{_mb(aspace_mb)}"/>')
    parts.append("</heap>")
    return "\n".join(parts)


def _xml(heaps: list[str], top_system_mb: float, top_fast_mb: float = 0.0,
         top_rest_mb: float = 0.0, mmap_mb: float = 0.0,
         omit_top_system: bool = False) -> str:
    body = "\n".join(heaps)
    tail = [f'<total type="fast" count="1" size="{_mb(top_fast_mb)}"/>',
            f'<total type="rest" count="1" size="{_mb(top_rest_mb)}"/>',
            f'<total type="mmap" count="1" size="{_mb(mmap_mb)}"/>']
    if not omit_top_system:
        tail.append(f'<system type="current" size="{_mb(top_system_mb)}"/>')
    tail.append(f'<system type="max" size="{_mb(top_system_mb)}"/>')
    return ('<malloc version="1">\n' + body + "\n" + "\n".join(tail) + "\n</malloc>\n")


# A plausible web worker: main arena at 390 MB plus four 64 MB per-thread
# arenas (`GUNICORN_THREADS=4`), against 675 MB of process anon.
WEB = _xml([_heap(0, 390.0, rest_mb=320.0, aspace_mb=390.0),
            _heap(1, 64.0, rest_mb=50.0, aspace_mb=64.0),
            _heap(2, 64.0, rest_mb=50.0, aspace_mb=64.0),
            _heap(3, 64.0, rest_mb=48.0, aspace_mb=64.0),
            _heap(4, 64.0, rest_mb=47.0, aspace_mb=64.0)],
           top_system_mb=646.0, top_rest_mb=515.0)


def test_per_heap_figures_are_parsed_individually():
    parsed = memory_observability.parse_malloc_info_arenas(WEB)
    assert parsed["arena_count"] == 5
    main = parsed["arenas"][0]
    assert main["nr"] == 0
    assert main["system_current_mb"] == 390.0
    assert main["free_held_mb"] == 320.0
    assert main["in_use_mb"] == 70.0
    assert main["aspace_total_mb"] == 390.0
    assert parsed["arenas"][1]["nr"] == 1
    assert parsed["arenas"][1]["system_current_mb"] == 64.0


def test_reconciliation_is_reported_not_assumed():
    parsed = memory_observability.parse_malloc_info_arenas(WEB)
    assert parsed["per_heap_sum_mb"] == 646.0
    assert parsed["reconcile_residual_mb"] == 0.0
    assert parsed["reconciles"] is True


def test_a_sum_that_does_not_reproduce_the_total_blocks_every_verdict():
    # The whole point of the reconciliation: if the tree was read wrong, the
    # split computed from it must not be presented as a finding.
    broken = _xml([_heap(0, 390.0), _heap(1, 64.0)], top_system_mb=900.0)
    parsed = memory_observability.parse_malloc_info_arenas(broken, anon_mb=950.0)
    assert parsed["reconciles"] is False
    assert parsed["reads_as"] == "reconciliation_failed"
    assert parsed["reconcile_residual_mb"] == pytest.approx(446.0, abs=0.2)


def test_main_and_secondary_split():
    parsed = memory_observability.parse_malloc_info_arenas(WEB)
    assert parsed["split_available"] is True
    assert parsed["main_arena_mb"] == 390.0
    assert parsed["secondary_arena_mb"] == 256.0
    assert parsed["secondary_pct_of_arenas"] == pytest.approx(39.6, abs=0.2)


def test_secondary_dominant_is_recognised():
    heavy = _xml([_heap(0, 100.0), _heap(1, 200.0), _heap(2, 200.0)],
                 top_system_mb=500.0)
    parsed = memory_observability.parse_malloc_info_arenas(heavy, anon_mb=520.0)
    assert parsed["secondary_pct_of_arenas"] == 80.0
    assert parsed["reads_as"] == "secondary_arenas_dominant"


def test_main_dominant_is_recognised():
    parsed = memory_observability.parse_malloc_info_arenas(WEB, anon_mb=675.0)
    assert parsed["reads_as"] == "main_arena_dominant"


# --- what `mallinfo2` is actually measuring ---------------------------------
# The lane's premise is that `mallinfo2` sees the main arena only. `man
# mallinfo2` says so under BUGS; glibc's `__libc_mallinfo2` appears to walk the
# arena ring. These four tests are the discriminator that settles it from data.

def test_mallinfo2_tracking_heap_zero_reads_as_main_arena_only():
    parsed = memory_observability.parse_malloc_info_arenas(
        WEB, anon_mb=675.0, mallinfo2_arena_mb=390.0)
    assert parsed["mallinfo2_scope"] == "main_arena_only"
    assert parsed["mallinfo2_vs_main_arena_mb"] == 0.0
    assert parsed["mallinfo2_vs_top_level_mb"] == -256.0


def test_mallinfo2_tracking_the_total_FALSIFIES_the_premise():
    parsed = memory_observability.parse_malloc_info_arenas(
        WEB, anon_mb=675.0, mallinfo2_arena_mb=646.0)
    assert parsed["mallinfo2_scope"] == "all_arenas"
    assert "FALSIFIED" in parsed["mallinfo2_scope_why"]


def test_mallinfo2_matching_neither_is_not_forced_into_a_branch():
    parsed = memory_observability.parse_malloc_info_arenas(
        WEB, anon_mb=675.0, mallinfo2_arena_mb=500.0)
    assert parsed["mallinfo2_scope"] == "neither"


def test_a_single_arena_cannot_discriminate_and_says_so():
    # main == total by construction. A naive check would read "main_arena_only"
    # off a comparison with no power -- the exact shape of every instrument
    # blindness this codebase keeps recording.
    solo = _xml([_heap(0, 400.0, rest_mb=300.0)], top_system_mb=400.0)
    parsed = memory_observability.parse_malloc_info_arenas(
        solo, anon_mb=500.0, mallinfo2_arena_mb=400.0)
    assert parsed["mallinfo2_scope"] == "indistinguishable"
    assert "cannot discriminate" in parsed["mallinfo2_scope_why"]


def test_small_fixtures_cannot_discriminate_either():
    # Pinned deliberately: with a 2 MB floor on the tolerance, a toy fixture
    # puts main and total within tolerance and the instrument must refuse
    # rather than answer. This is why the other fixtures are production-scale.
    tiny = _xml([_heap(0, 4.0), _heap(1, 2.0)], top_system_mb=6.0)
    parsed = memory_observability.parse_malloc_info_arenas(
        tiny, anon_mb=12.0, mallinfo2_arena_mb=4.0)
    assert parsed["mallinfo2_scope"] == "indistinguishable"


def test_mallinfo2_absent_leaves_scope_absent_but_keeps_the_split():
    parsed = memory_observability.parse_malloc_info_arenas(WEB, anon_mb=675.0)
    assert "mallinfo2_scope" not in parsed
    assert parsed["main_arena_mb"] == 390.0


# --- coverage and the refusals ----------------------------------------------

def test_coverage_and_the_part_no_arena_metric_can_speak_to():
    parsed = memory_observability.parse_malloc_info_arenas(WEB, anon_mb=675.0)
    assert parsed["arena_coverage_pct"] == pytest.approx(95.7, abs=0.2)
    assert parsed["non_arena_anon_mb"] == pytest.approx(29.0, abs=0.2)


def test_unrepresentative_arenas_block_the_split_verdict():
    # `#435`'s refresh-worker regime: the arenas hold a small slice of anon, so
    # no split over them describes the process.
    parsed = memory_observability.parse_malloc_info_arenas(WEB, anon_mb=4600.0)
    assert parsed["arena_coverage_pct"] == pytest.approx(14.0, abs=0.3)
    assert parsed["reads_as"] == "arenas_not_representative"


def test_unknown_coverage_does_not_default_to_a_verdict():
    parsed = memory_observability.parse_malloc_info_arenas(WEB)
    assert parsed["reads_as"] == "coverage_unknown"


def test_single_arena_is_a_falsification_not_a_weak_result():
    solo = _xml([_heap(0, 400.0)], top_system_mb=400.0)
    parsed = memory_observability.parse_malloc_info_arenas(solo, anon_mb=450.0)
    assert parsed["reads_as"] == "single_arena"


def test_a_heap_missing_nr_refuses_to_guess_which_is_main():
    bad = _xml([_heap(0, 390.0, omit_nr=True), _heap(1, 64.0)], top_system_mb=454.0)
    parsed = memory_observability.parse_malloc_info_arenas(bad, anon_mb=470.0)
    assert parsed["split_available"] is False
    assert parsed["main_arena_mb"] is None
    assert parsed["heap_fields_degraded"] is True


def test_a_heap_missing_its_size_fails_reconciliation_rather_than_shrinking_the_residual():
    bad = _xml([_heap(0, 390.0), _heap(1, 64.0, omit_system=True)], top_system_mb=454.0)
    parsed = memory_observability.parse_malloc_info_arenas(bad, anon_mb=470.0)
    assert parsed["heap_fields_degraded"] is True
    assert parsed["reconciles"] is False
    assert parsed["reads_as"] == "reconciliation_failed"


def test_garbage_and_missing_totals_return_none():
    assert memory_observability.parse_malloc_info_arenas("") is None
    assert memory_observability.parse_malloc_info_arenas("not xml") is None
    assert memory_observability.parse_malloc_info_arenas("<other><a/></other>") is None
    assert memory_observability.parse_malloc_info_arenas(
        _xml([_heap(0, 390.0)], top_system_mb=390.0, omit_top_system=True)) is None


def test_no_heaps_at_all_is_named():
    empty = _xml([], top_system_mb=0.5)
    parsed = memory_observability.parse_malloc_info_arenas(empty, anon_mb=100.0)
    assert parsed["arena_count"] == 0
    assert parsed["reads_as"] == "no_arenas_reported"


# --- the live half: gating, throttling, and cost ----------------------------

@pytest.fixture(autouse=True)
def _reset_detail_state():
    memory_observability._MALLOC_ARENA_DETAIL_STATE.update({"at": 0.0, "reading": None})
    yield
    memory_observability._MALLOC_ARENA_DETAIL_STATE.update({"at": 0.0, "reading": None})


def test_detail_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SYNDICATE_MALLOC_ARENA_DETAIL", raising=False)
    assert memory_observability.arena_detail_enabled() is False


@pytest.mark.parametrize("raw,expected", [("1", True), ("true", True), ("ON", True),
                                          ("0", False), ("", False), ("maybe", False)])
def test_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("SYNDICATE_MALLOC_ARENA_DETAIL", raw)
    assert memory_observability.arena_detail_enabled() is expected


def test_detail_reports_its_own_cost_and_pairs_the_instruments(monkeypatch):
    monkeypatch.setattr(memory_observability, "_malloc_info_xml", lambda: WEB)
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat",
                        lambda: {"anon": _mb(675.0)})
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2",
                        lambda: {"available": True, "arena_mb": 390.0})
    got = memory_observability.malloc_arena_detail()
    assert got["mallinfo2_scope"] == "main_arena_only"
    assert got["process_anon_mb"] == pytest.approx(675.0, abs=0.1)
    # The cost is MEASURED, not assumed -- `#241`.
    assert isinstance(got["duration_ms"], float)
    assert got["xml_bytes"] > 0
    assert got["cached"] is False


def test_second_call_inside_the_interval_is_served_from_cache_and_stamped(monkeypatch):
    calls = []

    def _xml_once():
        calls.append(1)
        return WEB

    monkeypatch.setattr(memory_observability, "_malloc_info_xml", _xml_once)
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat", lambda: None)
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2", lambda: {"available": False})
    monkeypatch.setenv("SYNDICATE_MALLOC_ARENA_DETAIL_INTERVAL_SECONDS", "600")

    first = memory_observability.malloc_arena_detail()
    second = memory_observability.malloc_arena_detail()
    assert len(calls) == 1, "the throttle must not take the malloc lock twice"
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["age_s"] >= 0.0


def test_force_bypasses_the_throttle(monkeypatch):
    calls = []
    monkeypatch.setattr(memory_observability, "_malloc_info_xml",
                        lambda: (calls.append(1), WEB)[1])
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat", lambda: None)
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2", lambda: {"available": False})
    monkeypatch.setenv("SYNDICATE_MALLOC_ARENA_DETAIL_INTERVAL_SECONDS", "600")
    memory_observability.malloc_arena_detail()
    memory_observability.malloc_arena_detail(force=True)
    assert len(calls) == 2


def test_a_broken_mallinfo2_crosscheck_does_not_lose_the_arena_split(monkeypatch):
    def _boom():
        raise RuntimeError("no glibc here")

    monkeypatch.setattr(memory_observability, "_malloc_info_xml", lambda: WEB)
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat",
                        lambda: {"anon": _mb(675.0)})
    monkeypatch.setattr(memory_observability, "glibc_mallinfo2", _boom)
    got = memory_observability.malloc_arena_detail()
    assert got is not None
    assert got["main_arena_mb"] == 390.0
    assert "mallinfo2_scope" not in got


def test_off_glibc_returns_none_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(memory_observability, "_malloc_info_xml", lambda: None)
    assert memory_observability.malloc_arena_detail() is None


def test_detail_never_raises_out_of_the_snapshot(monkeypatch):
    def _boom():
        raise RuntimeError("instrument failure")

    monkeypatch.setattr(memory_observability, "_malloc_info_xml", _boom)
    assert memory_observability.malloc_arena_detail() is None


# --- the existing aggregate reading must not have changed -------------------
# `malloc_arena_snapshot()` is consumed by `scripts/run_refresh_worker.py`,
# which belongs to another OPEN lane. Its body was refactored onto the shared
# XML helper, so this pins that the OUTPUT is unchanged.

def test_aggregate_snapshot_still_behaves_after_the_refactor(monkeypatch):
    monkeypatch.setattr(memory_observability, "_malloc_info_xml", lambda: WEB)
    monkeypatch.setattr(memory_observability, "_read_container_memory_stat",
                        lambda: {"anon": _mb(675.0)})
    got = memory_observability.malloc_arena_snapshot()
    assert got["arenas"] == 5
    assert got["system_current_mb"] == 646.0
    assert got["free_held_mb"] == 515.0
    assert got["in_use_mb"] == 131.0
    assert got["arena_coverage_pct"] == pytest.approx(95.7, abs=0.2)
    assert got["reads_as"] == "fragmentation"


def test_aggregate_snapshot_returns_none_off_glibc(monkeypatch):
    monkeypatch.setattr(memory_observability, "_malloc_info_xml", lambda: None)
    assert memory_observability.malloc_arena_snapshot() is None


# --- the defect this lane tripped over --------------------------------------

def test_no_module_level_name_is_defined_twice():
    """`_MALLOC_TRIM_STATE` and `_resolve_malloc_trim` were each defined TWICE
    in this module: once by `#285` (~line 2397) and again ~1,900 lines later
    beside `mallinfo2`. Python keeps the LAST binding, so `#285`'s resolver
    became unreachable and took two things with it silently --

      * the one-time `MALLOC_TRIM_INIT` line, which exists precisely because the
        binding cannot be exercised off Linux and a production log line is its
        only proof; and
      * commit daed5d92, "hold the CDLL, not just the function pointer taken off
        it" -- the duplicate kept only the pointer, re-opening a fixed bug.

    Nothing failed loudly. `malloc_trim` still bound and still trimmed; what was
    lost was the EVIDENCE that it had. This file is 4,000+ lines, which is
    exactly the size at which a second `def` of an existing name is invisible to
    review, so the invariant is pinned here rather than left to notice.
    """
    import ast
    import collections
    import inspect

    tree = ast.parse(inspect.getsource(memory_observability))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
        elif isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
    dupes = {n: c for n, c in collections.Counter(names).items() if c > 1}
    assert not dupes, f"module-level names defined more than once: {dupes}"
