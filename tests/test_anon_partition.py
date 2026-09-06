"""Tests for the anon PARTITION. `#632`, lane `web-oom-non-malloc-anon`.

`UPDATE 25` left a specific hole: glibc's arena fills to a ~390 MB ceiling and
stops, `hblkhd` is 0.4 MB, and 205.1 MB (34.4%) of pid 97's anon belongs to no
allocator this investigation had measured. This partition names it.

The arithmetic is where a plausible wrong answer gets made, so the pure function
carries every refusal and these tests are mostly about the REFUSALS -- the cases
where the instrument must decline rather than publish a tidy number.

Fixture numbers are the real production ones (pid 97: anon 595.6, glibc 390.5).
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import memory_observability


def _glibc(total_mb: float | None):
    if total_mb is None:
        return {"available": False, "why": "not glibc"}
    return {"available": True, "glibc_total_mb": total_mb}


def _smaps(file_backed: float, stack: float, total_anon: float | None = None):
    out = {
        "by_kind_mb": {"file_backed": file_backed, "stack": stack,
                       "anon_mmap": 400.0, "heap": 60.0},
        "anon_mmap_by_size_mb": {"8-64MB": 300.0, "1-8MB": 100.0},
        "largest_regions_mb": [(64.0, "anon:64.0MB")],
    }
    if total_anon is not None:
        out["total_anon_mb"] = total_anon
    return out


def _build(anon=595.6, glibc=390.5, pymalloc=150.0, file_backed=40.0, stack=1.0,
           smaps_total=None):
    return memory_observability.build_anon_partition(
        anon_mb=anon,
        smaps=_smaps(file_backed, stack, smaps_total),
        glibc=_glibc(glibc),
        pymalloc={"arena_mb": pymalloc} if pymalloc is not None else None,
    )


# --- the partition itself ----------------------------------------------------

def test_terms_are_named_with_the_instrument_that_produced_each():
    got = _build()
    assert got["terms"] == {"glibc_malloc": 390.5, "pymalloc_arenas": 150.0,
                            "so_private_dirty": 40.0, "main_thread_stack": 1.0}
    assert got["sources"]["glibc_malloc"] == "mallinfo2 arena+hblkhd"
    assert got["sources"]["pymalloc_arenas"] == "sys._debugmallocstats arenas"
    assert got["sources"]["so_private_dirty"] == "smaps by_kind file_backed"


def test_a_partition_that_adds_up_reads_as_explained():
    got = _build()
    assert got["named_total_mb"] == pytest.approx(581.5, abs=0.2)
    assert got["residual_mb"] == pytest.approx(14.1, abs=0.2)
    assert got["residual_pct_of_anon"] == pytest.approx(2.4, abs=0.2)
    assert got["reads_as"] == "explained"


def test_the_dominant_term_is_reported_not_left_to_the_reader():
    got = _build()
    assert got["largest_named_term"] == "glibc_malloc"
    assert got["largest_named_term_mb"] == 390.5


def test_a_real_residual_is_named_unexplained_and_points_at_the_buckets():
    # pymalloc small: the 205 MB hole stays open.
    got = _build(pymalloc=10.0, file_backed=5.0)
    assert got["residual_mb"] == pytest.approx(189.1, abs=0.2)
    assert got["reads_as"] == "residual_unexplained"
    assert "size buckets" in got["why"]
    assert got["anon_mmap_by_size_mb"] == {"8-64MB": 300.0, "1-8MB": 100.0}


# --- the refusals ------------------------------------------------------------

def test_terms_summing_past_anon_REFUSES_and_names_the_likely_cause():
    # The load-bearing check. A CPython built without ARENA_USE_MMAP takes its
    # pymalloc arenas from malloc, so they are already inside the glibc figure
    # and adding them double counts -- inflating the explained share and
    # shrinking the residual toward a tidy, wrong answer.
    got = _build(pymalloc=300.0)
    assert got["reads_as"] == "terms_overlap"
    assert got["overlap_mb"] == pytest.approx(135.9, abs=0.3)
    assert "ARENA_USE_MMAP" in got["why"]
    assert "No attribution below is usable" in got["why"]


def test_a_small_negative_is_slack_not_overlap():
    # Three readings that are not atomic can cross slightly. The overlap bar is
    # max(8 MB, 5% of anon) -- 29.8 MB here -- so a 5 MB cross is not a finding.
    got = _build(pymalloc=169.1)
    assert got["residual_mb"] == pytest.approx(-5.0, abs=0.3)
    assert got["reads_as"] != "terms_overlap"


def test_an_unreadable_term_blocks_calling_the_residual_unexplained():
    got = _build(pymalloc=None)
    assert got["terms"]["pymalloc_arenas"] is None
    assert "UNAVAILABLE" in got["sources"]["pymalloc_arenas"]
    assert got["terms_unavailable"] == ["pymalloc_arenas"]
    assert got["reads_as"] == "incomplete"
    assert "inflated by whatever they hold" in got["why"]


def test_glibc_reporting_unavailable_is_a_missing_term_not_a_zero():
    got = _build(glibc=None)
    assert got["terms"]["glibc_malloc"] is None
    assert got["reads_as"] == "incomplete"


def test_no_anon_reading_refuses_before_any_arithmetic():
    got = _build(anon=None)
    assert got["reads_as"] == "no_anon_reading"
    assert "residual_mb" not in got


def test_no_smaps_leaves_two_terms_unavailable():
    got = memory_observability.build_anon_partition(
        anon_mb=595.6, smaps=None, glibc=_glibc(390.5), pymalloc={"arena_mb": 150.0})
    assert got["terms_unavailable"] == ["so_private_dirty", "main_thread_stack"]
    assert got["reads_as"] == "incomplete"


# --- the second kernel read --------------------------------------------------

def test_smaps_own_total_is_checked_against_the_rollup():
    # Two independent kernel reads of the same quantity. If they disagree, one
    # of them is not measuring what its name says.
    ok = _build(smaps_total=594.0)
    assert ok["smaps_vs_rollup_mb"] == pytest.approx(-1.6, abs=0.2)
    assert ok["smaps_agrees_with_rollup"] is True

    bad = _build(smaps_total=400.0)
    assert bad["smaps_agrees_with_rollup"] is False


# --- the live half -----------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    memory_observability._ANON_PARTITION_STATE.update({"at": 0.0, "reading": None})
    memory_observability._ANON_PARTITION_PYMALLOC_BUDGET["count"] = 0
    yield
    memory_observability._ANON_PARTITION_STATE.update({"at": 0.0, "reading": None})
    memory_observability._ANON_PARTITION_PYMALLOC_BUDGET["count"] = 0


def test_partition_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SYNDICATE_ANON_PARTITION", raising=False)
    assert memory_observability.anon_partition_enabled() is False


@pytest.mark.parametrize("raw,expected", [("1", True), ("on", True), ("TRUE", True),
                                          ("0", False), ("", False), ("later", False)])
def test_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("SYNDICATE_ANON_PARTITION", raw)
    assert memory_observability.anon_partition_enabled() is expected


def test_it_does_not_use_the_shared_pymalloc_budget(monkeypatch):
    """The shared cap is THREE calls per process -- sized for a one-shot
    diagnostic. A 30-minute window would get three real readings and then a
    stream of `incomplete` ones that look like a finding rather than an
    exhausted counter."""
    shared_before = dict(memory_observability._PYMALLOC_STATS_STATE)
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 595.6)
    for _ in range(6):
        memory_observability.anon_partition(force=True)
    assert memory_observability._PYMALLOC_STATS_STATE == shared_before
    assert memory_observability._ANON_PARTITION_PYMALLOC_BUDGET["count"] == 6
    assert memory_observability._ANON_PARTITION_PYMALLOC_MAX > 100


def test_reading_is_cached_and_stamped_within_the_interval(monkeypatch):
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 595.6)
    monkeypatch.setenv("SYNDICATE_ANON_PARTITION_INTERVAL_SECONDS", "600")
    first = memory_observability.anon_partition()
    second = memory_observability.anon_partition()
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["age_s"] >= 0.0
    # The expensive readings were taken once, not twice.
    assert memory_observability._ANON_PARTITION_PYMALLOC_BUDGET["count"] == 1


def test_force_bypasses_the_throttle(monkeypatch):
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 595.6)
    monkeypatch.setenv("SYNDICATE_ANON_PARTITION_INTERVAL_SECONDS", "600")
    memory_observability.anon_partition()
    memory_observability.anon_partition(force=True)
    assert memory_observability._ANON_PARTITION_PYMALLOC_BUDGET["count"] == 2


def test_it_reports_its_own_cost(monkeypatch):
    monkeypatch.setattr(memory_observability, "_process_anon_mb", lambda: 595.6)
    got = memory_observability.anon_partition(force=True)
    assert isinstance(got["duration_ms"], float)
    assert got["pid"] > 0


def test_it_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("instrument failure")

    monkeypatch.setattr(memory_observability, "_process_anon_mb", _boom)
    # Must not propagate: telemetry cannot be allowed to fail a request.
    memory_observability.anon_partition(force=True)


def test_pymalloc_reader_actually_returns_a_number_here():
    """This one runs for real. `_debugmallocstats` is not Linux-only, so unlike
    every other term in this partition the pymalloc reading can be exercised on
    the machine running these tests -- which is the only end-to-end proof
    available off Render that the parse works at all."""
    got = memory_observability.log_pymalloc_arena_stats(
        "test", budget=({"count": 0}, 5), quiet=True)
    assert got is not None
    assert isinstance(got["arena_mb"], float)
    assert got["arena_mb"] > 0
    assert got["captured_chars"] > 0


# --- the threshold, calibrated against a real fault ---------------------------

def test_the_production_false_positive_is_now_slack():
    """Measured on the live instrument within minutes of deploying it: residual
    -4.3 MB on a 209.0 MB process tripped `terms_overlap` against a 2%/2 MB bar
    of 4.18. Four megabytes is what a worker serving traffic allocates between
    three sequential readings -- not two terms counting the same bytes."""
    got = memory_observability.build_anon_partition(
        anon_mb=209.0,
        smaps=_smaps(4.4, 0.1),
        glibc=_glibc(104.8),
        pymalloc={"arena_mb": 104.0},
    )
    assert got["residual_mb"] == pytest.approx(-4.3, abs=0.2)
    assert got["reads_as"] != "terms_overlap"


def test_the_bar_still_catches_a_whole_term_double_counted():
    """The fault it exists for: a CPython without ARENA_USE_MMAP, where the whole
    pymalloc term is already inside glibc's figure. That is ~100 MB at boot, an
    order of magnitude above the slack the bar now tolerates."""
    got = memory_observability.build_anon_partition(
        anon_mb=209.0,
        smaps=_smaps(4.4, 0.1),
        glibc=_glibc(104.8),
        pymalloc={"arena_mb": 204.0},
    )
    assert got["reads_as"] == "terms_overlap"
    assert got["overlap_mb"] == pytest.approx(104.3, abs=0.3)
    assert "ARENA_USE_MMAP" in got["why"]


def test_the_two_bars_are_independent():
    # The read-agreement check compares two reads of the SAME quantity and keeps
    # the tight bar; the overlap bar is deliberately looser.
    got = _build(anon=209.0, glibc=104.8, pymalloc=104.0, file_backed=4.4,
                 stack=0.1, smaps_total=203.0)
    assert got["overlap_bar_mb"] == pytest.approx(10.45, abs=0.1)
    assert got["smaps_agrees_with_rollup"] is False   # 6.0 MB apart, tight bar
    assert got["reads_as"] != "terms_overlap"         # 4.3 MB under, loose bar
