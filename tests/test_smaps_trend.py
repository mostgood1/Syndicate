"""Anon by REGION SIZE, as a time series -- `#632`'s last available instrument.

FIVE CANDIDATES ARE NOW ELIMINATED BY MEASUREMENT: cross-worker cgroup scope
(confirmed, fixed), background loops (falsified), GC timing (excluded),
`LAST_RESULT` reassignment (excluded), and pymalloc arena fragmentation
(excluded -- arenas were 40% of worker RSS, did not move, and the gap held at
56.6 MB).

That last one is why this file exists. **Arenas can only see the 40%.** Anything
over 512 bytes bypasses pymalloc entirely and goes to malloc/mmap, which a 28 MB
JSON payload certainly does -- so the instrument that came back flat is
structurally incapable of seeing the allocation most likely to be responsible.
`#435` found glibc `malloc_info` blind for the same reason (13.9% coverage).

`parse_smaps` reads the kernel's own accounting and buckets anon by mapping
SIZE, so it can see a large direct mmap that both allocator views miss. The
question `#632` has been circling for five probes finally has a form the data can
answer: WHICH BUCKET GROWS.

The bucketing is what these tests actually exercise. `sample_smaps_trend` needs
procfs and cannot run here, but `parse_smaps` is pure -- so the classification
that the whole conclusion will rest on is tested against synthetic maps with
KNOWN sizes, rather than assumed to be right when the production series arrives.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD

KB = 1024
MB = 1024 * 1024


def _region(start: int, size: int, anon: int, path: str = "") -> str:
    header = f"{start:012x}-{start + size:012x} rw-p 00000000 00:00 0 {path}".rstrip()
    return (
        header + "\n"
        f"Size:           {size // KB} kB\n"
        f"Rss:            {anon // KB} kB\n"
        f"Anonymous:      {anon // KB} kB\n"
    )


class BucketingTests(unittest.TestCase):
    """The classification the production verdict will rest on."""

    def test_a_payload_sized_region_lands_in_8_64MB(self) -> None:
        """THE bucket to watch. A 28 MB intelligence payload is the allocation
        pymalloc cannot see, and this is where it must show up."""
        text = _region(0x700000000000, 28 * MB, 28 * MB)

        buckets = MOD.parse_smaps(text)["anon_mmap_by_size_mb"]

        self.assertAlmostEqual(buckets.get("8-64MB", 0.0), 28.0, places=1)
        self.assertEqual(buckets.get("1-8MB", 0.0), 0.0)

    def test_regions_are_bucketed_by_SIZE_not_by_resident_anon(self) -> None:
        """A 32 MB mapping only 1 MB resident is still an 8-64MB region. Getting
        this backwards would file a large sparse arena under a small bucket and
        invert the reading."""
        text = _region(0x700000000000, 32 * MB, 1 * MB)

        buckets = MOD.parse_smaps(text)["anon_mmap_by_size_mb"]

        self.assertAlmostEqual(buckets.get("8-64MB", 0.0), 1.0, places=1)
        self.assertNotIn("64KB-1MB", buckets)

    def test_each_bucket_boundary_is_exclusive_at_the_TOP(self) -> None:
        """`<64KB` must not swallow exactly 64KB. An off-by-one at a boundary
        moves mass between the two buckets the verdict compares."""
        text = _region(0x700000000000, 64 * KB, 64 * KB)

        buckets = MOD.parse_smaps(text)["anon_mmap_by_size_mb"]

        self.assertNotIn("<64KB", buckets)
        self.assertGreater(buckets.get("64KB-1MB", 0.0), 0.0)

    def test_the_buckets_span_every_scale_at_once(self) -> None:
        text = (
            _region(0x100000000000, 32 * KB, 32 * KB)
            + _region(0x200000000000, 512 * KB, 512 * KB)
            + _region(0x300000000000, 4 * MB, 4 * MB)
            + _region(0x400000000000, 28 * MB, 28 * MB)
            + _region(0x500000000000, 128 * MB, 128 * MB)
        )

        buckets = MOD.parse_smaps(text)["anon_mmap_by_size_mb"]

        self.assertAlmostEqual(buckets["1-8MB"], 4.0, places=1)
        self.assertAlmostEqual(buckets["8-64MB"], 28.0, places=1)
        self.assertAlmostEqual(buckets[">64MB"], 128.0, places=1)

    def test_file_backed_and_heap_anon_are_NOT_in_the_size_buckets(self) -> None:
        """The buckets are for anonymous MMAP only. Folding the heap in would
        make a bucket move that has nothing to do with a direct mmap."""
        text = (
            _region(0x100000000000, 16 * MB, 16 * MB, "/usr/lib/libpython3.11.so")
            + _region(0x200000000000, 16 * MB, 16 * MB, "[heap]")
            + _region(0x300000000000, 16 * MB, 16 * MB)
        )

        parsed = MOD.parse_smaps(text)

        self.assertAlmostEqual(parsed["anon_mmap_by_size_mb"]["8-64MB"], 16.0, places=1)
        self.assertAlmostEqual(parsed["by_kind_mb"]["heap"], 16.0, places=1)
        self.assertAlmostEqual(parsed["by_kind_mb"]["file_backed"], 16.0, places=1)

    def test_total_anon_counts_EVERY_kind_so_it_can_reconcile(self) -> None:
        """`total_anon_mb` is compared against the cgroup's own anon. If it only
        summed the mmap buckets it would never reconcile, and the breakdown would
        be unusable as attribution."""
        text = (
            _region(0x100000000000, 16 * MB, 16 * MB, "[heap]")
            + _region(0x200000000000, 16 * MB, 16 * MB)
        )

        self.assertAlmostEqual(MOD.parse_smaps(text)["total_anon_mb"], 32.0, places=1)

    def test_a_region_with_zero_anon_is_skipped_entirely(self) -> None:
        text = _region(0x100000000000, 64 * MB, 0)

        parsed = MOD.parse_smaps(text)

        self.assertEqual(parsed["total_anon_mb"], 0.0)
        self.assertEqual(parsed["anon_mmap_by_size_mb"], {})

    def test_the_LAST_region_in_the_file_is_not_dropped(self) -> None:
        """A flush-on-next-header parser loses the final entry unless it flushes
        at EOF -- and the final entry is as likely as any to be the big one."""
        text = _region(0x100000000000, 4 * MB, 4 * MB) + _region(0x200000000000, 28 * MB, 28 * MB)

        buckets = MOD.parse_smaps(text)["anon_mmap_by_size_mb"]

        self.assertAlmostEqual(buckets.get("8-64MB", 0.0), 28.0, places=1)


@contextlib.contextmanager
def _fake_procfs(text: str):
    """Point the reader at a synthetic `self/smaps` on disk.

    `_PROCFS_ROOT` is the real seam, so these cases exercise the ACTUAL read and
    parse rather than a stubbed `parse_smaps`. The first draft mocked a
    `_read_smaps_text` that does not exist -- `create=True` invented it, nothing
    read it, and all three cases fell through to "not a Linux procfs" while
    looking like they had mocked something.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "self").mkdir()
        (root / "self" / "smaps").write_text(text, encoding="utf-8")
        with mock.patch.object(MOD, "_PROCFS_ROOT", root):
            yield


