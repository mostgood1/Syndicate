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


class CandidateTraceScopedBoundTests(unittest.TestCase):
    """A scoped trace hydrates one sport and skips the whole-board pool.

    Before: `?sport=mlb&date=...` still built every configured sport's overview
    and ran `_build_candidate_pool` twice, so the refusal above only stopped the
    accidental bare call.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _get(self, query: str):
        from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE as service

        with patch.dict(os.environ, {"ADMIN_TOKEN": _TOKEN}, clear=False), patch(
            "syndicate.features.intelligence.build_intelligence_overview",
            return_value=[{"slug": "mlb", "dashboard_games": []}],
        ) as overview, patch("syndicate.features.intelligence.collect_candidates", return_value=[]), patch(
            "syndicate.features.intelligence._collect_candidates", return_value=[]
        ), patch.object(service, "_available_sport_manifests", return_value={}), patch.object(
            service, "_source_state_fingerprint", return_value="fp"
        ), patch.object(service, "_candidate_pool_key", return_value="k"), patch.object(
            service, "_build_candidate_pool", return_value={"candidate_count": 0}
        ) as pool:
            response = self.client.get(f"/api/ops/intelligence/candidate-trace{query}", headers=_HEADERS)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        return response.get_json(), overview, pool

    def test_overview_is_built_for_the_requested_sport_only(self) -> None:
        _payload, overview, _pool = self._get("?sport=MLB&date=2026-08-04")
        overview.assert_called_once()
        self.assertEqual(overview.call_args.kwargs.get("sports"), ["mlb"])

    def test_pool_rebuild_is_skipped_by_default_and_says_so(self) -> None:
        payload, _overview, pool = self._get("?sport=mlb&date=2026-08-04")
        pool.assert_not_called()
        self.assertFalse(payload["pool_sections_ran"])
        for section in ("manifest_check", "full_pool_check", "app_context_pool_check"):
            self.assertIn("pool=1", payload[section]["skipped"])

    def test_pool_rebuild_runs_when_asked(self) -> None:
        payload, _overview, pool = self._get("?sport=mlb&date=2026-08-04&pool=1")
        self.assertEqual(pool.call_count, 2)
        self.assertTrue(payload["pool_sections_ran"])
        self.assertEqual(payload["full_pool_check"]["candidate_count"], 0)

    def test_requested_sport_configured_tells_absent_from_misspelled(self) -> None:
        payload, _overview, _pool = self._get("?sport=mlb&date=2026-08-04")
        self.assertTrue(payload["requested_sport_configured"])
        payload, _overview, _pool = self._get("?sport=cricket&date=2026-08-04")
        self.assertFalse(payload["requested_sport_configured"])


if __name__ == "__main__":
    unittest.main()
