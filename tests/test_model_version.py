"""Tests for syndicate.features.shared.model_version and its wiring into
intelligence_evaluation's prediction/recommendation recording -- Stage 5
of the learning-loop plan (attribution: which code produced this
prediction, so an accuracy change can be tied to a specific commit)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import model_version
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation


class CodeVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        model_version.code_version.cache_clear()

    def tearDown(self) -> None:
        model_version.code_version.cache_clear()

    def test_prefers_render_env_var(self) -> None:
        with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "abcdef1234567890"}, clear=False):
            self.assertEqual(model_version.code_version(), "abcdef123456")

    def test_falls_back_through_env_var_names_in_order(self) -> None:
        with patch.dict("os.environ", {"GIT_COMMIT": "1111222233334444"}, clear=False):
            model_version.code_version.cache_clear()
            self.assertEqual(model_version.code_version(), "111122223333")

    def test_falls_back_to_git_when_no_env_var_set(self) -> None:
        import os

        env_without_git_vars = {k: v for k, v in os.environ.items() if k not in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_VERSION")}
        with patch.dict("os.environ", env_without_git_vars, clear=True):
            with patch("syndicate.features.shared.model_version._git_commit", return_value="deadbeef0000"):
                self.assertEqual(model_version.code_version(), "deadbeef0000")

    def test_unknown_when_neither_env_nor_git_available(self) -> None:
        import os

        env_without_git_vars = {k: v for k, v in os.environ.items() if k not in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_VERSION")}
        with patch.dict("os.environ", env_without_git_vars, clear=True):
            with patch("syndicate.features.shared.model_version._git_commit", return_value=None):
                self.assertEqual(model_version.code_version(), "unknown")

    def test_cached_across_calls(self) -> None:
        with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "aaaa11112222"}, clear=False):
            first = model_version.code_version()
        with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "bbbb33334444"}, clear=False):
            second = model_version.code_version()
        self.assertEqual(first, second)  # cached, env change after first call has no effect


class LedgerStampingTests(unittest.TestCase):
    def setUp(self) -> None:
        model_version.code_version.cache_clear()

    def test_prediction_record_carries_model_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "cafef00dcafe"}, clear=False):
                model_version.code_version.cache_clear()
                prediction = record_prediction(query={"selected_date": "2026-08-02", "sport": "mlb"}, response={}, persist=True, ledger_path=ledger_path)
            self.assertEqual(prediction["model_version"], "cafef00dcafe")

    def test_prediction_id_is_unaffected_by_model_version(self) -> None:
        # model_version must never leak into the content hash prediction_id
        # is derived from -- otherwise the SAME prediction across a deploy
        # would mint a duplicate "new" ledger row instead of deduping.
        with tempfile.TemporaryDirectory() as tmp_dir_a, tempfile.TemporaryDirectory() as tmp_dir_b:
            with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "version0000aa"}, clear=False):
                model_version.code_version.cache_clear()
                pred_a = record_prediction(query={"selected_date": "2026-08-02", "sport": "mlb"}, response={}, persist=True, ledger_path=Path(tmp_dir_a) / "l.jsonl")
            with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "version1111bb"}, clear=False):
                model_version.code_version.cache_clear()
                pred_b = record_prediction(query={"selected_date": "2026-08-02", "sport": "mlb"}, response={}, persist=True, ledger_path=Path(tmp_dir_b) / "l.jsonl")
            self.assertEqual(pred_a["prediction_id"], pred_b["prediction_id"])
            self.assertNotEqual(pred_a["model_version"], pred_b["model_version"])

    def test_recommendation_inherits_parent_prediction_model_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "parentversio0"}, clear=False):
                model_version.code_version.cache_clear()
                prediction = record_prediction(query={"selected_date": "2026-08-02", "sport": "mlb"}, response={}, persist=True, ledger_path=ledger_path)
            with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "differentnow01"}, clear=False):
                model_version.code_version.cache_clear()
                recommendation = record_recommendation(
                    prediction_record=prediction,
                    recommendation={"market": "moneyline", "selection": "KC", "sport": "mlb"},
                    persist=True,
                    ledger_path=ledger_path,
                )
            self.assertEqual(recommendation["model_version"], "parentversio")


if __name__ == "__main__":
    unittest.main()
