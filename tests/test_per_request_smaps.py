"""Per-request smaps sampling on a named route -- `#632`'s attribution attempt.

WHY A NEW INSTRUMENT RATHER THAN MORE CORRELATION. The coarse approach was tried
and failed on its own terms: attribution emissions fire every 200 solo requests,
giving 3-9 minute intervals and n=13, and after dropping one high-leverage point
every `|r| < 0.45` with Pearson and Spearman disagreeing in SIGN on three of five
routes. Worse, the unnormalised version ranked `/healthz` top at `r=+0.682` -- a
route with `max_mb 0.00` that cannot allocate an 8-64MB mapping -- because
differencing over UNEQUAL intervals let duration drive both sides.

So this measures the thing directly: the size-bucket delta ACROSS ONE REQUEST.

THE SAFETY MODEL IS THE POINT, and every gate here has a specific reason:
- The kernel walks page tables to answer smaps. `#241` is the precedent for
  periodic work assumed to be free that put a production service into a restart
  loop, so this is OFF unless a route allowlist names a route.
- Capped per process, because an allowlisted route under load is still unbounded.
- Solo requests only -- an overlapping request makes the delta unattributable.
- The instrument TIMES ITSELF and reports `sample_ms`. Every guess about the cost
  of periodic work in this repo has been wrong in the expensive direction, so the
  number is measured rather than assumed.
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


def _smaps(big_mb: int) -> str:
    """One large anon mapping of `big_mb`, plus a fixed 16 MB heap."""
    return (_region(0x100000000000, big_mb * MB, big_mb * MB)
            + _region(0x300000000000, 16 * MB, 16 * MB, "[heap]"))


@contextlib.contextmanager
def _profiled(routes: str, big_mb: int = 20, anon_seq=(100.0, 130.0) * 40):
    """Profile on, allowlist set, a synthetic procfs, and a scripted anon series.

    `_process_anon_mb` reads a HARDCODED `/proc/self/smaps_rollup` rather than
    `_PROCFS_ROOT`, so it cannot be redirected the way the smaps read can and has
    to be mocked. Noted rather than worked around silently: it is a real
    testability gap in the older code path, not something this instrument chose.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "self").mkdir()
        (root / "self" / "smaps").write_text(_smaps(big_mb), encoding="utf-8")
        env = {"SYNDICATE_REQUEST_MEMORY_PROFILE": "1",
               "SYNDICATE_SMAPS_PER_REQUEST_ROUTES": routes}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(MOD, "_PROCFS_ROOT", root), \
                mock.patch.object(MOD, "_process_anon_mb", side_effect=list(anon_seq)):
            MOD.reset_request_memory_attribution()
            yield root
    MOD.reset_request_memory_attribution()


def _grow(root: pathlib.Path, big_mb: int) -> None:
    (root / "self" / "smaps").write_text(_smaps(big_mb), encoding="utf-8")


class SamplingGateTests(unittest.TestCase):

    def test_an_UNLISTED_route_is_never_sampled(self) -> None:
        with _profiled("/api/demo") as root:
            token = MOD.note_request_start("/api/other")
            _grow(root, 48)
            MOD.note_request_end(token, "/api/other", emit_every=10 ** 9)

            self.assertNotIn("buckets_before", token or {})
            self.assertEqual(MOD._PER_REQUEST_SMAPS_STATE["routes"], {})

    def test_no_allowlist_means_the_instrument_is_INERT(self) -> None:
        """The default. A page-table walk per request must not be something you
        get by setting the profile flag alone."""
        with _profiled("") as root:
            token = MOD.note_request_start("/api/demo")
            _grow(root, 48)
            MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)

            self.assertNotIn("buckets_before", token or {})
            self.assertEqual(MOD._PER_REQUEST_SMAPS_STATE["count"], 0)

    def test_a_LISTED_route_records_the_8_64MB_delta_across_the_request(self) -> None:
        """The measurement `#632` actually needs: 20 MB -> 48 MB inside one
        request is +28 MB in the large-mapping bucket."""
        with _profiled("/api/demo") as root:
            token = MOD.note_request_start("/api/demo")
            _grow(root, 48)
            MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)

            entry = MOD._PER_REQUEST_SMAPS_STATE["routes"]["/api/demo"]
            self.assertEqual(entry["n"], 1)
            self.assertAlmostEqual(entry["sum_8_64mb"], 28.0, places=1)
            self.assertAlmostEqual(entry["max_8_64mb"], 28.0, places=1)

    def test_a_request_that_frees_records_a_NEGATIVE_delta(self) -> None:
        """Large mappings ARE returned to the OS -- one production interval fell
        -43.4 MB. A sampler that could only report growth would hide exactly the
        evidence that this is churn rather than monotonic retention."""
        with _profiled("/api/demo", big_mb=48) as root:
            token = MOD.note_request_start("/api/demo")
            _grow(root, 20)
            MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)

            entry = MOD._PER_REQUEST_SMAPS_STATE["routes"]["/api/demo"]
            self.assertAlmostEqual(entry["sum_8_64mb"], -28.0, places=1)

    def test_multiple_requests_ACCUMULATE_and_keep_the_max(self) -> None:
        with _profiled("/api/demo") as root:
            for target in (30, 40):
                token = MOD.note_request_start("/api/demo")
                _grow(root, target)
                MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)
                _grow(root, 20)

            entry = MOD._PER_REQUEST_SMAPS_STATE["routes"]["/api/demo"]
            self.assertEqual(entry["n"], 2)
            self.assertAlmostEqual(entry["max_8_64mb"], 20.0, places=1)
            self.assertAlmostEqual(entry["sum_8_64mb"], 30.0, places=1)

    def test_the_budget_is_ENFORCED(self) -> None:
        """An allowlisted route under load is still unbounded without this."""
        with _profiled("/api/demo"), \
                mock.patch.dict(os.environ, {"SYNDICATE_SMAPS_PER_REQUEST_SAMPLES": "2"},
                                clear=False):
            for _ in range(4):
                token = MOD.note_request_start("/api/demo")
                MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)

            self.assertEqual(MOD._PER_REQUEST_SMAPS_STATE["count"], 2)

    def test_an_unparseable_budget_falls_back_to_the_DEFAULT(self) -> None:
        with mock.patch.dict(os.environ, {"SYNDICATE_SMAPS_PER_REQUEST_SAMPLES": "all"},
                             clear=False):
            self.assertEqual(MOD._per_request_smaps_budget(),
                             MOD._PER_REQUEST_SMAPS_MAX_DEFAULT)

    def test_the_allowlist_accepts_several_routes_and_strips_whitespace(self) -> None:
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_SMAPS_PER_REQUEST_ROUTES": "/a, /b ,/c"},
                             clear=False):
            self.assertEqual(MOD._per_request_smaps_routes(), frozenset({"/a", "/b", "/c"}))

    def test_the_allowlist_is_re_read_so_it_can_be_changed_without_a_rebuild(self) -> None:
        """Not cached. An allowlist frozen at import would mean the only way to
        point this at a different route is a deploy, and a deploy restarts the
        process whose growth is being measured."""
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_SMAPS_PER_REQUEST_ROUTES": "/first"}, clear=False):
            self.assertEqual(MOD._per_request_smaps_routes(), frozenset({"/first"}))
        with mock.patch.dict(os.environ,
                             {"SYNDICATE_SMAPS_PER_REQUEST_ROUTES": "/second"}, clear=False):
            self.assertEqual(MOD._per_request_smaps_routes(), frozenset({"/second"}))


