"""Does reassigning `LAST_RESULT` explain `#632`'s negative route totals?

THE GARBAGE COLLECTOR IS AFFIRMATIVELY EXCLUDED, not merely unsupported.
Measured 2026-09-04 across 7 emissions on `3ee5e4b0`: the ONLY
gen-2-overlapping request read **+32.344 MB (positive)**, while the
non-overlapping group swung to **-30.108 MB**. The negatives live entirely in
requests where no collection ran, which is the opposite of that hypothesis.

CPython frees on refcount zero, with no collector involved. So a statement that
drops the last reference to a large object allocated by an EARLIER request
refunds that memory inside the CURRENT request's window, and before/after
differencing charges the refund to whoever happens to be running.

`LAST_RESULT` is exactly that shape: a module-level global in
`blueprints/intelligence.py`, reassigned on every query, holding a copy of the
intelligence payload. Each query allocates a new one and releases the previous
one in the same statement.

WHY ALLOC AND FREE ARE RECORDED SEPARATELY. A new value the same size as the old
nets to ~0. Recording only the net is how this mechanism stayed invisible through
three rounds of this investigation -- cross-worker, background loops, and GC were
all investigated while the net-zero reassignment sat in the measured path.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class NoteGlobalReassignTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def test_alloc_and_free_are_kept_APART(self) -> None:
        """The whole point: a same-size replacement nets to zero and must still
        be visible as a large allocation AND a large refund."""
        MOD.note_global_reassign("LAST_RESULT", 40.0, -39.5)

        row = MOD.request_memory_attribution_payload()["global_reassign"]["LAST_RESULT"]
        self.assertEqual(row["n"], 1)
        self.assertAlmostEqual(row["alloc_mb"], 40.0)
        self.assertAlmostEqual(row["free_mb"], -39.5)
        self.assertNotEqual(row["alloc_mb"] + row["free_mb"], row["alloc_mb"],
                            "net alone would read ~0 and hide the mechanism")

    def test_the_extremes_are_kept_in_the_right_direction(self) -> None:
        """`max_free_mb` tracks the most NEGATIVE refund; taking max() of a
        negative series would record the smallest refund and read as ~0."""
        MOD.note_global_reassign("LAST_RESULT", 10.0, -5.0)
        MOD.note_global_reassign("LAST_RESULT", 80.0, -75.0)

        row = MOD.request_memory_attribution_payload()["global_reassign"]["LAST_RESULT"]
        self.assertAlmostEqual(row["max_alloc_mb"], 80.0)
        self.assertAlmostEqual(row["max_free_mb"], -75.0)

    def test_unreadable_halves_are_skipped_not_counted_as_zero(self) -> None:
        """A missing reading is not a measurement of nothing."""
        MOD.note_global_reassign("LAST_RESULT", None, None)

        row = MOD.request_memory_attribution_payload()["global_reassign"]["LAST_RESULT"]
        self.assertEqual(row["n"], 1)
        self.assertEqual(row["alloc_mb"], 0.0)
        self.assertEqual(row["free_mb"], 0.0)

    def test_reset_clears_it(self) -> None:
        MOD.note_global_reassign("LAST_RESULT", 1.0, -1.0)
        MOD.reset_request_memory_attribution()

        self.assertEqual(MOD.request_memory_attribution_payload()["global_reassign"], {})


class MeasurePairTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def test_the_pair_costs_NOTHING_when_the_profile_is_off(self) -> None:
        """This sits on a request path; it must not read /proc when disabled."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_REQUEST_MEMORY_PROFILE", None)
            with mock.patch.object(MOD, "_process_anon_mb") as reader:
                before, label = MOD.measure_global_reassign("LAST_RESULT")
                MOD.finish_global_reassign(before, label, None)

        self.assertIsNone(before)
        self.assertIsNone(label)
        reader.assert_not_called()
        self.assertEqual(MOD.request_memory_attribution_payload()["global_reassign"], {})

    def test_a_full_pair_records_both_halves(self) -> None:
        with mock.patch.dict(os.environ, {"SYNDICATE_REQUEST_MEMORY_PROFILE": "on"}, clear=False), \
             mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 160.0]):
            before, label = MOD.measure_global_reassign("LAST_RESULT")   # 100.0
            mid = 158.0                                                  # after allocating
            MOD.finish_global_reassign(before, label, mid)               # 160.0 after freeing

        row = MOD.request_memory_attribution_payload()["global_reassign"]["LAST_RESULT"]
        self.assertAlmostEqual(row["alloc_mb"], 58.0)
        self.assertAlmostEqual(row["free_mb"], 2.0)

    def test_an_unopened_pair_is_a_no_op(self) -> None:
        MOD.finish_global_reassign(None, None, None)
        self.assertEqual(MOD.request_memory_attribution_payload()["global_reassign"], {})


class CallSiteTests(unittest.TestCase):

    def test_the_query_route_measures_the_reassignment(self) -> None:
        """The probe must be ON the statement that reassigns the global, with the
        old value's release INSIDE the measured span -- otherwise the refund
        lands outside and the mechanism stays invisible."""
        import inspect
        from syndicate.blueprints import intelligence

        src = inspect.getsource(intelligence.intelligence_query_api)
        self.assertIn("measure_global_reassign(\"LAST_RESULT\")", src)
        self.assertIn("_lr_prev = LAST_RESULT", src)
        assign = src.index("_lr_prev = LAST_RESULT")
        release = src.index("del _lr_prev")
        finish = src.index("finish_global_reassign")
        self.assertLess(assign, release, "the old value must be held, then released")
        self.assertLess(release, finish, "the release must be INSIDE the measured span")


if __name__ == "__main__":
    unittest.main()
