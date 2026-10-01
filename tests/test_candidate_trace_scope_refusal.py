"""`/api/ops/intelligence/candidate-trace` refuses an unscoped full trace.

Finding 2026-10-01, local production fleet (gunicorn --workers 2 --threads 4
--timeout 60, as on Render): the bare call ran 87.98s and never answered. The
full path rebuilds the whole board in-request -- build_intelligence_overview
(force_refresh=True) over every sport, then _build_candidate_pool twice -- so
gunicorn killed the worker and the next request routed to it got
ConnectionResetError.

These assert the BRANCH, not just the clock: the heavy builders are patched to
raise, so a refusal that still reached them would surface as a 500 (or the
builder's own error), never as a quick 400. The scoped case proves the same
patches DO fire when the path is taken, so the refusal tests cannot pass
because the patch targets were wrong.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from syndicate.app import create_app

_TOKEN = "secret-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


class _HeavyBuildReached(AssertionError):
    pass


def _explode(*_args, **_kwargs):
    raise _HeavyBuildReached("heavy candidate build reached in-request")


class CandidateTraceScopeRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _get(self, query: str):
        from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE as service

        with patch.dict(os.environ, {"ADMIN_TOKEN": _TOKEN}, clear=False), patch(
            "syndicate.features.intelligence.build_intelligence_overview", side_effect=_explode
        ) as overview, patch.object(service, "_build_candidate_pool", side_effect=_explode) as pool:
            started = time.monotonic()
            response = self.client.get(f"/api/ops/intelligence/candidate-trace{query}", headers=_HEADERS)
            elapsed = time.monotonic() - started
        return response, overview, pool, elapsed

    def _assert_refused(self, query: str, missing: list[str]) -> None:
        response, overview, pool, elapsed = self._get(query)
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True)[:400])
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "scope_required")
        self.assertEqual(payload["missing_scope"], missing)
        self.assertIn("read_only=1", payload["detail"])
        overview.assert_not_called()
        pool.assert_not_called()
        self.assertLess(elapsed, 5.0)

    def test_bare_call_is_refused_before_any_build(self) -> None:
        self._assert_refused("", ["sport", "date"])

    def test_date_without_sport_is_refused(self) -> None:
        self._assert_refused("?date=2026-08-04", ["sport"])

    def test_sport_without_date_is_refused(self) -> None:
        self._assert_refused("?sport=mlb", ["date"])

    def test_blank_params_count_as_missing(self) -> None:
        self._assert_refused("?sport=%20&date=", ["sport", "date"])

    def test_scoped_call_still_reaches_the_full_trace(self) -> None:
        # Reachability: with both scopes the patched builder IS called, so the
        # assert_not_called() above is evidence, not a mis-aimed patch.
        response, overview, _pool, _elapsed = self._get("?sport=mlb&date=2026-08-04")
        overview.assert_called_once()
        self.assertEqual(response.status_code, 500)
        self.assertIn("build_intelligence_overview", response.get_json()["error"])

    def test_read_only_needs_no_scope(self) -> None:
        response, overview, pool, _elapsed = self._get("?read_only=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("read_only_trace", response.get_json())
        overview.assert_not_called()
        pool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