class ContaminationTests(unittest.TestCase):

    def test_a_request_that_was_NOT_SOLO_is_discarded_not_recorded(self) -> None:
        """An overlapping request makes the delta unattributable. Recording it
        anyway is how a number that means nothing enters a ledger -- and this
        investigation has twice acted on a number that was internally consistent
        and wrong."""
        with _profiled("/api/demo") as root:
            outer = MOD.note_request_start("/api/demo")
            self.assertIn("buckets_before", outer or {})
            inner = MOD.note_request_start("/api/demo")   # overlaps -> not solo
            self.assertIsNone(inner)
            _grow(root, 48)
            MOD.note_request_end(inner, "/api/demo", emit_every=10 ** 9)
            MOD.note_request_end(outer, "/api/demo", emit_every=10 ** 9)

            self.assertEqual(MOD._PER_REQUEST_SMAPS_STATE["routes"], {},
                             "a contaminated window must leave no row")


class PayloadTests(unittest.TestCase):

    def test_the_attribution_payload_carries_the_per_route_rows(self) -> None:
        with _profiled("/api/demo") as root:
            token = MOD.note_request_start("/api/demo")
            _grow(root, 48)
            MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)
            payload = MOD.request_memory_attribution_payload()

            self.assertEqual(payload["per_request_smaps_samples"], 1)
            self.assertAlmostEqual(
                payload["per_request_smaps"]["/api/demo"]["sum_8_64mb"], 28.0, places=1)

    def test_it_reports_what_the_INSTRUMENT_cost(self) -> None:
        """`sample_ms` is measured, not assumed. Every guess about the price of
        periodic work in this repo has been wrong in the expensive direction."""
        with _profiled("/api/demo") as root:
            token = MOD.note_request_start("/api/demo")
            _grow(root, 48)
            MOD.note_request_end(token, "/api/demo", emit_every=10 ** 9)

            entry = MOD._PER_REQUEST_SMAPS_STATE["routes"]["/api/demo"]
            self.assertIn("sum_ms", entry)
            self.assertGreaterEqual(entry["sum_ms"], 0.0)

    def test_an_unsampled_process_publishes_empty_not_a_crash(self) -> None:
        MOD.reset_request_memory_attribution()
        payload = MOD.request_memory_attribution_payload()

        self.assertEqual(payload["per_request_smaps"], {})
        self.assertEqual(payload["per_request_smaps_samples"], 0)

    def test_reset_clears_the_rows(self) -> None:
        MOD._PER_REQUEST_SMAPS_STATE.update({"count": 3, "routes": {"/x": {"n": 3}}})

        MOD.reset_request_memory_attribution()

        self.assertEqual(MOD._PER_REQUEST_SMAPS_STATE, {"count": 0, "routes": {}})


class BackwardCompatibilityTests(unittest.TestCase):

    def test_note_request_start_still_works_with_NO_route(self) -> None:
        """The parameter is optional. Every other caller, and every existing
        test, passes nothing."""
        with _profiled("/api/demo"):
            token = MOD.note_request_start()

            self.assertIsNotNone(token)
            self.assertNotIn("buckets_before", token)


if __name__ == "__main__":
    unittest.main()
