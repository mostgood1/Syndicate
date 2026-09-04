"""Make `#632`'s all-request attribution RECONCILABLE.

The previous attempt reported `/api/ops/artifacts/export` at "+145.10 of
+145.10 MB -- 100%". That was `sum(sampled)/sum(sampled)`: 100% by construction,
over a denominator of two routes chosen by hand. The fix is to compare what was
attributed against the PROCESS's own climb and name the RESIDUAL.

Trying that against the existing emissions surfaced two defects that made the
comparison impossible, both measured on production logs 2026-09-04:

1. `routes` IS TRUNCATED to `top=12` for readability. pid 80 at 19:38:38 had
   `distinct_routes=13, len(routes)=12`, and differencing it read **4842%
   unexplained**. A reconciliation total must never come from a list that is
   truncated for display.

2. `pid` IS NOT A PROCESS IDENTITY. pid 79's `solo_attributed` went **800 -> 200**
   at 19:55:32 -- a gunicorn worker respawned and the OS reused the pid.
   Differencing across that boundary read **-117% coverage**.

Both produced numbers that looked like memory behaviour and were arithmetic
artifacts. These tests pin the two fixes so the residual can be believed.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


def _anon(*values: float):
    """Scripted `_process_anon_mb` readings -- start, end, start, end, ...

    Padded with the final value, because the reader is not the only caller:
    `request_memory_attribution_payload` also samples it for
    `process_anon_mb_now`. Hand-counting every call site makes a test that
    breaks whenever an unrelated field is added, and the padding is harmless
    here because the payload is always read AFTER the scripted requests.
    """
    return mock.patch.object(MOD, "_process_anon_mb",
                             side_effect=list(values) + [values[-1]] * 16)


def _one_request(route: str, emit_every: int = 10 ** 9) -> None:
    token = MOD.note_request_start(route)
    MOD.note_request_end(token, route, emit_every=emit_every)


class UntruncatedTotalTests(unittest.TestCase):

    def setUp(self) -> None:
        self._env = mock.patch.dict(
            os.environ, {"SYNDICATE_REQUEST_MEMORY_PROFILE": "1"}, clear=False)
        self._env.start()
        MOD.reset_request_memory_attribution()

    def tearDown(self) -> None:
        self._env.stop()
        MOD.reset_request_memory_attribution()

    def test_the_total_covers_routes_the_displayed_list_DROPS(self) -> None:
        """THE defect. With `top=1` the shown list holds one route; the total
        must still carry both, or every window that serves more routes than the
        display cap under-reports what was attributed."""
        with _anon(100.0, 130.0, 130.0, 137.5):
            _one_request("/a")
            _one_request("/b")

            payload = MOD.request_memory_attribution_payload(top=1)

            self.assertEqual(len(payload["routes"]), 1)
            self.assertEqual(payload["distinct_routes"], 2)
            self.assertAlmostEqual(sum(r["total_mb"] for r in payload["routes"]), 30.0, places=2)
            self.assertAlmostEqual(payload["attributed_total_mb"], 37.5, places=2)

    def test_the_total_equals_the_shown_sum_when_NOTHING_is_truncated(self) -> None:
        """The control. If these disagreed with no truncation, the total would be
        measuring something other than the routes."""
        with _anon(100.0, 130.0, 130.0, 137.5):
            _one_request("/a")
            _one_request("/b")

            payload = MOD.request_memory_attribution_payload(top=12)

            self.assertAlmostEqual(sum(r["total_mb"] for r in payload["routes"]),
                                   payload["attributed_total_mb"], places=2)

    def test_a_request_that_FREED_memory_reduces_the_total(self) -> None:
        """Route totals can legitimately fall -- production showed
        `/api/ops/artifacts/publish` at -53.59 MB over a window. A total that
        only accumulated growth would not reconcile against a process that fell."""
        with _anon(100.0, 130.0, 130.0, 110.0):
            _one_request("/a")
            _one_request("/b")

            self.assertAlmostEqual(
                MOD.request_memory_attribution_payload()["attributed_total_mb"],
                10.0, places=2)

    def test_the_total_RECONCILES_against_the_process_climb(self) -> None:
        """The identity the whole exercise rests on: attributed + residual is the
        process's own movement, with the residual carrying everything unsampled."""
        with _anon(100.0, 130.0, 130.0, 137.5):
            _one_request("/a")
            _one_request("/b")

            attributed = MOD.request_memory_attribution_payload()["attributed_total_mb"]
            process_climb = 137.5 - 100.0
            residual = process_climb - attributed

            self.assertAlmostEqual(attributed, 37.5, places=2)
            self.assertAlmostEqual(residual, 0.0, places=2)

    def test_a_SKIPPED_request_lands_in_the_residual_not_the_total(self) -> None:
        """Requests skipped for concurrency are unattributed BY DESIGN, and
        production skips 51-172 per window. They must show up as residual rather
        than silently inflating coverage."""
        with _anon(100.0, 130.0):
            outer = MOD.note_request_start("/a")
            inner = MOD.note_request_start("/a")          # overlaps -> skipped
            self.assertIsNone(inner)
            MOD.note_request_end(inner, "/a", emit_every=10 ** 9)
            MOD.note_request_end(outer, "/a", emit_every=10 ** 9)

            payload = MOD.request_memory_attribution_payload()

            self.assertAlmostEqual(payload["attributed_total_mb"], 0.0, places=2)

    def test_ONE_overlap_increments_skipped_concurrent_TWICE(self) -> None:
        """`skipped_concurrent` counts CONTAMINATED WINDOWS, not skipped
        requests, and a single overlap contaminates two: the inner request is
        refused a token at start, and the outer then fails `alone_throughout` at
        end because the sequence moved under it.

        Pinned because it changes how the production figure reads. A window
        showing `skipped_concurrent=172` does NOT mean 172 unattributed
        requests -- up to half of that count can be the same overlaps counted
        from the other side, and treating it as a request count would overstate
        how much of the residual is explained by skipping.
        """
        with _anon(100.0, 130.0):
            outer = MOD.note_request_start("/a")
            inner = MOD.note_request_start("/a")
            MOD.note_request_end(inner, "/a", emit_every=10 ** 9)
            MOD.note_request_end(outer, "/a", emit_every=10 ** 9)

            self.assertEqual(MOD.request_memory_attribution_payload()["skipped_concurrent"], 2)

    def test_reset_clears_the_total(self) -> None:
        with _anon(100.0, 130.0):
            _one_request("/a")

        MOD.reset_request_memory_attribution()

        self.assertEqual(
            MOD.request_memory_attribution_payload()["attributed_total_mb"], 0.0)


