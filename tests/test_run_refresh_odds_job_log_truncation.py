"""Run-artifact log truncation.

Measured 2026-08-03: `migration_runs/**` held 185.71MB of a 212.67MB
keyvalue total (2,549 keys) -- 87% of a 256MB shared instance already
evicting 37k keys under `allkeys-lru`, which does not spare TTL-less
coordination state. The worst offenders were captured subprocess console
output persisted straight into shared state: `odds_refresh.stderr.txt` and
`odds_refresh.json` at 8MB each. Upgrading the instance is not an option.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from scripts.run_refresh_odds_job import _max_run_artifact_text_bytes
from scripts.run_refresh_odds_job import _truncate_log_text
from scripts.run_refresh_odds_job import _truncate_payload_strings


class TruncateLogTextTests(unittest.TestCase):
    def test_short_text_is_returned_unchanged(self) -> None:
        self.assertEqual(_truncate_log_text("all good"), "all good")

    def test_oversized_text_keeps_the_tail_not_the_head(self) -> None:
        text = ("HEAD" * 100) + ("x" * 20000) + "THE-REAL-FAILURE"
        result = _truncate_log_text(text, limit=4096)
        # The tail is where the failure is -- keeping the head would discard
        # exactly the part worth reading.
        self.assertIn("THE-REAL-FAILURE", result)
        self.assertNotIn("HEADHEADHEAD", result)

    def test_truncation_is_announced(self) -> None:
        result = _truncate_log_text("y" * 20000, limit=4096)
        self.assertIn("truncated", result)

    def test_result_respects_the_limit_with_room_for_the_notice(self) -> None:
        result = _truncate_log_text("z" * 500000, limit=4096)
        self.assertLess(len(result.encode("utf-8")), 4096 + 200)

    def test_none_and_empty_are_safe(self) -> None:
        self.assertEqual(_truncate_log_text(""), "")
        self.assertEqual(_truncate_log_text(None), "")  # type: ignore[arg-type]


class TruncatePayloadStringsTests(unittest.TestCase):
    def test_payload_stays_valid_json_after_truncation(self) -> None:
        payload = {"ok": True, "returnCode": 0, "stdout": "q" * 400000}
        trimmed = _truncate_payload_strings(payload)
        # Truncating the *serialized* text would corrupt the JSON and break
        # /api/ops/odds-refresh/status's parsing -- fields are trimmed instead.
        reloaded = json.loads(json.dumps(trimmed))
        self.assertTrue(reloaded["ok"])
        self.assertEqual(reloaded["returnCode"], 0)
        self.assertLess(len(reloaded["stdout"].encode("utf-8")), 400000)

    def test_small_fields_and_non_strings_are_untouched(self) -> None:
        payload = {"ok": False, "command": ["a", "b"], "error": "boom"}
        self.assertEqual(_truncate_payload_strings(payload), payload)

    def test_nested_payload_strings_are_truncated(self) -> None:
        payload = {"result": {"stderr": "e" * 400000, "pid": 42}}
        trimmed = _truncate_payload_strings(payload)
        self.assertLess(len(trimmed["result"]["stderr"].encode("utf-8")), 400000)
        self.assertEqual(trimmed["result"]["pid"], 42)


class MaxRunArtifactTextBytesTests(unittest.TestCase):
    def test_default_is_bounded_well_under_the_backend_write_ceiling(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_MAX_RUN_ARTIFACT_TEXT_BYTES", None)
            # The backend's own write ceiling is 8MB; the observed keys sat
            # right at it. The default must be orders of magnitude below.
            self.assertLess(_max_run_artifact_text_bytes(), 1_000_000)

    def test_env_override_is_honoured(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_MAX_RUN_ARTIFACT_TEXT_BYTES": "12345"}):
            self.assertEqual(_max_run_artifact_text_bytes(), 12345)

    def test_garbage_and_tiny_values_fall_back_to_a_safe_floor(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_MAX_RUN_ARTIFACT_TEXT_BYTES": "not-a-number"}):
            self.assertEqual(_max_run_artifact_text_bytes(), 65536)
        with patch.dict(os.environ, {"SYNDICATE_MAX_RUN_ARTIFACT_TEXT_BYTES": "10"}):
            self.assertEqual(_max_run_artifact_text_bytes(), 4096)


if __name__ == "__main__":
    unittest.main()
