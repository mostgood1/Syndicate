"""Measure `malloc_trim`, and refuse to over-read it. `#632`.

`mallinfo2` measured ~200 MB per worker freed-but-retained in glibc's arena
against only ~72 MB in use. `malloc_trim` is the call that hands free pages back.

Two properties make the measurement trustworthy rather than merely favourable:

* **glibc's own return value is reported verbatim** (1 = released, 0 = could
  not), instead of being inferred from the deltas. A 0 beside a large apparent
  drop would mean something ELSE moved the memory.
* **`in_use` must not move.** Trim releases FREE pages; if allocated bytes
  changed during the call, the process was doing other work and the deltas are
  not attributable to the trim.

The DURATION is a first-class output, because a long malloc-lock hold on a live
service is its own defect -- "it freed 200 MB" is not worth having if it stalled
every request to do it.
"""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


def _info(available=True, arena=270.0, free=200.0, in_use=70.0, free_pct=74.0):
    if not available:
        return {"available": False, "why": "nope"}
    return {"available": True, "arena_mb": arena, "free_in_arena_mb": free,
            "in_use_mb": in_use, "free_pct_of_glibc": free_pct}


class TrimMeasurementTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD._MALLOC_TRIM_STATE.update({"resolved": False, "fn": None, "why": None})

    tearDown = setUp

    def test_a_successful_trim_reports_the_anon_DROP_and_glibc_return(self) -> None:
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=lambda _p: 1), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  side_effect=[_info(arena=270.0, free=200.0),
                                               _info(arena=80.0, free=10.0)]), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=[450.0, 260.0]):
            result = MOD.malloc_trim_now()

        self.assertEqual(result["malloc_trim_returned"], 1)
        self.assertAlmostEqual(result["anon_delta_mb"], -190.0, places=1)
        self.assertAlmostEqual(result["arena_delta_mb"], -190.0, places=1)
        self.assertAlmostEqual(result["free_in_arena_delta_mb"], -190.0, places=1)

    def test_glibc_returning_ZERO_is_reported_not_inferred(self) -> None:
        """A 0 beside a large apparent drop means something else moved the
        memory, and the reading is not ours to claim."""
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=lambda _p: 0), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  side_effect=[_info(), _info()]), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=[450.0, 250.0]):
            result = MOD.malloc_trim_now()

        self.assertEqual(result["malloc_trim_returned"], 0)
        self.assertAlmostEqual(result["anon_delta_mb"], -200.0, places=1)

    def test_IN_USE_moving_marks_the_reading_unattributable(self) -> None:
        """The guard against crediting concurrent work to the trim."""
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=lambda _p: 1), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  side_effect=[_info(in_use=70.0),
                                               _info(in_use=130.0)]), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=[450.0, 400.0]):
            result = MOD.malloc_trim_now()

        self.assertFalse(result["in_use_stable"])
        self.assertAlmostEqual(result["in_use_delta_mb"], 60.0, places=1)

    def test_IN_USE_holding_still_marks_the_reading_attributable(self) -> None:
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=lambda _p: 1), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  side_effect=[_info(in_use=70.0),
                                               _info(in_use=71.0)]), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=[450.0, 260.0]):
            result = MOD.malloc_trim_now()

        self.assertTrue(result["in_use_stable"])

    def test_the_DURATION_is_reported(self) -> None:
        """A long malloc-lock hold on a live service is its own defect."""
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=lambda _p: 1), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  side_effect=[_info(), _info()]), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=[450.0, 260.0]):
            result = MOD.malloc_trim_now()

        self.assertIn("duration_ms", result)
        self.assertGreaterEqual(result["duration_ms"], 0.0)

    def test_an_absent_malloc_trim_reports_ABSENT_not_a_zero_delta(self) -> None:
        """A zero delta would read as "trim did nothing", which is a measurement.
        Absence is not."""
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=None):
            result = MOD.malloc_trim_now()

        self.assertFalse(result["available"])
        for key in ("anon_delta_mb", "arena_delta_mb", "malloc_trim_returned"):
            self.assertNotIn(key, result)

    def test_a_raising_call_is_reported_not_swallowed(self) -> None:
        def boom(_pad):
            raise OSError("boom")

        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=boom), \
                mock.patch.object(MOD, "glibc_mallinfo2", return_value=_info()), \
                mock.patch.object(MOD, "_process_anon_mb", return_value=450.0):
            result = MOD.malloc_trim_now()

        self.assertFalse(result["available"])
        self.assertIn("call failed", result["why"])

    def test_unreadable_anon_yields_None_delta_not_zero(self) -> None:
        with mock.patch.object(MOD, "_resolve_malloc_trim", return_value=lambda _p: 1), \
                mock.patch.object(MOD, "glibc_mallinfo2",
                                  side_effect=[_info(), _info()]), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=[None, None]):
            result = MOD.malloc_trim_now()

        self.assertIsNone(result["anon_delta_mb"])


class RouteSafetyTests(unittest.TestCase):

    def test_the_endpoint_is_POST_only(self) -> None:
        """It mutates allocator state and takes the malloc lock. A GET would be
        reachable by a crawler, an uptime monitor, a browser prefetch or a
        link-preview fetcher -- none of which should stall every request on a
        worker."""
        from syndicate.app import app

        rules = [r for r in app.url_map.iter_rules()
                 if str(r.rule) == "/api/ops/glibc-malloc-trim"]

        self.assertEqual(len(rules), 1)
        self.assertIn("POST", rules[0].methods)
        self.assertNotIn("GET", rules[0].methods)


if __name__ == "__main__":
    unittest.main()
