"""glibc's own accounting, for the 71.7% of anon that is not Python. `#632`.

A converged object-graph walk put live Python objects at **28.3%** of a worker's
anon, and at **0.3% of the GROWTH**. No Python-level probe can reach the rest, so
the question moves below CPython.

**THIS IS NOT THE CALL `#435` TRIED.** That used `malloc_info` -- per-arena XML,
13.9% coverage, structurally unable to see mmapped chunks. `mallinfo2.hblkhd` is
*space allocated in mmapped regions*, which is exactly the 8-64MB class the smaps
trend identified as the growing term.

The instrument exists to split two cases with OPPOSITE fixes:

* `arena + hblkhd` vs anon -- is the memory in glibc at all? If not, the bytes
  bypass malloc entirely and even this is the wrong layer.
* `uordblks` vs `fordblks`/`keepcost` -- in use, or freed but retained? Retained
  is returnable with `malloc_trim()`; in use means a C owner to find.
"""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


def _fake(arena_mb=0.0, hblkhd_mb=0.0, in_use_mb=0.0, free_mb=0.0,
          keepcost_mb=0.0, hblks=0):
    mb = 1024 * 1024
    info = MOD._Mallinfo2()
    info.arena = int(arena_mb * mb)
    info.hblks = int(hblks)
    info.hblkhd = int(hblkhd_mb * mb)
    info.uordblks = int(in_use_mb * mb)
    info.fordblks = int(free_mb * mb)
    info.keepcost = int(keepcost_mb * mb)
    return lambda: info


class ReconciliationTests(unittest.TestCase):
    """`glibc_pct_of_anon` decides whether this layer is even the right one."""

    def test_glibc_holding_most_of_anon_reads_near_100_pct(self) -> None:
        with mock.patch.object(MOD, "_resolve_mallinfo2",
                               return_value=_fake(arena_mb=120.0, hblkhd_mb=240.0)), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=380.0):
            info = MOD.glibc_mallinfo2()

        self.assertAlmostEqual(info["glibc_total_mb"], 360.0, places=1)
        self.assertAlmostEqual(info["glibc_pct_of_anon"], 94.7, places=1)

    def test_glibc_holding_LITTLE_of_anon_is_the_falsification_case(self) -> None:
        """If glibc accounts for a small slice, the bytes bypass malloc -- a C
        extension calling `mmap` directly -- and even this instrument is looking
        at the wrong layer. That must be visible, not buried."""
        with mock.patch.object(MOD, "_resolve_mallinfo2",
                               return_value=_fake(arena_mb=20.0, hblkhd_mb=15.0)), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=380.0):
            info = MOD.glibc_mallinfo2()

        self.assertLess(info["glibc_pct_of_anon"], 10.0)

    def test_the_ratio_is_None_when_anon_is_unreadable(self) -> None:
        """Not zero. A zero would assert glibc explains none of the memory."""
        with mock.patch.object(MOD, "_resolve_mallinfo2",
                               return_value=_fake(arena_mb=50.0, hblkhd_mb=50.0)), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=None):
            info = MOD.glibc_mallinfo2()

        self.assertIsNone(info["glibc_pct_of_anon"])
        self.assertIsNone(info["process_anon_mb"])

    def test_MMAPPED_space_is_reported_separately_from_the_arena(self) -> None:
        """The whole reason for this call over `malloc_info`: mmapped chunks are
        the 8-64MB class, and an arena-only view cannot see them."""
        with mock.patch.object(MOD, "_resolve_mallinfo2",
                               return_value=_fake(arena_mb=90.0, hblkhd_mb=300.0, hblks=42)), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=400.0):
            info = MOD.glibc_mallinfo2()

        self.assertAlmostEqual(info["mmapped_mb"], 300.0, places=1)
        self.assertEqual(info["mmapped_regions"], 42)
        self.assertAlmostEqual(info["arena_mb"], 90.0, places=1)


