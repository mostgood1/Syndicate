"""The CFBD monthly-quota latch: does it stop the call, and only the right one.

WHY THIS EXISTS. Measured on refresh-worker 2026-08-31:

    SEASON_PROJECTION_LAUNCHING sport=ncaaf reason=artifact_stale
      age_seconds=366893  interval_seconds=86400

The configured interval is once per DAY and it was firing about 24x that --
a failing run never refreshes the artifact, so every worker tick re-triggers it.
14 generator attempts that day, each dying on a quota CFBD had already said was
exhausted, with ten snapshot builders sharing the same key. A feedback loop that
hammers hardest exactly when the quota is scarcest.

THE FIRST TEST IS A REACHABILITY TEST -- does a latched call make NO request --
because a correctness test over the policy alone would pass whether or not the
latch was ever consulted, which is the failure mode that matters here.
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from syndicate.features.ncaaf import cfbd_quota_latch as latch


class _Isolated(unittest.TestCase):
    """Every test writes to its own data root. The latch is a real file on the
    mounted disk in production, so a test that shared one would leak state
    between cases and, worse, could latch a developer's own machine."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        patcher = mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)


class WhatCountsAsAMonthlyQuota(_Isolated):
    def test_the_vendor_wording_is_recognised(self):
        self.assertTrue(latch.is_monthly_quota_body('{"message":"Monthly call quota exceeded."}'))

    def test_a_short_window_throttle_is_NOT_latched(self):
        """A throttle and an exhausted month arrive with the SAME 429 and need
        opposite responses. Latching a throttle turns 30 seconds of waiting into
        a multi-day outage."""
        for body in ('{"message":"Too many requests"}', "Rate limit exceeded, retry shortly", "", None):
            with self.subTest(body=body):
                self.assertFalse(latch.is_monthly_quota_body(body))
                self.assertIsNone(latch.note_quota_exhausted(body))


class TheLatchItself(_Isolated):
    def test_off_then_on(self):
        latch.raise_if_latched("GET /ppa/teams")  # not latched: returns
        latch.note_quota_exhausted('{"message":"Monthly call quota exceeded."}')
        with self.assertRaises(latch.QuotaExhausted):
            latch.raise_if_latched("GET /ppa/teams")

    def test_it_expires_at_the_month_roll_not_after_a_duration(self):
        """The quota is monthly, so the honest expiry is 00:00 UTC on the 1st.
        A fixed TTL would either keep calling after the quota returned or keep
        refusing after it did."""
        expires = latch.note_quota_exhausted('{"message":"Monthly call quota exceeded."}')
        stamp = datetime.fromtimestamp(expires, tz=timezone.utc)
        self.assertEqual((stamp.day, stamp.hour, stamp.minute), (1, 0, 0))
        self.assertGreater(stamp, datetime.now(timezone.utc))

    def test_an_expired_latch_lets_the_call_through(self):
        path = latch.latch_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"expires_epoch": time.time() - 1}), encoding="utf-8")
        self.assertIsNone(latch.quota_latched_until())
        latch.raise_if_latched("GET /ppa/teams")  # must not raise

    def test_an_unreadable_latch_FAILS_OPEN(self):
        """Deliberately the opposite of this repo's usual rule. A wrong 'not
        latched' costs one wasted call; a wrong 'latched' is a multi-day outage
        on a service that is actually healthy."""
        path = latch.latch_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        self.assertIsNone(latch.quota_latched_until())
        latch.raise_if_latched("GET /ppa/teams")

    def test_it_survives_a_new_process(self):
        """The generator runs as a FRESH PROCESS on every launch, so an
        in-memory flag would be forgotten between exactly the attempts this
        exists to suppress. Re-reading from disk is the whole design."""
        latch.note_quota_exhausted('{"message":"Monthly call quota exceeded."}')
        self.assertIsNotNone(latch.quota_latched_until())
        latch.clear_latch()
        self.assertIsNone(latch.quota_latched_until())


class ItActuallySuppressesTheRequest(_Isolated):
    def test_a_latched_generator_call_makes_NO_http_request(self):
        """The reachability test. Everything else here could pass while the
        latch was never consulted by a caller."""
        import scripts.generate_smartsim2_ncaaf_projections as gen

        latch.note_quota_exhausted('{"message":"Monthly call quota exceeded."}')
        with mock.patch("urllib.request.urlopen") as opened:
            with self.assertRaises(latch.QuotaExhausted):
                gen._cfbd_get("/ppa/teams", {"year": 2026})
        opened.assert_not_called()

    def test_an_unlatched_generator_call_DOES_reach_the_transport(self):
        """off != on, in the other direction -- otherwise a latch that blocked
        everything unconditionally would pass the test above."""
        import scripts.generate_smartsim2_ncaaf_projections as gen

        latch.clear_latch()
        payload = mock.MagicMock()
        payload.read.return_value = b"[]"
        payload.__enter__ = lambda s: payload
        payload.__exit__ = lambda s, *a: False
        with mock.patch("urllib.request.urlopen", return_value=payload) as opened:
            with mock.patch.dict("os.environ", {"CFBD_API_KEY": "test-key"}):
                gen._cfbd_get("/ppa/teams", {"year": 2026})
        opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
