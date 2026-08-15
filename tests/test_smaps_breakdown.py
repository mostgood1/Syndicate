"""`#435` — the smaps reader, calibrated against a fixture with known totals.

WHY A FIXTURE AND NOT ONLY A LIVE READ. Two instruments in this investigation
were shipped uncalibrated and both produced confident wrong answers: a
forward-paging log reader that reported a peak over 1.2s of a 51s window, and a
one-level str/bytes census that concluded "85% of anon is not Python data". The
numbers here are chosen so the expected output is arithmetic, not opinion.

WHAT IT IS FOR. 673MB of the 1,607MB rest-state floor is anon that pymalloc never
allocated. `malloc_info` cannot see it (13.9% coverage, self-labelled
`arena_not_representative`) and the Python censuses cannot see non-Python memory
at all. smaps is the kernel's own accounting — the same one that decides the kill.
"""

from __future__ import annotations

from syndicate.features.shared import memory_observability as mo

# 4 mappings: heap 100MB, one 512MB anonymous mmap, a 2MB anonymous mmap,
# and a file-backed region with 1MB private-dirty.
SMAPS = """\
556000000000-556006400000 rw-p 00000000 00:00 0                          [heap]
Size:             102400 kB
Rss:              102400 kB
Anonymous:        102400 kB
7f0000000000-7f0020000000 rw-p 00000000 00:00 0
Size:             524288 kB
Rss:              524288 kB
Anonymous:        524288 kB
7f1000000000-7f1000200000 rw-p 00000000 00:00 0
Size:               2048 kB
Rss:                2048 kB
Anonymous:          2048 kB
7f2000000000-7f2000100000 r--p 00000000 08:01 1234    /usr/lib/libpython3.11.so
Size:               1024 kB
Rss:                1024 kB
Anonymous:          1024 kB
7ffd00000000-7ffd00021000 rw-p 00000000 00:00 0                          [stack]
Size:                132 kB
Rss:                 132 kB
Anonymous:           132 kB
"""


def test_groups_anon_by_mapping_kind():
    out = mo.parse_smaps(SMAPS)
    by_kind = out["by_kind_mb"]
    assert by_kind["heap"] == 100.0
    assert by_kind["anon_mmap"] == 512.0 + 2.0
    assert by_kind["file_backed"] == 1.0
    assert by_kind["stack"] == round(132 / 1024, 1)


def test_total_is_the_sum_of_every_kind():
    out = mo.parse_smaps(SMAPS)
    assert out["total_anon_mb"] == round(sum(out["by_kind_mb"].values()), 1)
    assert out["region_count"] == 5


def test_anon_mmap_is_bucketed_by_region_size():
    # The bucket is what separates a wall of pymalloc arenas from a handful of
    # large numpy buffers -- there is no name on either to key on.
    buckets = mo.parse_smaps(SMAPS)["anon_mmap_by_size_mb"]
    assert buckets[">64MB"] == 512.0
    assert buckets["1-8MB"] == 2.0
    assert "heap" not in buckets  # named mappings never enter the histogram


def test_file_backed_pages_are_kept_separate_from_anon_mmap():
    # The cgroup counts file-backed pages under `file`, not `anon`. Folding them
    # together is how a page-cache plateau once got reported as a leak.
    by_kind = mo.parse_smaps(SMAPS)["by_kind_mb"]
    assert by_kind["file_backed"] == 1.0
    assert by_kind["anon_mmap"] == 514.0


def test_a_field_line_is_never_parsed_as_a_mapping_header():
    # "Anonymous: 12 kB" and a header both start a line; an unanchored pattern
    # would silently open a new region on every field and report near-zero.
    assert mo._SMAPS_HEADER_RE.match("Anonymous:           132 kB") is None
    assert mo._SMAPS_HEADER_RE.match("VmFlags: rd wr mr mw me ac") is None
    assert mo._SMAPS_HEADER_RE.match(
        "556000000000-556006400000 rw-p 00000000 00:00 0    [heap]"
    ) is not None


def test_mappings_with_no_anonymous_pages_are_dropped():
    text = (
        "7f2000000000-7f2000100000 r--p 00000000 08:01 99 /usr/lib/x.so\n"
        "Size:               1024 kB\n"
        "Anonymous:             0 kB\n"
    )
    out = mo.parse_smaps(text)
    assert out["total_anon_mb"] == 0.0 and out["region_count"] == 0