class InUseVersusRetainedTests(unittest.TestCase):
    """The split that decides the FIX."""

    def test_mostly_FREE_means_malloc_trim_has_something_to_return(self) -> None:
        with mock.patch.object(MOD, "_resolve_mallinfo2",
                               return_value=_fake(arena_mb=400.0, hblkhd_mb=0.0,
                                                  in_use_mb=40.0, free_mb=360.0,
                                                  keepcost_mb=200.0)), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=420.0):
            info = MOD.glibc_mallinfo2()

        self.assertAlmostEqual(info["free_pct_of_glibc"], 90.0, places=1)
        self.assertAlmostEqual(info["releasable_top_mb"], 200.0, places=1)

    def test_mostly_IN_USE_means_a_C_owner_to_find(self) -> None:
        with mock.patch.object(MOD, "_resolve_mallinfo2",
                               return_value=_fake(arena_mb=400.0, hblkhd_mb=0.0,
                                                  in_use_mb=380.0, free_mb=20.0)), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=420.0):
            info = MOD.glibc_mallinfo2()

        self.assertAlmostEqual(info["free_pct_of_glibc"], 5.0, places=1)
        self.assertAlmostEqual(info["in_use_mb"], 380.0, places=1)


class AvailabilityTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD._MALLINFO2_STATE.update({"resolved": False, "fn": None, "why": None})

    tearDown = setUp

    def test_an_absent_mallinfo2_reports_ABSENT_not_ZERO(self) -> None:
        """A zero would assert "glibc holds nothing", which is a claim. Absence
        is the truth on a platform without glibc 2.33+, and the numeric keys must
        not be there to be misread."""
        with mock.patch.object(MOD, "_resolve_mallinfo2", return_value=None):
            info = MOD.glibc_mallinfo2()

        self.assertFalse(info["available"])
        self.assertIn("why", info)
        for key in ("arena_mb", "mmapped_mb", "glibc_total_mb", "glibc_pct_of_anon"):
            self.assertNotIn(key, info)

    def test_a_call_that_RAISES_is_reported_not_swallowed(self) -> None:
        def boom():
            raise OSError("segfault-ish")

        with mock.patch.object(MOD, "_resolve_mallinfo2", return_value=boom):
            info = MOD.glibc_mallinfo2()

        self.assertFalse(info["available"])
        self.assertIn("call failed", info["why"])

    def test_resolution_is_attempted_ONCE_and_cached(self) -> None:
        """It runs behind an ops endpoint anyone can curl; re-resolving a libc
        symbol on every request is waste with no upside."""
        calls = []

        def fake_cdll(_name):
            calls.append(1)
            raise OSError("no libc here")

        with mock.patch.object(MOD.ctypes, "CDLL", fake_cdll):
            MOD._resolve_mallinfo2()
            MOD._resolve_mallinfo2()
            MOD._resolve_mallinfo2()

        self.assertEqual(len(calls), 1)


class StructShapeTests(unittest.TestCase):

    def test_every_field_is_size_t_NOT_int(self) -> None:
        """The reason this uses `mallinfo2` rather than `mallinfo`: the older
        struct declares these as `int`, which SILENTLY WRAPS past 2 GB. On a 2 GB
        service that is precisely the range under measurement, so a wrapped value
        would read as a small, reassuring number."""
        import ctypes

        for name, ctype in MOD._Mallinfo2._fields_:
            self.assertIs(ctype, ctypes.c_size_t, f"{name} must be size_t")

    def test_the_field_ORDER_matches_glibc(self) -> None:
        """These are read positionally out of a C struct. A reordering would
        silently swap, say, `hblkhd` with `usmblks` and produce plausible
        nonsense rather than an error."""
        self.assertEqual(
            [name for name, _ in MOD._Mallinfo2._fields_],
            ["arena", "ordblks", "smblks", "hblks", "hblkhd",
             "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost"])


if __name__ == "__main__":
    unittest.main()
