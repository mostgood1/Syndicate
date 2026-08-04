from __future__ import annotations

import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared.shadow_candidate_ledger import (
    _is_sampled_in,
    prune_old_shadow_ledger_files,
    record_shadow_candidates,
    shadow_ledger_path,
)


class ShadowCandidateLedgerTests(unittest.TestCase):
    def test_disabled_by_default_is_a_safe_no_op(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = record_shadow_candidates(
                [{"candidate_id": "c1", "sport_slug": "mlb", "market": "moneyline"}],
                selected_date="2026-08-04",
                root=root,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")

    def test_enabled_writes_a_lean_record_to_the_bounded_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED": "true",
                    "SYNDICATE_SHADOW_CANDIDATE_LEDGER_SAMPLE_RATE": "1.0",
                },
                clear=False,
            ):
                result = record_shadow_candidates(
                    [
                        {
                            "candidate_id": "c1",
                            "sport_slug": "mlb",
                            "market": "moneyline",
                            "selection": "Home ML",
                            "event_id": "game-1",
                            "odds": "+110",
                            "model_probability": 0.55,
                            "implied_probability": 0.48,
                            "edge": 0.07,
                            "_shadow_rejection_reason": "edge_below_threshold",
                            # Fields that must NOT survive into the lean record --
                            # this is exactly the kind of bulk payload that made
                            # the real evaluation ledger's records large.
                            "market_context": {"some": "large blob" * 50},
                            "simulation_detail": list(range(500)),
                        }
                    ],
                    selected_date="2026-08-04",
                    root=root,
                )
            self.assertTrue(result["ok"])
            self.assertFalse(result["skipped"])
            self.assertEqual(result["sampled"], 1)

            path = shadow_ledger_path("2026-08-04", root=root)
            self.assertTrue(path.exists())
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            record = lines[0]
            self.assertTrue(record["shadow"])
            self.assertEqual(record["rejection_reason"], "edge_below_threshold")
            self.assertEqual(record["candidate_id"], "c1")
            self.assertEqual(record["event_id"], "game-1")
            self.assertNotIn("market_context", record)
            self.assertNotIn("simulation_detail", record)

    def test_per_cycle_cap_is_enforced_even_at_full_sample_rate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = [
                {"candidate_id": f"c{i}", "sport_slug": "mlb", "market": "moneyline", "_shadow_rejection_reason": "edge_below_threshold"}
                for i in range(10)
            ]
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED": "true",
                    "SYNDICATE_SHADOW_CANDIDATE_LEDGER_SAMPLE_RATE": "1.0",
                    "SYNDICATE_SHADOW_CANDIDATE_LEDGER_MAX_PER_CYCLE": "3",
                },
                clear=False,
            ):
                result = record_shadow_candidates(candidates, selected_date="2026-08-04", root=root)
            self.assertEqual(result["sampled"], 3)
            self.assertEqual(result["considered"], 10)
            path = shadow_ledger_path("2026-08-04", root=root)
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 3)

    def test_zero_cap_disables_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(
                os.environ,
                {"SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED": "true", "SYNDICATE_SHADOW_CANDIDATE_LEDGER_MAX_PER_CYCLE": "0"},
                clear=False,
            ):
                result = record_shadow_candidates(
                    [{"candidate_id": "c1", "sport_slug": "mlb"}], selected_date="2026-08-04", root=root
                )
            self.assertTrue(result["skipped"])
            self.assertEqual(result["reason"], "cap_is_zero")
            self.assertFalse(shadow_ledger_path("2026-08-04", root=root).exists())

    def test_sampling_is_deterministic_per_candidate_identity(self) -> None:
        candidate = {"candidate_id": "stable-id-123", "sport_slug": "mlb"}
        first = _is_sampled_in(candidate, rate=0.3)
        second = _is_sampled_in(candidate, rate=0.3)
        self.assertEqual(first, second)

    def test_sampling_rate_zero_never_samples_rate_one_always_samples(self) -> None:
        candidate = {"candidate_id": "any-id", "sport_slug": "mlb"}
        self.assertFalse(_is_sampled_in(candidate, rate=0.0))
        self.assertTrue(_is_sampled_in(candidate, rate=1.0))

    def test_missing_candidate_id_falls_back_to_a_stable_composite_key(self) -> None:
        candidate = {"sport_slug": "mlb", "market": "moneyline", "selection": "Home ML", "event_id": "game-1"}
        first = _is_sampled_in(candidate, rate=0.5)
        second = _is_sampled_in(dict(candidate), rate=0.5)
        self.assertEqual(first, second)

    def test_no_rejected_candidates_is_a_safe_no_op(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED": "true"}, clear=False):
                result = record_shadow_candidates([], selected_date="2026-08-04", root=root)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["reason"], "no_rejected_candidates")

    def test_a_write_failure_is_reported_not_raised(self) -> None:
        # root is a FILE, not a directory -- mkdir(parents=True) under it fails.
        with TemporaryDirectory() as tmp:
            blocking_file = Path(tmp) / "not_a_directory"
            blocking_file.write_text("x", encoding="utf-8")
            root = blocking_file / "shadow_candidate_ledger"
            with patch.dict(
                os.environ,
                {"SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED": "true", "SYNDICATE_SHADOW_CANDIDATE_LEDGER_SAMPLE_RATE": "1.0"},
                clear=False,
            ):
                result = record_shadow_candidates(
                    [{"candidate_id": "c1", "sport_slug": "mlb"}], selected_date="2026-08-04", root=root
                )
            self.assertFalse(result["ok"])
            self.assertIn("error", result)


class PruneOldShadowLedgerFilesTests(unittest.TestCase):
    def test_removes_files_older_than_retention_window_keeps_recent_ones(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(parents=True, exist_ok=True)
            old_path = root / "2026-07-01.jsonl"
            recent_path = root / "2026-08-03.jsonl"
            old_path.write_text('{"a": 1}\n', encoding="utf-8")
            recent_path.write_text('{"a": 2}\n', encoding="utf-8")

            with patch.dict(os.environ, {"SYNDICATE_SHADOW_CANDIDATE_LEDGER_RETENTION_DAYS": "21"}, clear=False):
                result = prune_old_shadow_ledger_files(root=root, today=date(2026, 8, 4))

            self.assertTrue(result["ok"])
            self.assertEqual(result["removed"], 1)
            self.assertFalse(old_path.exists())
            self.assertTrue(recent_path.exists())

    def test_missing_root_is_a_safe_no_op(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "does_not_exist"
            result = prune_old_shadow_ledger_files(root=root, today=date(2026, 8, 4))
        self.assertTrue(result["ok"])
        self.assertEqual(result["removed"], 0)

    def test_non_date_filenames_are_left_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(parents=True, exist_ok=True)
            weird_path = root / "unknown.jsonl"
            weird_path.write_text('{"a": 1}\n', encoding="utf-8")
            result = prune_old_shadow_ledger_files(root=root, today=date(2026, 8, 4))
            self.assertEqual(result["removed"], 0)
            self.assertTrue(weird_path.exists())


if __name__ == "__main__":
    unittest.main()