def test_empty_and_garbage_input_do_not_raise():
    for text in ("", "not smaps at all\n", "Anonymous: 5 kB\n"):
        out = mo.parse_smaps(text)
        assert out["total_anon_mb"] == 0.0


def test_reader_is_capped_per_process():
    saved = mo._SMAPS_STATE["count"]
    try:
        mo._SMAPS_STATE["count"] = mo._SMAPS_MAX_PER_PROCESS
        assert mo.log_smaps_anon_breakdown("unit-test") is None
    finally:
        mo._SMAPS_STATE["count"] = saved


# --- the reconciliation fix -----------------------------------------------
#
# The first production read returned `reconciles: false` at 27.0%. The parse was
# right; the COMPARISON was a category error -- a per-process total against
# cgroup `anon`, which counts the container. This worker runs 8-10 children
# holding ~504MB, so that guard would have fired on every read forever, and a
# guard that always fires is a guard nobody reads.


def test_reconciles_against_the_process_not_the_container(monkeypatch, tmp_path):
    smaps = tmp_path / "smaps"
    smaps.write_text(SMAPS, encoding="utf-8")
    monkeypatch.setattr(mo, "_PROCFS_ROOT", tmp_path.parent)
    monkeypatch.setattr(type(smaps), "exists", lambda self: True, raising=False)
    monkeypatch.setattr(mo, "parse_smaps", lambda text: {"total_anon_mb": 615.1, "by_kind_mb": {}})
    # process anon agrees; container is far larger because of children
    monkeypatch.setattr(mo, "_process_rss_anon_bytes", lambda: int(615.1 * 1024 * 1024))
    monkeypatch.setattr(mo, "_read_container_memory_stat", lambda: {"anon": int(1516.5 * 1024 * 1024)})
    monkeypatch.setattr(mo.Path, "read_text", lambda self, **kw: SMAPS, raising=False)
    mo._SMAPS_STATE["count"] = 0
    out = mo.log_smaps_anon_breakdown("unit-test")
    assert out is not None
    assert out["reconciles"] is True, out
    assert out["reconciles_within_pct"] == 0.0
    # the container figure is kept, but named so it cannot be subtracted blindly
    assert out["cgroup_anon_mb_CONTAINER_SCOPE"] == 1516.5
    assert out["other_processes_anon_mb"] == round(1516.5 - 615.1, 1)


def test_a_real_parse_mismatch_still_fails_the_check(monkeypatch):
    """The guard must stay CAPABLE OF FAILING, or the fix merely disabled it.

    Exercises the real function with a parse that under-reports by 64%, rather
    than asserting the threshold arithmetic inline -- a guard test that never
    calls the guard proves nothing, which is the same defect this whole
    investigation keeps finding in its own instruments.
    """
    monkeypatch.setattr(mo, "parse_smaps", lambda text: {"total_anon_mb": 400.0, "by_kind_mb": {}})
    monkeypatch.setattr(mo, "_process_rss_anon_bytes", lambda: int(1100.0 * 1024 * 1024))
    monkeypatch.setattr(mo, "_read_container_memory_stat", lambda: {})
    monkeypatch.setattr(mo.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(mo.Path, "read_text", lambda self, **kw: SMAPS, raising=False)
    mo._SMAPS_STATE["count"] = 0
    out = mo.log_smaps_anon_breakdown("unit-test-mismatch")
    assert out["reconciles"] is False, out
    assert out["reconciles_within_pct"] == 63.6


def test_rss_anon_is_read_not_vm_rss(tmp_path, monkeypatch):
    # VmRSS includes file-backed pages, which the cgroup counts under `file`.
    status = tmp_path / "self"
    status.mkdir()
    (status / "status").write_text(
        "VmRSS:\t 2000000 kB\nRssAnon:\t 1106900 kB\nRssFile:\t  893100 kB\n", encoding="utf-8"
    )
    monkeypatch.setattr(mo, "_PROCFS_ROOT", tmp_path)
    assert mo._process_rss_anon_bytes() == 1106900 * 1024
