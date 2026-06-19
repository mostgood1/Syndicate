from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

from syndicate.features.bankroll_manager import compute_bet_size
from syndicate.features.wnba.live_lens import build_live_lens_page_context


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