class ProcessIdentityTests(unittest.TestCase):

    def test_the_payload_carries_a_PROCESS_token_not_just_a_pid(self) -> None:
        """A pid is reused after a worker respawns. Production differenced across
        exactly that boundary and read -117% coverage."""
        payload = MOD.request_memory_attribution_payload()

        self.assertEqual(payload["proc_token"], MOD._proc_token())
        self.assertEqual(len(MOD._proc_token()), 12)

    def test_the_token_is_STABLE_within_a_process(self) -> None:
        """It must not change per emission, or every window would look like a
        restart and nothing could ever be differenced."""
        first = MOD.request_memory_attribution_payload()["proc_token"]
        second = MOD.request_memory_attribution_payload()["proc_token"]

        self.assertEqual(first, second)

    def test_a_FORKED_WORKER_does_not_inherit_the_parent_token(self) -> None:
        """THE defect this token was re-written for, and it shipped inert once.

        The first version generated the token at IMPORT, and gunicorn forks its
        workers after the import -- so every worker carried the identical token.
        Measured in production 2026-09-04 20:24-20:26: pid 99 and pid 98 emitted
        the same `6178fc632433`, merging two workers into one apparent series.
        That is worse than having no token: a shared one reads as continuity
        rather than as a collision, so differencing produced a confident number
        from two different processes.
        """
        parent = MOD._proc_token()

        with mock.patch.object(MOD.os, "getpid", return_value=987654):
            child = MOD._proc_token()
            self.assertNotEqual(child, parent)
            self.assertEqual(MOD._proc_token(), child, "stable within the child too")

    def test_a_RESPAWNED_worker_on_a_RECYCLED_pid_gets_a_fresh_token(self) -> None:
        """The other direction. A new process starts with empty module state, so
        its first call disagrees with the recorded pid and mints a new token even
        when the OS handed back the same pid."""
        MOD._PROC_TOKEN_STATE.update({"pid": None, "token": None})
        first = MOD._proc_token()

        MOD._PROC_TOKEN_STATE.update({"pid": None, "token": None})   # fresh process
        second = MOD._proc_token()

        self.assertNotEqual(first, second)

    def test_reset_does_NOT_change_the_token(self) -> None:
        """Reset clears counters; it does not make a new process. If reset
        rotated the token, a reader would see a restart that never happened."""
        before = MOD._proc_token()

        MOD.reset_request_memory_attribution()

        self.assertEqual(MOD.request_memory_attribution_payload()["proc_token"], before)


if __name__ == "__main__":
    unittest.main()
