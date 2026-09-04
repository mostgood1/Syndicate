"""The profiler measures THIS PROCESS, not the container (`#632`).

WHY THE SCOPE MOVED. `_REQUEST_MEMORY_STATE["inflight"]` is module state, so the
"provably alone" guarantee has only ever covered ONE gunicorn worker. The
measurement, `_anon_mb()`, read the per-CONTAINER cgroup. At
`WEB_CONCURRENCY=2` those are different scopes, and a request alone in its own
worker was still charged whatever the sibling worker and every merge subprocess
allocated during its window.

Measured 2026-09-03, that produced an attributed share of **61-150%** depending
on framing -- and a share above 100% is arithmetically impossible for a true
partition. Two direct sightings, either of which is enough on its own:

  * a CUMULATIVE route total FELL: `/api/ops/artifacts/publish` went
    211.59 -> 167.13 MB while its own `solo_n` rose 405 -> 502, and a cumulative
    sum of retained memory cannot decrease;
  * the two workers disagreed in SIGN on the same route one minute apart,
    +102.50 MB against -64.35 MB.

WHY NOT JUST RUN ONE WORKER. Tried. It **evicted the container in 22 minutes**
(`server_failed`, `['evicted','unhealthy']`, 23:37:08Z) because one worker x 4
threads is 4 concurrent slots and `/healthz` queued behind slow artifact
requests. The worker count is not ours to spend, so the instrument changed
instead.
"""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class _Env:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        import os
        self._patch = mock.patch.dict(
            os.environ,
            {} if self._value is None else {"SYNDICATE_REQUEST_MEMORY_PROFILE": self._value},
            clear=False)
        self._patch.start()
        if self._value is None:
            import os as _os
            _os.environ.pop("SYNDICATE_REQUEST_MEMORY_PROFILE", None)
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class ScopeTests(unittest.TestCase):
    """The attribution must read the PROCESS, never the container."""

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()
        MOD._PROCESS_ANON_UNAVAILABLE = False

    tearDown = setUp

    def test_attribution_does_NOT_read_the_container_cgroup(self) -> None:
        """The whole defect in one assertion. If `_anon_mb` is consulted for a
        delta, the sibling worker is back inside the number."""
        with _Env("on"), \
             mock.patch.object(MOD, "_process_anon_mb", side_effect=[100.0, 130.0]), \
             mock.patch.object(MOD, "_anon_mb") as container:
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)

        row = MOD.request_memory_attribution_payload()["routes"][0]
        self.assertEqual(row["route"], "/mlb/api/cards")
        self.assertAlmostEqual(row["total_mb"], 30.0)
        container.assert_not_called()

    def test_an_unreadable_process_reading_declines_rather_than_falling_back(self) -> None:
        """Falling back to the cgroup would quietly restore the defect. Absent
        must mean "do not attribute", and must be COUNTED so the payload shows
        it -- a silent decline is indistinguishable from a quiet service."""
        with _Env("on"), \
             mock.patch.object(MOD, "_process_anon_mb", return_value=None), \
             mock.patch.object(MOD, "_anon_mb", return_value=500.0) as container:
            token = MOD.note_request_start()
            MOD.note_request_end(token, "/mlb/api/cards", emit_every=10_000)

        payload = MOD.request_memory_attribution_payload()
        self.assertEqual(payload["routes"], [])
        self.assertEqual(payload["unreadable"], 1)
        container.assert_not_called()

    def test_the_payload_NAMES_its_basis_so_two_regimes_are_distinguishable(self) -> None:
        """Emissions recorded before this change are deltas of a DIFFERENT
        quantity. Without this key nothing in the log says which is which, and
        the two would be silently averaged together."""
        with _Env("on"), mock.patch.object(MOD, "_process_anon_mb", return_value=1.0):
            payload = MOD.request_memory_attribution_payload()

        self.assertEqual(payload["attribution_basis"], "process_anon_smaps_rollup")
        self.assertIn("process_anon_mb_now", payload)
        self.assertIn("anon_mb_now", payload,
                      "the container reading stays, as context and for continuity")


class SmapsRollupReaderTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD._PROCESS_ANON_UNAVAILABLE = False

    tearDown = setUp

    def test_it_reads_the_Anonymous_field_and_converts_kB_to_MB(self) -> None:
        text = ("55c1b0a00000-7ffd0f7ff000 ---p 00000000 00:00 0 [rollup]\n"
                "Rss:              412345 kB\n"
                "Anonymous:        204800 kB\n"
                "Shared_Clean:      12345 kB\n")
        with mock.patch("builtins.open", mock.mock_open(read_data=text)):
            self.assertAlmostEqual(MOD._process_anon_mb(), 200.0)

    def test_Rss_is_NOT_used(self) -> None:
        """`Rss` counts file-backed pages the cgroup files under `file`.
        Conflating them is how a page-cache plateau once got called a leak
        (`#566`), and here it would inflate every attributed delta."""
        text = "Rss:  999999 kB\nAnonymous:  102400 kB\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=text)):
            self.assertAlmostEqual(MOD._process_anon_mb(), 100.0)

    def test_a_missing_file_is_reported_ONCE_and_then_short_circuits(self) -> None:
        """This runs per request; a missing file must not cost a syscall every
        time. It must also be LOUD once, not silent -- attribution stopping is
        otherwise invisible."""
        with mock.patch("builtins.open", side_effect=FileNotFoundError()) as op:
            self.assertIsNone(MOD._process_anon_mb())
            self.assertTrue(MOD._PROCESS_ANON_UNAVAILABLE)
            self.assertEqual(op.call_count, 1)
            self.assertIsNone(MOD._process_anon_mb())
            self.assertEqual(op.call_count, 1, "must not retry a known-absent file")

    def test_a_malformed_line_returns_None_rather_than_raising(self) -> None:
        with mock.patch("builtins.open", mock.mock_open(read_data="Anonymous:\n")):
            self.assertIsNone(MOD._process_anon_mb())

    def test_an_unreadable_file_does_not_latch_the_unavailable_flag(self) -> None:
        """A transient read error is not the same as an absent file: latching on
        it would disable attribution for the life of the process."""
        with mock.patch("builtins.open", side_effect=PermissionError()):
            self.assertIsNone(MOD._process_anon_mb())
        self.assertFalse(MOD._PROCESS_ANON_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