_ONE_REGION = _region(0x100000000000, 28 * MB, 28 * MB)


class BudgetSeparationTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD._SMAPS_TREND_STATE.update({"count": 0, "last": None})
        MOD._SMAPS_STATE["count"] = 0

    tearDown = setUp

    def test_the_trend_does_NOT_spend_the_alarm_census_budget(self) -> None:
        """`_SMAPS_MAX_PER_PROCESS` exists for the watchdog's census when anon is
        already critical. Routine trend sampling must not consume it."""
        with _fake_procfs(_ONE_REGION):
            MOD.sample_smaps_trend("t1")
            MOD.sample_smaps_trend("t2")

        self.assertEqual(MOD._SMAPS_TREND_STATE["count"], 2)
        self.assertEqual(MOD._SMAPS_STATE["count"], 0,
                         "the alarm census's budget must be untouched")

    def test_the_trend_budget_is_ENFORCED(self) -> None:
        """The kernel walks page tables for smaps -- `#241` is the precedent for
        assuming periodic work is free."""
        with _fake_procfs(_ONE_REGION), \
                mock.patch.dict(os.environ, {"SYNDICATE_SMAPS_TREND_SAMPLES": "2"}, clear=False):
            self.assertIsNotNone(MOD.sample_smaps_trend("a"))
            self.assertIsNotNone(MOD.sample_smaps_trend("b"))
            self.assertIsNone(MOD.sample_smaps_trend("c"), "past the budget it must refuse")

        self.assertEqual(MOD._SMAPS_TREND_STATE["count"], 2)

    def test_an_unparseable_budget_falls_back_to_the_DEFAULT_not_to_unlimited(self) -> None:
        with mock.patch.dict(os.environ, {"SYNDICATE_SMAPS_TREND_SAMPLES": "lots"}, clear=False):
            self.assertEqual(MOD._smaps_trend_budget(), MOD._SMAPS_TREND_MAX_DEFAULT)


class PayloadTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def test_the_attribution_payload_carries_the_latest_reading(self) -> None:
        text = (_region(0x100000000000, 28 * MB, 28 * MB)
                + _region(0x200000000000, 4 * MB, 4 * MB))
        with _fake_procfs(text):
            MOD.sample_smaps_trend("check")

        payload = MOD.request_memory_attribution_payload()

        self.assertEqual(payload["smaps_trend_samples"], 1)
        self.assertAlmostEqual(payload["smaps_trend"]["total_anon_mb"], 32.0, places=1)
        self.assertAlmostEqual(payload["smaps_trend"]["by_size_mb"]["8-64MB"], 28.0, places=1)

    def test_an_absent_reading_publishes_an_empty_dict_not_a_crash(self) -> None:
        payload = MOD.request_memory_attribution_payload()

        self.assertEqual(payload["smaps_trend"], {})
        self.assertEqual(payload["smaps_trend_samples"], 0)

    def test_the_trend_records_BY_KIND_because_the_buckets_miss_most_of_it(self) -> None:
        """The size buckets cover anon_mmap ONLY, and the first clean series
        showed 65-70% of each worker's climb was somewhere else.

        Recording only `by_size_mb` threw the majority term away and left it as
        a residual computed by subtraction -- a number with no name on it.
        `parse_smaps` already returns `by_kind_mb`; this asserts the trend keeps
        it, and that the two views disagree exactly as they must when non-mmap
        anon is present.
        """
        text = (_region(0x100000000000, 28 * MB, 28 * MB)
                + _region(0x200000000000, 16 * MB, 16 * MB, "[heap]"))
        with _fake_procfs(text):
            MOD.sample_smaps_trend("check")

        last = MOD._SMAPS_TREND_STATE["last"]

        self.assertAlmostEqual(last["by_kind_mb"]["heap"], 16.0, places=1)
        self.assertAlmostEqual(last["by_kind_mb"]["anon_mmap"], 28.0, places=1)
        self.assertNotIn("heap", last["by_size_mb"],
                         "size buckets cover anon_mmap only -- that is the point")
        self.assertAlmostEqual(sum(last["by_size_mb"].values()), 28.0, places=1)
        self.assertAlmostEqual(last["total_anon_mb"], 44.0, places=1)

    def test_the_payload_says_WHICH_WORKER_emitted_it(self) -> None:
        """Two gunicorn workers emit into one log stream, so a series read
        without a pid is TWO interleaved series.

        Measured 2026-09-04: five consecutive emissions alternated between
        processes, and only luck put the same worker at both ends of the
        first-vs-last comparison. This is the cross-worker error that the
        per-process anon fix already corrected at the cgroup level, returning
        one level up at the time series. Splitting on a bucket value that
        happens to differ per worker is an inference; a pid is an identifier.
        """
        payload = MOD.request_memory_attribution_payload()

        self.assertEqual(payload["pid"], os.getpid())

    def test_reset_clears_the_trend_so_a_test_cannot_read_the_PREVIOUS_case(self) -> None:
        MOD._SMAPS_TREND_STATE.update({"count": 7, "last": {"total_anon_mb": 1.0}})

        MOD.reset_request_memory_attribution()

        self.assertEqual(MOD._SMAPS_TREND_STATE, {"count": 0, "last": None})
        self.assertEqual(MOD._ARENA_TREND_STATE, {"count": 0, "last": None})


if __name__ == "__main__":
    unittest.main()
