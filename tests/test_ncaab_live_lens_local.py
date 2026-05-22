from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaab.live_lens import build_live_lens_page_context
from syndicate.features.ncaab.sources import live_lines_payload
from syndicate.features.ncaab.sources import live_lens_tuning_payload
from syndicate.features.ncaab.sources import live_state_payload


class NcaabLiveLensLocalTests(unittest.TestCase):
    def test_live_state_payload_returns_mirror_unavailable_error_without_source_fallback(self) -> None:
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value=None):
            payload = live_state_payload("2026-05-20")

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["kind"], "live_state")
        self.assertEqual(payload["source"], "local_mirror")
        self.assertIn("Refresh the NCAAB source mirror", payload["message"])

    def test_live_lines_payload_returns_empty_error_payload_without_source_fallback(self) -> None:
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value=None):
            payload = live_lines_payload("2026-05-20", ["game-1"])

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["kind"], "live_lines")
        self.assertEqual(payload["lines"], {})
        self.assertEqual(payload["source"], "local_mirror")

    def test_live_lens_tuning_payload_returns_local_error_payload_when_missing(self) -> None:
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value=None):
            payload = live_lens_tuning_payload()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["source"], "local_mirror")
        self.assertIsNone(payload["pace_hi"])

    def test_live_lens_page_context_reports_mirror_unavailable_state(self) -> None:
        with patch(
            "syndicate.features.ncaab.live_lens.live_state_payload",
            return_value={"status": "error", "date": "2026-05-20", "count": 0, "message": "mirror missing"},
        ), patch(
            "syndicate.features.ncaab.live_lens.live_lens_tuning_payload",
            return_value={"status": "error", "pace_hi": None, "pps_hi": None},
        ):
            context = build_live_lens_page_context("2026-05-20")

        self.assertEqual(context["warning_panel"]["title"], "Live state unavailable")
        self.assertIn("mirror missing", context["warning_panel"]["list_items"][0])
        self.assertEqual(context["source_title"], "NCAAB mirrored live scoreboard + live lines")


if __name__ == "__main__":
    unittest.main()