from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from syndicate.features.bankroll_manager import compute_bet_size
from syndicate.features.wnba.live_lens import build_live_lens_page_context
from syndicate.features.shared.request_path_guard import ComputeInRequestPathError
from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path


class RequestPathGuardTests(unittest.TestCase):
    def test_live_lens_page_context_logs_warning_in_request_context(self) -> None:
        app = Flask(__name__)
        with app.test_request_context("/wnba/live-lens?date=2026-06-19", method="GET"):
            with patch("syndicate.features.shared.request_path_guard.logger.warning") as mocked_warning:
                build_live_lens_page_context("2026-06-19")

        mocked_warning.assert_called_once_with("WARNING: compute in request path", extra={"operation": "build_live_lens_page_context"})

    def test_compute_function_logs_warning_in_request_context(self) -> None:
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch("syndicate.features.shared.request_path_guard.logger.warning") as mocked_warning:
                result = compute_bet_size({"model_probability": 0.55, "implied_probability": 0.5, "odds": -110})

        mocked_warning.assert_called_once_with("WARNING: compute in request path", extra={"operation": "compute_bet_size"})
        self.assertIn("recommended_bet_size", result)

    def test_refuse_raises_in_request_context_on_hosted_deployment(self) -> None:
        # #56/#98/#109: this is the hard structural gate -- unlike the
        # warn-only helper above, a hosted (Render) deployment must never
        # merely log and proceed. #98's OOM (ops.py's admin-gated
        # candidate-trace debug endpoint calling _build_candidate_pool
        # directly) and #109's memory spike (the query API's force_refresh
        # cache-miss fallback calling _compute_response directly) were both
        # exactly this: heavy compute reached from a live web request on
        # production. No exemption for the debug endpoint either -- #98's
        # incident is exactly why not.
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
                with self.assertRaises(ComputeInRequestPathError):
                    refuse_if_compute_in_request_path("some_heavy_operation")

    def test_refuse_only_warns_in_request_context_when_not_hosted(self) -> None:
        # Local dev (no separate refresh-worker process) must keep working --
        # only a real hosted deployment enforces the hard gate.
        app = Flask(__name__)
        with app.test_request_context("/api/test", method="GET"):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RENDER", None)
                os.environ.pop("SYNDICATE_REQUIRE_HOSTED_STORAGE", None)
                with patch("syndicate.features.shared.request_path_guard.logger.warning") as mocked_warning:
                    refuse_if_compute_in_request_path("some_heavy_operation")
        mocked_warning.assert_called_once_with("WARNING: compute in request path", extra={"operation": "some_heavy_operation"})

    def test_refuse_is_a_no_op_outside_any_request_context(self) -> None:
        # refresh-worker is a plain script with no Flask app, so this must
        # never fire for its background loop regardless of hosted status --
        # has_request_context() is always False there.
        with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            refuse_if_compute_in_request_path("some_heavy_operation")  # must not raise

    def test_build_candidate_pool_refuses_on_hosted_web_request(self) -> None:
        # Integration-level: the actual entry point #98's incident went
        # through, not just the guard helper in isolation.
        from pipeline.intelligence_state import IntelligenceStateService

        service = IntelligenceStateService()
        app = Flask(__name__)
        with app.test_request_context("/api/ops/intelligence/candidate-trace", method="GET"):
            with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
                with self.assertRaises(ComputeInRequestPathError):
                    service._build_candidate_pool("2026-07-27", "fingerprint-1")

    def test_compute_response_refuses_on_hosted_web_request(self) -> None:
        # Integration-level: the actual entry point #109's incident went
        # through, not just the guard helper in isolation.
        from pipeline.intelligence_state import IntelligenceStateService

        service = IntelligenceStateService()
        app = Flask(__name__)
        with app.test_request_context("/api/intelligence/query", method="POST"):
            # RENDER=true alone also flips refresh_state_store's own strict
            # hosted-storage check, which requires SYNDICATE_DATA_ROOT to be
            # set before it will even read a manifest for fingerprinting --
            # unrelated to this guard, but has to be satisfied to reach it.
            with patch.dict(os.environ, {"RENDER": "true", "SYNDICATE_DATA_ROOT": str(Path(__file__).resolve().parent.parent / "data")}, clear=False):
                with self.assertRaises(ComputeInRequestPathError):
                    service._compute_response({"question": "top edges today", "date": "2026-07-27"}, force_refresh=True)
